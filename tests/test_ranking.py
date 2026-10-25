"""Unit tests for multi-factor ranking, explainability, and diversity selection."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from daily_tech_brief.config import RankingWeights
from daily_tech_brief.models import Article, OpportunityMetadata
from daily_tech_brief.ranking import ArticleRanker


@pytest.fixture
def ranker() -> ArticleRanker:
    weights = RankingWeights(
        relevance=0.35,
        freshness=0.25,
        importance=0.20,
        credibility=0.15,
        novelty=0.05,
    )
    return ArticleRanker(weights=weights, max_per_source=2, target_stories=5, min_stories=3)


def test_compute_freshness_score(ranker: ArticleRanker, ist_tz: ZoneInfo):
    now = datetime(2026, 10, 25, 12, 0, tzinfo=ist_tz)

    # 2 hours old
    fresh_2h = ranker.compute_freshness_score(now - timedelta(hours=2), now)
    assert 90.0 <= fresh_2h <= 100.0

    # 12 hours old
    fresh_12h = ranker.compute_freshness_score(now - timedelta(hours=12), now)
    assert 70.0 <= fresh_12h <= 89.0

    # 36 hours old
    fresh_36h = ranker.compute_freshness_score(now - timedelta(hours=36), now)
    assert 40.0 <= fresh_36h <= 69.0

    # 72 hours old
    fresh_72h = ranker.compute_freshness_score(now - timedelta(hours=72), now)
    assert fresh_72h < 40.0

    # Missing date
    fresh_none = ranker.compute_freshness_score(None, now)
    assert fresh_none == 45.0


def test_compute_importance_score(ranker: ArticleRanker):
    # High impact CVE
    art_cve = Article(
        id="1",
        canonical_url="https://example.com/1",
        original_url="https://example.com/1",
        title="Zero-Day Remote Code Execution CVE-2026-9999 Actively Exploited",
        description="Critical advisory.",
        source_id="cisa",
        source_name="CISA",
    )
    imp_cve = ranker.compute_importance_score(art_cve)
    assert imp_cve >= 75.0

    # Clickbait penalty
    art_clickbait = Article(
        id="2",
        canonical_url="https://example.com/2",
        original_url="https://example.com/2",
        title="You Won't Believe This Shocking New Tool",
        description="Game-changer will destroy everything.",
        source_id="blog",
        source_name="Blog",
    )
    imp_clickbait = ranker.compute_importance_score(art_clickbait)
    assert imp_clickbait <= 40.0


def test_ranking_explanation_populated(ranker: ArticleRanker, ist_tz: ZoneInfo):
    now = datetime.now(ist_tz)
    art = Article(
        id="3",
        canonical_url="https://example.com/3",
        original_url="https://example.com/3",
        title="Rust 1.95 Released with Major Compile-Time Speedups",
        description="The Rust foundation announces major release.",
        source_id="rust",
        source_name="Rust Blog",
        published_at=now - timedelta(hours=3),
        first_seen_at=now,
        relevance_score=75.0,
        source_credibility_score=90.0,
    )
    ranked = ranker.score_article(art, now)
    assert ranked.combined_score > 60.0
    assert "Score:" in ranked.ranking_explanation
    assert "Rel(35%):" in ranked.ranking_explanation
    assert "Fresh(25%):" in ranked.ranking_explanation


def test_source_diversity_enforcement(ranker: ArticleRanker, ist_tz: ZoneInfo):
    now = datetime.now(ist_tz)
    # Create 5 articles from the SAME source and 3 from other sources
    articles = []
    for i in range(5):
        articles.append(
            Article(
                id=f"same_{i}",
                canonical_url=f"https://example.com/same_{i}",
                original_url=f"https://example.com/same_{i}",
                title=f"Article {i} from Same Source",
                description="General news story.",
                source_id="monopoly_source",
                source_name="Monopoly Source",
                categories=["software_dev"],
                published_at=now - timedelta(hours=2),
                first_seen_at=now,
                relevance_score=80.0,
                source_credibility_score=90.0,
            )
        )

    categories_list = ["ai_and_llms", "cybersecurity", "research_and_opensource"]
    for i in range(3):
        articles.append(
            Article(
                id=f"other_{i}",
                canonical_url=f"https://example.com/other_{i}",
                original_url=f"https://example.com/other_{i}",
                title=f"Article {i} from Other Source",
                description="Other valuable story.",
                source_id=f"source_{i}",
                source_name=f"Source {i}",
                categories=[categories_list[i]],
                published_at=now - timedelta(hours=3),
                first_seen_at=now,
                relevance_score=75.0,
                source_credibility_score=85.0,
            )
        )

    selected, used_fallback = ranker.select_stories(
        articles, primary_lookback_hours=24, fallback_lookback_hours=48, now=now
    )

    # Monopoly source should have at most max_per_source (2)
    monopoly_count = sum(1 for a in selected if a.source_id == "monopoly_source")
    assert monopoly_count <= 2
    assert len(selected) == 5


def test_fallback_window_on_low_news_days(ranker: ArticleRanker, ist_tz: ZoneInfo):
    now = datetime.now(ist_tz)
    # Only 1 story in the last 24h, but 4 stories in 24-48h
    articles = [
        Article(
            id="fresh_1",
            canonical_url="https://example.com/fresh_1",
            original_url="https://example.com/fresh_1",
            title="Fresh Story Within 24h",
            description="Recent news.",
            source_id="src1",
            source_name="Source 1",
            published_at=now - timedelta(hours=5),
            first_seen_at=now,
            relevance_score=70.0,
        )
    ]
    for i in range(4):
        articles.append(
            Article(
                id=f"older_{i}",
                canonical_url=f"https://example.com/older_{i}",
                original_url=f"https://example.com/older_{i}",
                title=f"Older Story {i} from Yesterday",
                description="Solid news from 30 hours ago.",
                source_id=f"src_{i+2}",
                source_name=f"Source {i+2}",
                published_at=now - timedelta(hours=30),
                first_seen_at=now,
                relevance_score=70.0,
            )
        )

    selected, used_fallback = ranker.select_stories(
        articles, primary_lookback_hours=24, fallback_lookback_hours=48, now=now
    )

    # Since 1 < min_stories (3), fallback window should be activated
    assert used_fallback is True
    assert len(selected) >= 3
