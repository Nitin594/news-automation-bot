"""Unit tests for categorizer and topic relevance scoring."""

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from daily_tech_brief.categorizer import ArticleCategorizer
from daily_tech_brief.models import Article, OpportunityMetadata


@pytest.fixture
def categorizer() -> ArticleCategorizer:
    categories = {
        "ai_and_llms": {
            "name": "AI & LLMs",
            "weight": 1.2,
            "keywords": ["llm", "deepseek", "transformer", "claude"],
        },
        "software_dev": {
            "name": "Software Development",
            "weight": 1.1,
            "keywords": ["python", "rust", "database", "kubernetes"],
        },
        "cybersecurity": {
            "name": "Cybersecurity Watch",
            "weight": 1.15,
            "keywords": ["cve", "vulnerability", "ransomware", "cisa"],
        },
        "internships_and_hackathons": {
            "name": "Internships & Opportunities",
            "weight": 1.25,
            "keywords": ["internship", "hackathon", "student program"],
        },
    }
    excluded = ["crypto pump", "giveaway", "discount code"]
    return ArticleCategorizer(categories, excluded)


def test_categorize_single_category(categorizer: ArticleCategorizer, ist_tz: ZoneInfo):
    art = Article(
        id="1",
        canonical_url="https://example.com/1",
        original_url="https://example.com/1",
        title="DeepSeek releases new open weights reasoning model",
        description="A technical paper detailing the novel transformer architecture.",
        source_id="src1",
        source_name="Source 1",
        first_seen_at=datetime.now(ist_tz),
    )
    res = categorizer.categorize(art)
    assert "ai_and_llms" in res.categories
    assert "deepseek" in res.matched_keywords
    assert "transformer" in res.matched_keywords
    assert res.relevance_score >= 60.0


def test_categorize_multi_category(categorizer: ArticleCategorizer, ist_tz: ZoneInfo):
    art = Article(
        id="2",
        canonical_url="https://example.com/2",
        original_url="https://example.com/2",
        title="Building LLM Pipelines in Python with Kubernetes",
        description="How to orchestrate distributed inference workloads.",
        source_id="src1",
        source_name="Source 1",
        first_seen_at=datetime.now(ist_tz),
    )
    res = categorizer.categorize(art)
    assert "ai_and_llms" in res.categories
    assert "software_dev" in res.categories
    assert "llm" in res.matched_keywords
    assert "python" in res.matched_keywords
    assert "kubernetes" in res.matched_keywords


def test_categorize_cybersecurity_alert(categorizer: ArticleCategorizer, ist_tz: ZoneInfo):
    art = Article(
        id="3",
        canonical_url="https://example.com/3",
        original_url="https://example.com/3",
        title="CISA Adds Critical CVE-2026-1122 Vulnerability to Catalog",
        description="Immediate patch advisory for remote code execution bug.",
        source_id="cisa",
        source_name="CISA",
        first_seen_at=datetime.now(ist_tz),
    )
    res = categorizer.categorize(art)
    assert "cybersecurity" in res.categories
    assert "cve" in res.matched_keywords
    assert "vulnerability" in res.matched_keywords


def test_categorize_excluded_topic(categorizer: ArticleCategorizer, ist_tz: ZoneInfo):
    art = Article(
        id="4",
        canonical_url="https://example.com/4",
        original_url="https://example.com/4",
        title="Huge Crypto Pump and Token Giveaway Announced",
        description="Claim your free coins now.",
        source_id="spam",
        source_name="Spam",
        first_seen_at=datetime.now(ist_tz),
    )
    res = categorizer.categorize(art)
    assert res.relevance_score == 0.0
    assert "excluded topic filter" in res.ranking_explanation


def test_categorize_opportunity(categorizer: ArticleCategorizer, ist_tz: ZoneInfo):
    art = Article(
        id="5",
        canonical_url="https://example.com/5",
        original_url="https://example.com/5",
        title="Google Summer of Code 2026 Student Applications Open",
        description="Mentorship program for open source development.",
        source_id="google",
        source_name="Google",
        is_opportunity=True,
        opportunity_data=OpportunityMetadata(
            organization="Google",
            opportunity_type="Mentorship",
            application_url="https://summerofcode.withgoogle.com",
        ),
        first_seen_at=datetime.now(ist_tz),
    )
    res = categorizer.categorize(art)
    assert "internships_and_hackathons" in res.categories
