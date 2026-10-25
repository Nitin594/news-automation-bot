"""Unit tests for Plain-Text, Telegram HTML, and Email HTML digest rendering."""

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from daily_tech_brief.digest import DigestRenderer, format_timestamp
from daily_tech_brief.models import Article, OpportunityMetadata


@pytest.fixture
def digest_renderer(ist_tz: ZoneInfo) -> DigestRenderer:
    return DigestRenderer(ist_tz)


def test_format_timestamp(ist_tz: ZoneInfo):
    dt = datetime(2026, 10, 25, 3, 30, tzinfo=ZoneInfo("UTC"))
    formatted = format_timestamp(dt, ist_tz)
    assert "25 Oct 2026" in formatted
    assert "09:00 AM" in formatted

    assert format_timestamp(None, ist_tz) == "Unknown date"


def test_render_plain_text(digest_renderer: DigestRenderer, sample_article: Article, ist_tz: ZoneInfo):
    now = datetime(2026, 10, 25, 9, 0, tzinfo=ist_tz)
    plain = digest_renderer.render_plain_text([sample_article], "Sunday, 25 October 2026", now)

    assert "DAILY TECH BRIEF" in plain
    assert "Sunday, 25 October 2026" in plain
    assert "Coverage window: past 24 hours" in plain
    assert "DeepSeek Releases DeepSeek-R1" in plain
    assert "SOURCE NOTES:" in plain


def test_render_telegram_html(digest_renderer: DigestRenderer, sample_article: Article, ist_tz: ZoneInfo):
    sample_article.title = "Test <Unescaped & Dangerous> Title"
    now = datetime(2026, 10, 25, 9, 0, tzinfo=ist_tz)
    chunks = digest_renderer.render_telegram_html([sample_article], "Sunday, 25 October 2026", now)

    assert len(chunks) >= 1
    content = chunks[0]
    assert "⚡ <b>DAILY TECH BRIEF</b>" in content
    # Ensure HTML entities escaped safely
    assert "&lt;Unescaped &amp; Dangerous&gt;" in content
    assert "<Unescaped" not in content
    assert f'<a href="{sample_article.original_url}">' in content


def test_render_telegram_splitting(digest_renderer: DigestRenderer, ist_tz: ZoneInfo):
    now = datetime(2026, 10, 25, 9, 0, tzinfo=ist_tz)
    # Create 15 long articles to force chunk splitting (> 4000 chars)
    articles = []
    for i in range(15):
        articles.append(
            Article(
                id=f"art_{i}",
                canonical_url=f"https://example.com/article-{i}",
                original_url=f"https://example.com/article-{i}",
                title=f"Very Long Tech News Article Title Number {i} Detailing Developments",
                description="Long detailed description explaining the architecture and significance of the model release." * 5,
                source_id="src1",
                source_name="Source Publisher",
                summary="A concise summary of two or three sentences covering the major breakthrough." * 2,
                why_it_matters="One sentence explaining the strategic impact of this event.",
                first_seen_at=now,
            )
        )

    chunks = digest_renderer.render_telegram_html(articles, "Sunday, 25 October 2026", now)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 4096


def test_render_email_html(digest_renderer: DigestRenderer, sample_article: Article, ist_tz: ZoneInfo):
    now = datetime(2026, 10, 25, 9, 0, tzinfo=ist_tz)
    html_content = digest_renderer.render_email_html([sample_article], "Sunday, 25 October 2026", now)

    assert "<!DOCTYPE html>" in html_content
    assert "Daily Personal Tech Brief" in html_content
    assert sample_article.title in html_content
    assert "Read Original Source &rarr;" in html_content
    assert "Source Notes:" in html_content


def test_render_empty_articles(digest_renderer: DigestRenderer, ist_tz: ZoneInfo):
    now = datetime(2026, 10, 25, 9, 0, tzinfo=ist_tz)
    plain = digest_renderer.render_plain_text([], "Sunday, 25 October 2026", now)
    assert "No major qualifying news items" in plain

    tg = digest_renderer.render_telegram_html([], "Sunday, 25 October 2026", now)
    assert "No qualifying stories found" in tg[0]
