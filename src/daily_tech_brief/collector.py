"""Feed collector with polite backoff, conditional GET, and error isolation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import feedparser
import requests

from daily_tech_brief.models import Article, SourceConfig
from daily_tech_brief.normalizer import normalize_feed_entry

logger = logging.getLogger(__name__)

USER_AGENT = "DailyTechBriefBot/1.0 (+https://github.com/daily-tech-brief)"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB limit
MAX_RETRIES = 2
DEFAULT_TIMEOUT = 15


@dataclass
class FetchResult:
    """Detailed record of a source fetch attempt."""
    source_id: str
    status_code: Optional[int]
    status: str  # SUCCESS, NOT_MODIFIED, HTTP_ERROR, TIMEOUT, PARSE_ERROR, EMPTY
    duration_ms: int
    articles_count: int
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    error_message: Optional[str] = None
    articles: List[Article] = None

    def __post_init__(self):
        if self.articles is None:
            self.articles = []


class FeedCollector:
    """Robust RSS/Atom collector with conditional headers and fault tolerance."""

    def __init__(
        self,
        sources: List[SourceConfig],
        tz: ZoneInfo,
        user_agent: str = USER_AGENT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.sources = sources
        self.tz = tz
        self.user_agent = user_agent
        self.session = session or requests.Session()

    def fetch_source(
        self,
        source: SourceConfig,
        cached_etag: Optional[str] = None,
        cached_last_modified: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> FetchResult:
        """Fetch and parse a single feed with retries and conditional request support."""
        start_time = time.perf_counter()
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        }
        if cached_etag:
            headers["If-None-Match"] = cached_etag
        if cached_last_modified:
            headers["If-Modified-Since"] = cached_last_modified

        timeout = source.timeout_seconds or DEFAULT_TIMEOUT
        attempt = 0
        response = None
        last_error = None

        while attempt <= MAX_RETRIES:
            attempt += 1
            try:
                # Stream response to enforce MAX_RESPONSE_BYTES
                response = self.session.get(
                    source.url,
                    headers=headers,
                    timeout=timeout,
                    stream=True,
                    allow_redirects=True,
                )

                # Check for HTTP 429 Rate Limit
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_time = min(10.0, float(retry_after)) if retry_after and retry_after.isdigit() else 2.0 * attempt
                    logger.warning(f"Rate limited (429) on {source.id}. Backing off {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                    continue

                # 304 Not Modified
                if response.status_code == 304:
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    return FetchResult(
                        source_id=source.id,
                        status_code=304,
                        status="NOT_MODIFIED",
                        duration_ms=duration_ms,
                        articles_count=0,
                        etag=cached_etag,
                        last_modified=cached_last_modified,
                    )

                if response.status_code >= 500:
                    # Transient server error, retry with backoff
                    sleep_time = 1.0 * attempt
                    logger.warning(f"HTTP {response.status_code} for {source.id}. Retry {attempt}/{MAX_RETRIES} in {sleep_time}s")
                    time.sleep(sleep_time)
                    continue

                break  # Successful response or client error (4xx other than 429)

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = str(e)
                if attempt <= MAX_RETRIES:
                    time.sleep(1.0 * attempt)
                    continue
            except Exception as e:
                last_error = str(e)
                break

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Handle failure cases
        if response is None:
            err_str = str(last_error).lower()
            logger.error(f"Failed to fetch {source.id} ({source.url}): {last_error}")
            return FetchResult(
                source_id=source.id,
                status_code=None,
                status="TIMEOUT" if "timeout" in err_str or "timed out" in err_str else "HTTP_ERROR",
                duration_ms=duration_ms,
                articles_count=0,
                error_message=last_error or "Network failure without response",
            )

        if not response.ok:
            logger.error(f"HTTP error {response.status_code} fetching {source.id} from {source.url}")
            return FetchResult(
                source_id=source.id,
                status_code=response.status_code,
                status="HTTP_ERROR",
                duration_ms=duration_ms,
                articles_count=0,
                error_message=f"HTTP {response.status_code}: {response.reason}",
            )

        # Enforce max content size
        content_bytes = bytearray()
        oversized = False
        try:
            for chunk in response.iter_content(chunk_size=65536):
                content_bytes.extend(chunk)
                if len(content_bytes) > MAX_RESPONSE_BYTES:
                    logger.warning(f"Source {source.id} exceeded max size limit of {MAX_RESPONSE_BYTES} bytes. Aborting parse.")
                    oversized = True
                    break
        except Exception as e:
            logger.error(f"Error reading body chunks from {source.id}: {e}")
            return FetchResult(
                source_id=source.id,
                status_code=response.status_code,
                status="HTTP_ERROR",
                duration_ms=duration_ms,
                articles_count=0,
                error_message=f"Stream read failure: {e}",
            )

        if oversized:
            return FetchResult(
                source_id=source.id,
                status_code=response.status_code,
                status="OVERSIZED",
                duration_ms=duration_ms,
                articles_count=0,
                error_message=f"Feed exceeded max response size of {MAX_RESPONSE_BYTES} bytes",
            )

        # Extract ETag & Last-Modified
        new_etag = response.headers.get("ETag")
        new_last_modified = response.headers.get("Last-Modified")

        # Parse with feedparser
        try:
            parsed = feedparser.parse(bytes(content_bytes))
        except Exception as e:
            logger.error(f"feedparser failed on {source.id}: {e}")
            return FetchResult(
                source_id=source.id,
                status_code=response.status_code,
                status="PARSE_ERROR",
                duration_ms=duration_ms,
                articles_count=0,
                error_message=f"Feed parse error: {e}",
            )

        if parsed.bozo and not parsed.entries:
            # feedparser raised an unrecoverable exception
            bozo_msg = str(parsed.bozo_exception) if hasattr(parsed, "bozo_exception") else "Malformed XML"
            logger.warning(f"Malformed feed for {source.id}: {bozo_msg}")
            return FetchResult(
                source_id=source.id,
                status_code=response.status_code,
                status="PARSE_ERROR",
                duration_ms=duration_ms,
                articles_count=0,
                error_message=bozo_msg,
            )

        articles: List[Article] = []
        entries = parsed.entries[: source.max_items]
        for entry in entries:
            try:
                article = normalize_feed_entry(entry, source, self.tz, now=now)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.debug(f"Failed to normalize entry from {source.id}: {e}")

        status = "SUCCESS" if articles else "EMPTY"
        return FetchResult(
            source_id=source.id,
            status_code=response.status_code,
            status=status,
            duration_ms=duration_ms,
            articles_count=len(articles),
            etag=new_etag,
            last_modified=new_last_modified,
            articles=articles,
        )

    def fetch_all(
        self,
        cached_metadata: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
        now: Optional[datetime] = None,
    ) -> List[FetchResult]:
        """Fetch all enabled feeds sequentially with slight pacing to prevent rate limits."""
        results: List[FetchResult] = []
        metadata = cached_metadata or {}

        for source in self.sources:
            if not source.enabled:
                continue

            cache_info = metadata.get(source.id, {})
            cached_etag = cache_info.get("etag")
            cached_lm = cache_info.get("last_modified")

            result = self.fetch_source(
                source,
                cached_etag=cached_etag,
                cached_last_modified=cached_lm,
                now=now,
            )
            results.append(result)

            # Gentle pacing
            time.sleep(0.15)

        return results
