"""Unit tests for workflow coordinator, timezone logic, and scheduling."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest

from daily_tech_brief.config import Settings
from daily_tech_brief.models import Article, DeliveryResult, DigestRun
from daily_tech_brief.scheduler import WorkflowCoordinator


def test_timezone_conversion_and_metadata(sample_settings: Settings, ist_tz: ZoneInfo):
    coordinator = WorkflowCoordinator(sample_settings)
    run_id, digest_date, start, end, now = coordinator.get_run_metadata(custom_date="2026-10-25")

    assert run_id == "digest_2026-10-25"
    assert digest_date == "2026-10-25"
    assert now.tzinfo.key == "Asia/Kolkata"
    # Coverage window default is 24 hours
    assert (end - start).total_seconds() == 24 * 3600


def test_utc_to_ist_near_midnight(sample_settings: Settings, ist_tz: ZoneInfo):
    """Test date determination when UTC is night of previous day but IST is next morning."""
    # 2026-10-24 23:00:00 UTC corresponds to 2026-10-25 04:30:00 IST
    utc_dt = datetime(2026, 10, 24, 23, 0, 0, tzinfo=timezone.utc)
    ist_dt = utc_dt.astimezone(ist_tz)

    assert ist_dt.day == 25
    assert ist_dt.strftime("%Y-%m-%d") == "2026-10-25"


def test_duplicate_run_prevention(sample_settings: Settings, ist_tz: ZoneInfo):
    coordinator = WorkflowCoordinator(sample_settings)
    now = datetime.now(ist_tz)
    today_str = now.strftime("%Y-%m-%d")

    # Simulate completed run
    run = DigestRun(
        run_id=f"digest_{today_str}",
        digest_date=today_str,
        coverage_start=now - timedelta(hours=24),
        coverage_end=now,
        status="SUCCESS",
        story_count=5,
        created_at=now,
    )
    coordinator.storage.create_digest_run(run, [])

    # Calling execute_digest should detect existing run and not deliver again
    result = coordinator.execute_digest(dry_run=False, force=False)
    assert result["status"] == "ALREADY_COMPLETED"
    assert "already successfully delivered" in result["message"]


def test_dry_run_executes_without_delivery(sample_settings: Settings, sample_article: Article):
    coordinator = WorkflowCoordinator(sample_settings)

    with patch.object(coordinator, "collect_and_process_articles") as mock_collect, \
         patch.object(coordinator.delivery, "deliver_all") as mock_deliver:

        mock_collect.return_value = ([sample_article], [], 1, 1)

        result = coordinator.execute_digest(dry_run=True)
        assert result["status"] == "DRY_RUN_COMPLETE"
        assert result["stories_count"] == 1
        mock_deliver.assert_not_called()
