"""Unit tests for HTML sanitization, URL canonicalization, and date parsing."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest

from daily_tech_brief.models import SourceConfig
from daily_tech_brief.normalizer import (
    canonicalize_url,
    clean_text,
    extract_opportunity_metadata,
    generate_article_id,
    generate_content_hash,
    normalize_feed_entry,
    parse_timestamp,
)


def test_clean_text_html_stripping_and_entities():
    raw = "<p>OpenAI &amp; Anthropic announced <b>new models</b> &quot;instantly&quot;!</p>"
    cleaned = clean_text(raw)
    assert cleaned == 'OpenAI & Anthropic announced new models "instantly"!'


def test_clean_text_empty_and_whitespace():
    assert clean_text("") == ""
    assert clean_text(None) == ""
    assert clean_text("   Lots   of   \n\t  spaces  ") == "Lots of spaces"


def test_clean_text_unicode_and_emojis():
    raw = "🚀 Breakthrough in LLMs: René & Müller announce v2.0"
    cleaned = clean_text(raw)
    assert "🚀" in cleaned
    assert "René & Müller" in cleaned


def test_canonicalize_url_strips_tracking():
    raw = "https://example.com/blog/ai-post/?utm_source=twitter&utm_medium=social&utm_campaign=launch&article_id=42&ref=newsletter"
    canonical = canonicalize_url(raw)
    # Preserves functional parameter article_id, strips tracking params
    assert "article_id=42" in canonical
    assert "utm_source" not in canonical
    assert "utm_campaign" not in canonical
    assert "ref=" not in canonical


def test_canonicalize_url_trailing_slash_and_case():
    url1 = "HTTPS://Example.COM/Path/To/Story/"
    canonical = canonicalize_url(url1)
    assert canonical == "https://example.com/Path/To/Story"


def test_generate_article_id_deterministic():
    url = "https://example.com/post/1"
    id1 = generate_article_id(url)
    id2 = generate_article_id(url)
    assert id1 == id2
    assert len(id1) == 16


def test_generate_content_hash():
    h1 = generate_content_hash("Title", "Description")
    h2 = generate_content_hash("Title", "Description")
    h3 = generate_content_hash("Different Title", "Description")
    assert h1 == h2
    assert h1 != h3


def test_parse_timestamp_valid_rfc822(ist_tz: ZoneInfo):
    entry = {"published": "Sun, 25 Oct 2026 09:00:00 +0000"}
    dt = parse_timestamp(entry, ist_tz)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 25
    # IST is UTC+05:30 -> 9:00 UTC is 14:30 IST
    assert dt.hour == 14
    assert dt.minute == 30


def test_parse_timestamp_valid_iso(ist_tz: ZoneInfo):
    entry = {"published": "2026-10-25T03:30:00Z"}
    dt = parse_timestamp(entry, ist_tz)
    assert dt is not None
    # 03:30 UTC is 09:00 IST
    assert dt.hour == 9
    assert dt.minute == 30


def test_parse_timestamp_missing_or_malformed(ist_tz: ZoneInfo):
    assert parse_timestamp({}, ist_tz) is None
    assert parse_timestamp({"published": "not-a-real-date"}, ist_tz) is None


def test_extract_opportunity_metadata():
    title = "Summer 2026 Software Engineer Internship - Applications Open"
    desc = "Apply by November 15, 2026 for our remote student internship program."
    opp = extract_opportunity_metadata(title, desc, "https://jobs.example.com", is_opp_source=False)
    assert opp is not None
    assert opp.opportunity_type == "Internship"
    assert opp.location == "Remote"
    assert "November 15, 2026" in opp.deadline
    assert opp.verification_status == "unverified"


def test_normalize_feed_entry_missing_url(sample_source: SourceConfig, ist_tz: ZoneInfo):
    entry = {"title": "A story with no link"}
    art = normalize_feed_entry(entry, sample_source, ist_tz)
    assert art is None


def test_normalize_feed_entry_missing_title(sample_source: SourceConfig, ist_tz: ZoneInfo):
    entry = {"link": "https://example.com/no-title"}
    art = normalize_feed_entry(entry, sample_source, ist_tz)
    assert art is None


def test_normalize_feed_entry_success(sample_source: SourceConfig, ist_tz: ZoneInfo):
    entry = {
        "title": "Major &lt;b&gt;Python 3.14&lt;/b&gt; Feature Released",
        "link": "https://python.org/news?utm_source=rss",
        "summary": "<p>A new JIT compiler is now enabled by default.</p>",
        "author": "Guido van Rossum",
        "published": "2026-10-25T03:30:00Z",
    }
    art = normalize_feed_entry(entry, sample_source, ist_tz)
    assert art is not None
    assert art.title == "Major Python 3.14 Feature Released"
    assert art.canonical_url == "https://python.org/news"
    assert "JIT compiler" in art.description
    assert art.author == "Guido van Rossum"
    assert art.source_id == sample_source.id
    assert art.source_credibility_score == sample_source.reliability_weight
