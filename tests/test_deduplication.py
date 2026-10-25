"""Unit tests for multi-level deduplication, token similarity, and cross-day suppression."""

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from daily_tech_brief.deduplication import (
    ArticleDeduplicator,
    get_title_tokens,
    jaccard_similarity,
    normalize_title,
)
from daily_tech_brief.models import Article


def test_normalize_title():
    assert normalize_title("DeepSeek-R1: Released!") == "deepseekr1 released"
    assert normalize_title("   Lots   of   PUNCTUATION?!...  ") == "lots of punctuation"


def test_jaccard_similarity():
    s1 = {"deepseek", "releases", "model"}
    s2 = {"deepseek", "releases", "model"}
    assert jaccard_similarity(s1, s2) == 1.0

    s3 = {"deepseek", "releases", "paper"}
    # intersection: 2 ('deepseek', 'releases'), union: 4
    assert jaccard_similarity(s1, s3) == 0.5

    assert jaccard_similarity(set(), {"test"}) == 0.0


def test_deduplicate_exact_canonical_url(ist_tz: ZoneInfo):
    now = datetime.now(ist_tz)
    art1 = Article(
        id="1",
        canonical_url="https://example.com/story-1",
        original_url="https://example.com/story-1?utm_source=rss",
        title="First Article Title",
        description="Desc",
        source_id="src1",
        source_name="Src 1",
        first_seen_at=now,
    )
    art2 = Article(
        id="2",
        canonical_url="https://example.com/story-1",
        original_url="https://example.com/story-1?utm_source=twitter",
        title="Duplicate Canonical URL Story",
        description="Desc",
        source_id="src2",
        source_name="Src 2",
        first_seen_at=now,
    )
    dedup = ArticleDeduplicator()
    unique = dedup.deduplicate_batch([art1, art2])
    assert len(unique) == 1
    assert unique[0].canonical_url == "https://example.com/story-1"


def test_deduplicate_near_duplicate_titles_with_corroboration(ist_tz: ZoneInfo):
    now = datetime.now(ist_tz)
    art1 = Article(
        id="1",
        canonical_url="https://news1.com/gemini-2",
        original_url="https://news1.com/gemini-2",
        title="Google announces Gemini 2.0 with advanced multimodality",
        description="Google has unveiled Gemini 2.0.",
        source_id="news1",
        source_name="News 1",
        source_credibility_score=80.0,
        first_seen_at=now,
    )
    art2 = Article(
        id="2",
        canonical_url="https://techblog.com/google-gemini-2",
        original_url="https://techblog.com/google-gemini-2",
        title="Google announced Gemini 2.0 with advanced multimodality features",
        description="A major AI release from Google.",
        source_id="techblog",
        source_name="Tech Blog",
        source_credibility_score=85.0,
        first_seen_at=now,
    )
    dedup = ArticleDeduplicator(similarity_threshold=0.80)
    unique = dedup.deduplicate_batch([art1, art2])
    assert len(unique) == 1
    # Check that corroborating source was attached
    assert len(unique[0].corroborating_sources) == 1
    assert unique[0].corroborating_sources[0]["source_name"] == "Tech Blog"


def test_distinct_stories_not_merged(ist_tz: ZoneInfo):
    now = datetime.now(ist_tz)
    art1 = Article(
        id="1",
        canonical_url="https://example.com/python-312",
        original_url="https://example.com/python-312",
        title="Release notes for Python 3.12",
        description="Features in Python 3.12",
        source_id="src1",
        source_name="Src 1",
        first_seen_at=now,
    )
    art2 = Article(
        id="2",
        canonical_url="https://example.com/python-313",
        original_url="https://example.com/python-313",
        title="Release notes for Python 3.13",
        description="Features in Python 3.13",
        source_id="src1",
        source_name="Src 1",
        first_seen_at=now,
    )
    dedup = ArticleDeduplicator()
    unique = dedup.deduplicate_batch([art1, art2])
    assert len(unique) == 2


def test_filter_previously_delivered(ist_tz: ZoneInfo):
    now = datetime.now(ist_tz)
    art1 = Article(
        id="1",
        canonical_url="https://example.com/already-delivered",
        original_url="https://example.com/already-delivered",
        title="Yesterday Headline Delivered",
        description="Desc",
        source_id="src1",
        source_name="Src 1",
        first_seen_at=now,
    )
    art2 = Article(
        id="2",
        canonical_url="https://example.com/brand-new",
        original_url="https://example.com/brand-new",
        title="Brand New Headline For Today",
        description="Desc",
        source_id="src1",
        source_name="Src 1",
        first_seen_at=now,
    )
    delivered_urls = {"https://example.com/already-delivered"}
    delivered_titles = {"yesterday headline delivered"}

    dedup = ArticleDeduplicator()
    fresh = dedup.filter_previously_delivered([art1, art2], delivered_urls, delivered_titles)

    assert len(fresh) == 1
    assert fresh[0].id == "2"
