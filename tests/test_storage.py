"""Unit tests for SQLite persistent state, transactions, and delivery tracking."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from daily_tech_brief.models import Article, DigestRun
from daily_tech_brief.storage import Storage


def test_storage_init_creates_tables(test_storage: Storage):
    with test_storage._get_connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t["name"] for t in tables]

    assert "articles" in table_names
    assert "feed_runs" in table_names
    assert "digest_runs" in table_names
    assert "digest_articles" in table_names
    assert "deliveries" in table_names
    assert "summary_cache" in table_names


def test_record_feed_run_and_metadata(test_storage: Storage):
    now = datetime.now(timezone.utc)
    test_storage.record_feed_run(
        source_id="arxiv_ai",
        status_code=200,
        status="SUCCESS",
        duration_ms=450,
        articles_count=15,
        etag='"etag123"',
        last_modified="Sun, 25 Oct 2026 09:00:00 GMT",
        now=now,
    )

    meta = test_storage.get_feed_cache_metadata("arxiv_ai")
    assert meta["etag"] == '"etag123"'
    assert meta["last_modified"] == "Sun, 25 Oct 2026 09:00:00 GMT"


def test_save_and_retrieve_articles(test_storage: Storage, sample_article: Article):
    test_storage.save_articles([sample_article])

    with test_storage._get_connection() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (sample_article.id,)).fetchone()
        assert row is not None
        assert row["canonical_url"] == sample_article.canonical_url
        assert row["title"] == sample_article.title


def test_digest_run_and_delivery_tracking(test_storage: Storage, sample_article: Article, ist_tz: ZoneInfo):
    test_storage.save_articles([sample_article])
    now = datetime.now(ist_tz)
    run_id = "digest_2026-10-25"

    digest_run = DigestRun(
        run_id=run_id,
        digest_date="2026-10-25",
        coverage_start=now - timedelta(hours=24),
        coverage_end=now,
        status="IN_PROGRESS",
        story_count=1,
        created_at=now,
    )
    test_storage.create_digest_run(digest_run, [sample_article])

    # Record partial delivery: Telegram SUCCESS, Email FAILED
    test_storage.record_delivery_attempt(
        digest_id=run_id, channel="telegram", success=True, message_id="msg_999"
    )
    test_storage.record_delivery_attempt(
        digest_id=run_id, channel="email", success=False, error_message="SMTP Authentication failed"
    )

    statuses = test_storage.get_delivery_statuses(run_id)
    assert statuses["telegram"].success is True
    assert statuses["telegram"].message_id == "msg_999"
    assert statuses["email"].success is False
    assert "Authentication" in statuses["email"].error_message

    # Test safe retry of email channel
    test_storage.record_delivery_attempt(
        digest_id=run_id, channel="email", success=True, message_id="em_success"
    )
    updated = test_storage.get_delivery_statuses(run_id)
    assert updated["email"].success is True
    assert updated["email"].status == "SUCCESS"


def test_delivered_urls_retrieval(test_storage: Storage, sample_article: Article):
    sample_article.is_delivered = True
    test_storage.save_articles([sample_article])

    urls, titles = test_storage.get_delivered_urls_and_titles(retention_days=90)
    assert sample_article.canonical_url in urls
    assert "deepseek releases deepseekr1" in list(titles)[0]


def test_summary_cache(test_storage: Storage):
    content_hash = "abc123hash"
    assert test_storage.get_cached_summary(content_hash) is None

    test_storage.save_cached_summary(
        content_hash=content_hash,
        summary="Concise summary",
        why_it_matters="Important technical reason",
        technical_context="Built with PyTorch",
        method="llm",
    )

    cached = test_storage.get_cached_summary(content_hash)
    assert cached is not None
    assert cached["summary"] == "Concise summary"
    assert cached["why_it_matters"] == "Important technical reason"
    assert cached["method"] == "llm"


def test_transaction_rollback(test_storage: Storage):
    with pytest.raises(sqlite3.IntegrityError):
        with test_storage._get_connection() as conn:
            # Insert valid row
            conn.execute(
                "INSERT INTO digest_runs (run_id, digest_date, coverage_start, coverage_end, status, created_at, last_updated_at) VALUES ('r1', '2026-10-25', 't1', 't2', 'PENDING', 't3', 't4')"
            )
            # Duplicate primary key to trigger IntegrityError
            conn.execute(
                "INSERT INTO digest_runs (run_id, digest_date, coverage_start, coverage_end, status, created_at, last_updated_at) VALUES ('r1', '2026-10-25', 't1', 't2', 'PENDING', 't3', 't4')"
            )

    # Verify rollback occurred
    with test_storage._get_connection() as conn:
        row = conn.execute("SELECT * FROM digest_runs WHERE run_id = 'r1'").fetchone()
        assert row is None
