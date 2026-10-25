"""Article normalization, URL canonicalization, HTML sanitization, and parsing."""

from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from daily_tech_brief.models import Article, OpportunityMetadata, SourceConfig

logger = logging.getLogger(__name__)

# Tracking query parameters to strip for canonical URL determination
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "igshid",
    "ref",
    "source",
    "ref_src",
}

# HTML tag removal regex
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(raw_text: Optional[str]) -> str:
    """Safely strip HTML tags, unescape HTML entities, and normalize whitespace."""
    if not raw_text:
        return ""
    # Decode HTML entities first so encoded tags like &lt;b&gt; are safely caught
    unescaped = html.unescape(raw_text)
    # Strip HTML tags
    no_html = TAG_RE.sub(" ", unescaped)
    # Normalize excessive whitespace
    return WHITESPACE_RE.sub(" ", no_html).strip()


def canonicalize_url(raw_url: str) -> str:
    """Normalize a URL by stripping tracking parameters while preserving query params."""
    if not raw_url or not raw_url.strip():
        return ""

    url = raw_url.strip()
    try:
        parsed = urlparse(url)
        # Filter tracking parameters
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_pairs = [
            (k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS
        ]
        new_query = urlencode(filtered_pairs)

        # Normalize scheme and netloc to lowercase
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Remove trailing slash from path unless it's just root '/'
        path = parsed.path
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]

        # Remove fragment for canonical comparison
        canonical = urlunparse((scheme, netloc, path, parsed.params, new_query, ""))
        return canonical
    except Exception as e:
        logger.debug(f"URL canonicalization fallback for {raw_url}: {e}")
        return url


def generate_article_id(canonical_url: str) -> str:
    """Generate deterministic article ID using SHA-256 of canonical URL."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]


def generate_content_hash(title: str, description: str) -> str:
    """Generate deterministic content hash for caching summaries and change detection."""
    combined = f"{title.strip().lower()}\n{description.strip().lower()}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def parse_timestamp(
    entry_dict: Dict[str, Any], default_tz: ZoneInfo
) -> Optional[datetime]:
    """Extract and parse publication date into a timezone-aware datetime.
    
    Returns None if missing or malformed (never fabricates dates).
    """
    # 1. feedparser parsed time tuple: published_parsed or updated_parsed
    time_struct = entry_dict.get("published_parsed") or entry_dict.get("updated_parsed")
    if time_struct:
        try:
            # Struct is in UTC
            dt = datetime(*time_struct[:6], tzinfo=timezone.utc)
            return dt.astimezone(default_tz)
        except Exception:
            pass

    # 2. String representation: published, updated, or pubDate
    date_str = (
        entry_dict.get("published")
        or entry_dict.get("updated")
        or entry_dict.get("pubDate")
        or entry_dict.get("created")
    )
    if date_str and isinstance(date_str, str):
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=default_tz)
            return dt.astimezone(default_tz)
        except Exception:
            pass

        # Try ISO 8601 parsing
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=default_tz)
            return dt.astimezone(default_tz)
        except Exception:
            pass

    return None


def extract_opportunity_metadata(
    title: str, description: str, url: str, is_opp_source: bool
) -> Optional[OpportunityMetadata]:
    """Identify opportunity information (internship, hackathon, fellowship, grant)."""
    text = f"{title} {description}".lower()
    
    # Check if this qualifies as an opportunity
    is_internship = any(w in text for w in ["internship", "intern", "summer 2025", "summer 2026", "software engineer intern", "co-op"])
    is_hackathon = any(w in text for w in ["hackathon", "hackathon submission", "student competition", "code jam"])
    is_fellowship = any(w in text for w in ["fellowship", "mentorship", "gsoc", "lfx mentorship", "outreachy"])

    if not (is_opp_source or is_internship or is_hackathon or is_fellowship):
        return None

    # Determine type
    if is_hackathon:
        opp_type = "Hackathon"
    elif is_internship:
        opp_type = "Internship"
    elif is_fellowship:
        opp_type = "Mentorship / Fellowship"
    else:
        opp_type = "Student Program"

    # Simple heuristic deadline detection
    raw_text = f"{title} {description}"
    deadline = None
    deadline_match = re.search(
        r"(?:deadline|apply by|applications close|due date|ends on)[:\s]+([A-Za-z]+ \d{1,2},? \d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        raw_text,
        re.IGNORECASE,
    )
    if deadline_match:
        deadline = deadline_match.group(1)

    location = "Remote / Unspecified"
    if "remote" in text:
        location = "Remote"
    elif "hybrid" in text:
        location = "Hybrid"
    elif "onsite" in text:
        location = "Onsite"

    return OpportunityMetadata(
        organization="Announced Organization",
        opportunity_type=opp_type,
        location=location,
        application_url=url,
        deadline=deadline,
        eligibility="Students / Early Career (Review posting for exact criteria)",
        verification_status="unverified",  # Clearly identify as unverified unless checked
    )


def normalize_feed_entry(
    entry: Dict[str, Any],
    source: SourceConfig,
    tz: ZoneInfo,
    now: Optional[datetime] = None,
) -> Optional[Article]:
    """Convert raw feed entry dictionary to normalized Article instance."""
    now_dt = now or datetime.now(tz)
    
    # Original URL
    raw_url = entry.get("link") or entry.get("id") or ""
    if not raw_url:
        logger.debug(f"Skipping entry without URL in source {source.id}")
        return None

    canonical_url = canonicalize_url(raw_url)
    if not canonical_url:
        return None

    # Clean title
    raw_title = entry.get("title", "")
    title = clean_text(raw_title)
    if not title:
        logger.debug(f"Skipping entry without title in source {source.id} ({canonical_url})")
        return None

    # Clean description / summary
    raw_desc = (
        entry.get("summary")
        or entry.get("description")
        or (entry.get("content", [{}])[0].get("value") if entry.get("content") else "")
        or ""
    )
    description = clean_text(raw_desc)

    # Author
    author = entry.get("author") or (entry.get("authors", [{}])[0].get("name") if entry.get("authors") else None)
    if author:
        author = clean_text(author)

    # Timestamp
    published_at = parse_timestamp(entry, tz)

    # Opportunities
    opp_metadata = extract_opportunity_metadata(title, description, canonical_url, source.is_opportunity_source)

    article_id = generate_article_id(canonical_url)
    content_hash = generate_content_hash(title, description)

    return Article(
        id=article_id,
        canonical_url=canonical_url,
        original_url=raw_url,
        title=title,
        description=description,
        source_id=source.id,
        source_name=source.name,
        author=author,
        published_at=published_at,
        first_seen_at=now_dt,
        categories=list(source.categories),
        source_credibility_score=source.reliability_weight,
        content_hash=content_hash,
        is_opportunity=(opp_metadata is not None),
        opportunity_data=opp_metadata,
    )
