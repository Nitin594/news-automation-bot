"""Pytest fixtures for Daily Tech Brief unit test suite."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

# Ensure src/ is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from daily_tech_brief.config import Settings
from daily_tech_brief.models import Article, OpportunityMetadata, SourceConfig
from daily_tech_brief.storage import Storage


@pytest.fixture
def ist_tz() -> ZoneInfo:
    return ZoneInfo("Asia/Kolkata")


@pytest.fixture
def sample_settings(tmp_path: Path) -> Settings:
    db_path = str(tmp_path / "test_brief.db")
    return Settings(
        telegram_bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        telegram_chat_id="987654321",
        email_host="smtp.test.com",
        email_port=587,
        email_username="user@test.com",
        email_password="secretpassword",
        email_sender="user@test.com",
        email_recipient="dest@test.com",
        timezone_name="Asia/Kolkata",
        database_path=db_path,
        digest_limit=5,
        lookback_hours=24,
        fallback_lookback_hours=48,
    )


@pytest.fixture
def test_storage(tmp_path: Path) -> Storage:
    db_file = tmp_path / "test_storage.db"
    return Storage(str(db_file))


@pytest.fixture
def sample_source() -> SourceConfig:
    return SourceConfig(
        id="test_feed",
        name="Test Feed Publisher",
        url="https://example.com/feed.xml",
        categories=["ai_and_llms", "software_dev"],
        reliability_weight=85.0,
    )


@pytest.fixture
def sample_article(ist_tz: ZoneInfo) -> Article:
    now = datetime.now(ist_tz)
    return Article(
        id="art123",
        canonical_url="https://example.com/articles/deepseek-r1-release",
        original_url="https://example.com/articles/deepseek-r1-release?utm_source=rss",
        title="DeepSeek Releases DeepSeek-R1 Open Reasoning Model",
        description="DeepSeek has announced the open weights release of DeepSeek-R1 with competitive reasoning benchmarks.",
        source_id="test_feed",
        source_name="Test Feed Publisher",
        author="Alice Smith",
        published_at=now,
        first_seen_at=now,
        categories=["ai_and_llms"],
        matched_keywords=["deepseek", "reasoning model", "open weights"],
        source_credibility_score=85.0,
        content_hash="hash123",
    )
