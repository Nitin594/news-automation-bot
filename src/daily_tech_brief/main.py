"""Command-line interface entry point for Daily Tech Brief."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from daily_tech_brief.config import get_settings
from daily_tech_brief.scheduler import WorkflowCoordinator

logger = logging.getLogger("daily_tech_brief")

# Reconfigure stdout/stderr to UTF-8 on Windows consoles if supported
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def setup_logging(level_name: str = "INFO") -> None:
    """Configure structured logging."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_run(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Execute the complete digest workflow."""
    result = coordinator.execute_digest(
        dry_run=args.dry_run,
        custom_date=args.date,
        force=args.force,
    )
    if result.get("status") in ("SUCCESS", "DRY_RUN_COMPLETE", "ALREADY_COMPLETED"):
        return 0
    elif result.get("status") == "PARTIAL_FAILURE":
        return 1
    return 2


def cmd_collect(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Fetch feeds and display collection statistics without delivery."""
    print("Collecting feeds and computing statistics...")
    fresh, fetch_results, raw_count, dedup_count = coordinator.collect_and_process_articles()

    print("\n" + "=" * 50)
    print("FEED COLLECTION SUMMARY")
    print("=" * 50)
    for res in fetch_results:
        status_symbol = "[OK]" if res.status in ("SUCCESS", "NOT_MODIFIED") else "[FAIL]"
        print(f"{status_symbol:<6} {res.source_id:<22} | Status: {res.status:<12} | Items: {res.articles_count:<3} | {res.duration_ms}ms")
        if res.error_message:
            print(f"       Error: {res.error_message}")

    print("-" * 50)
    print(f"Total raw items fetched:       {raw_count}")
    print(f"Fresh items after deduplication: {dedup_count}")
    print("=" * 50 + "\n")
    return 0


def cmd_preview(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Generate and display the digest preview without sending it."""
    result = coordinator.execute_digest(dry_run=True, custom_date=args.date)
    return 0 if result.get("status") == "DRY_RUN_COMPLETE" else 1


def cmd_test_telegram(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Send test message to Telegram."""
    if not coordinator.delivery.telegram:
        print("ERROR: Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
        return 1

    print("Sending test message to Telegram...")
    res = coordinator.delivery.telegram.send_test_message()
    if res.success:
        print("✓ Telegram test message sent successfully!")
        return 0
    else:
        print(f"✗ Telegram test delivery failed: {res.error_message}")
        return 1


def cmd_test_email(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Send test email via SMTP."""
    if not coordinator.delivery.email:
        print("ERROR: Email SMTP is not configured. Set EMAIL_HOST, EMAIL_USERNAME, EMAIL_PASSWORD, and EMAIL_RECIPIENT in .env.")
        return 1

    print("Sending test email...")
    res = coordinator.delivery.email.send_test_message()
    if res.success:
        print("✓ Email test message sent successfully!")
        return 0
    else:
        print(f"✗ Email test delivery failed: {res.error_message}")
        return 1


def cmd_test_delivery(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Test both Telegram and Email delivery channels."""
    tg_code = cmd_test_telegram(coordinator, args)
    em_code = cmd_test_email(coordinator, args)
    return 0 if (tg_code == 0 and em_code == 0) else 1


def cmd_test_llm(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Test LLM summarization with the configured provider and API key."""
    settings = coordinator.settings
    if not settings.llm_api_key:
        print("ERROR: LLM_API_KEY is not set in .env.")
        print("Please set ENABLE_LLM_SUMMARIES=true and LLM_API_KEY=your_key in .env to test AI summarization.")
        return 1

    print(f"Testing {settings.llm_provider.upper()} summarization using model '{settings.llm_model}'...")
    from daily_tech_brief.models import Article
    from daily_tech_brief.summarizer import LLMSummarizer

    test_article = Article(
        id="test_ai_art",
        canonical_url="https://example.com/deepseek-r1",
        original_url="https://example.com/deepseek-r1",
        title="DeepSeek Releases DeepSeek-R1 Open Reasoning Model",
        description="DeepSeek has officially released the weights and technical report for DeepSeek-R1, demonstrating competitive mathematical and coding reasoning benchmarks compared to proprietary models, trained using reinforcement learning.",
        source_id="test",
        source_name="AI Research News",
        categories=["ai_and_llms"],
    )

    summarizer = LLMSummarizer(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )

    try:
        res = summarizer.summarize(test_article)
        print("\n" + "=" * 50)
        print("✓ AI Summarization Succeeded!")
        print("=" * 50)
        print(f"Summary:           {res.get('summary')}")
        print(f"Why it matters:    {res.get('why_it_matters')}")
        if res.get("technical_context"):
            print(f"Technical Context: {res.get('technical_context')}")
        print("=" * 50 + "\n")
        return 0
    except Exception as e:
        print(f"\n✗ AI Summarization failed: {e}")
        return 1


def cmd_sources(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """List configured feeds and their latest fetch status."""
    sources = coordinator.sources_registry.sources
    print(f"\nConfigured Sources ({len(sources)} total):")
    print("-" * 75)
    print(f"{'Source ID':<22} {'Reliability':<12} {'Enabled':<8} {'URL'}")
    print("-" * 75)
    for s in sources.values():
        enabled_str = "YES" if s.enabled else "NO"
        print(f"{s.id:<22} {s.reliability_weight:<12.1f} {enabled_str:<8} {s.url}")
    print("-" * 75 + "\n")
    return 0


def cmd_retry_failed(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Retry failed delivery channels without resending to successful ones."""
    res = coordinator.retry_failed_deliveries()
    return 0 if res.get("status") == "SUCCESS" else 1


def cmd_health(coordinator: WorkflowCoordinator, args: argparse.Namespace) -> int:
    """Validate system configuration, database access, and feeds without sending digest."""
    settings = coordinator.settings
    validation = settings.validate_all()

    print("\n" + "=" * 60)
    print(" DAILY TECH BRIEF - HEALTH CHECK")
    print("=" * 60)

    # 1. Database
    db_ok = len(validation["database"]) == 0
    print(f"[{'OK' if db_ok else 'FAIL'}] Database: {settings.database_path}")
    for err in validation["database"]:
        print(f"    ! {err}")

    # 2. Timezone
    tz = settings.get_timezone()
    now_in_tz = datetime.now(tz)
    print(f"[OK] Timezone: {tz} (Current local time: {now_in_tz.strftime('%Y-%m-%d %H:%M:%S %Z')})")

    # 3. Sources
    sources_count = len(coordinator.sources_registry.get_enabled_sources())
    print(f"[OK] Feeds Configured: {sources_count} active feeds ({settings.feeds_config_path})")

    # 4. Telegram
    tg_ok = len(validation["telegram"]) == 0
    print(f"[{'OK' if tg_ok else 'WARN'}] Telegram Config: {'Ready' if tg_ok else 'Incomplete'}")
    for err in validation["telegram"]:
        print(f"    - {err}")

    # 5. Email
    em_ok = len(validation["email"]) == 0
    print(f"[{'OK' if em_ok else 'WARN'}] Email SMTP Config: {'Ready' if em_ok else 'Incomplete'}")
    for err in validation["email"]:
        print(f"    - {err}")

    # 6. Optional LLM
    if settings.enable_llm_summaries:
        llm_ok = len(validation["llm"]) == 0
        print(f"[{'OK' if llm_ok else 'WARN'}] LLM Summaries: ENABLED ({settings.llm_provider}:{settings.llm_model})")
        for err in validation["llm"]:
            print(f"    - {err}")
    else:
        print("[OK] LLM Summaries: DISABLED (Operating in 100% Free Mode with Extractive Fallback)")

    print("=" * 60 + "\n")
    return 0 if (db_ok and sources_count > 0) else 1


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="daily-tech-brief",
        description="Autonomous Personal Tech News Aggregator, Ranker, and Multi-Channel Delivery System",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = subparsers.add_parser("run", help="Execute complete digest workflow")
    p_run.add_argument("--dry-run", action="store_true", help="Preview digest without sending messages")
    p_run.add_argument("--date", type=str, default=None, help="Custom digest date (YYYY-MM-DD)")
    p_run.add_argument("--force", action="store_true", help="Force run even if already completed today")

    # collect
    subparsers.add_parser("collect", help="Fetch feeds and display statistics without delivery")

    # preview
    p_prev = subparsers.add_parser("preview", help="Generate digest preview without sending")
    p_prev.add_argument("--date", type=str, default=None, help="Custom digest date (YYYY-MM-DD)")

    # test commands
    subparsers.add_parser("test-telegram", help="Send a Telegram test message")
    subparsers.add_parser("test-email", help="Send an email test message")
    subparsers.add_parser("test-delivery", help="Test both Telegram and email channels")
    subparsers.add_parser("test-llm", help="Test LLM AI summarization")

    # sources
    subparsers.add_parser("sources", help="List configured feeds and their statuses")

    # retry-failed
    subparsers.add_parser("retry-failed", help="Retry failed deliveries without resending successful channels")

    # health
    subparsers.add_parser("health", help="Validate configuration and source status")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_level)
    coordinator = WorkflowCoordinator(settings)

    command_map = {
        "run": cmd_run,
        "collect": cmd_collect,
        "preview": cmd_preview,
        "test-telegram": cmd_test_telegram,
        "test-email": cmd_test_email,
        "test-delivery": cmd_test_delivery,
        "test-llm": cmd_test_llm,
        "sources": cmd_sources,
        "retry-failed": cmd_retry_failed,
        "health": cmd_health,
    }

    handler = command_map.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    return handler(coordinator, args)


if __name__ == "__main__":
    sys.exit(main())
