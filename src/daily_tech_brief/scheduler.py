"""Workflow orchestrator, timezone scheduler logic, and end-to-end execution pipeline."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from daily_tech_brief.categorizer import ArticleCategorizer
from daily_tech_brief.collector import FeedCollector, FetchResult
from daily_tech_brief.config import Settings, get_settings
from daily_tech_brief.deduplication import ArticleDeduplicator
from daily_tech_brief.delivery import DeliveryService
from daily_tech_brief.digest import DigestRenderer
from daily_tech_brief.models import Article, DigestRun
from daily_tech_brief.ranking import ArticleRanker
from daily_tech_brief.sources import SourceRegistry
from daily_tech_brief.storage import Storage
from daily_tech_brief.summarizer import SummarizationPipeline

logger = logging.getLogger(__name__)


class WorkflowCoordinator:
    """Coordinates feed collection, categorization, ranking, summarization, and multi-channel delivery."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.tz = self.settings.get_timezone()
        self.storage = Storage(self.settings.database_path)
        self.sources_registry = SourceRegistry(self.settings.feeds_config_path)
        self.categorizer = ArticleCategorizer(
            categories=self.sources_registry.categories,
            excluded_topics=self.sources_registry.excluded_topics,
        )
        self.deduplicator = ArticleDeduplicator()
        self.ranker = ArticleRanker(
            weights=self.settings.weights,
            max_per_source=self.settings.max_articles_per_source,
            target_stories=self.settings.digest_limit,
        )
        self.summarizer = SummarizationPipeline(
            enable_llm=self.settings.enable_llm_summaries,
            provider=self.settings.llm_provider,
            api_key=self.settings.llm_api_key,
            model=self.settings.llm_model,
            storage=self.storage,
        )
        self.renderer = DigestRenderer(self.tz)
        self.delivery = DeliveryService(self.settings)

    def get_run_metadata(self, custom_date: Optional[str] = None) -> Tuple[str, str, datetime, datetime, datetime]:
        """Compute run ID, digest date string, coverage start/end, and generation time."""
        now = datetime.now(self.tz)
        if custom_date:
            digest_date = custom_date
        else:
            digest_date = now.strftime("%Y-%m-%d")

        run_id = f"digest_{digest_date}"
        coverage_end = now
        coverage_start = now - timedelta(hours=self.settings.lookback_hours)

        return run_id, digest_date, coverage_start, coverage_end, now

    def collect_and_process_articles(
        self, now: Optional[datetime] = None
    ) -> Tuple[List[Article], List[FetchResult], int, int]:
        """Fetch feeds, normalize, categorize, and deduplicate articles.
        
        Returns:
            Tuple of (fresh_articles, fetch_results, total_raw_count, dedup_count)
        """
        now_dt = now or datetime.now(self.tz)
        enabled_sources = self.sources_registry.get_enabled_sources()
        collector = FeedCollector(enabled_sources, self.tz)

        # Build cached metadata for conditional GET
        cached_meta = {
            s.id: self.storage.get_feed_cache_metadata(s.id) for s in enabled_sources
        }

        # 1. Fetch feeds
        fetch_results = collector.fetch_all(cached_metadata=cached_meta, now=now_dt)

        all_articles: List[Article] = []
        for res in fetch_results:
            # Record feed fetch in database
            self.storage.record_feed_run(
                source_id=res.source_id,
                status_code=res.status_code,
                status=res.status,
                duration_ms=res.duration_ms,
                articles_count=res.articles_count,
                etag=res.etag,
                last_modified=res.last_modified,
                error_message=res.error_message,
                now=now_dt,
            )
            all_articles.extend(res.articles)

        raw_count = len(all_articles)

        # 2. Categorize & filter excluded topics
        categorized_articles: List[Article] = []
        for art in all_articles:
            cat_art = self.categorizer.categorize(art)
            if cat_art.relevance_score > 0:  # Not excluded
                categorized_articles.append(cat_art)

        # 3. Deduplicate batch (merging near-duplicates)
        batch_deduped = self.deduplicator.deduplicate_batch(categorized_articles)

        # 4. Filter previously delivered articles from past daily digests
        delivered_urls, delivered_titles = self.storage.get_delivered_urls_and_titles(
            retention_days=self.settings.retention_days
        )
        fresh_articles = self.deduplicator.filter_previously_delivered(
            batch_deduped, delivered_urls, delivered_titles
        )

        # 5. Persist fresh articles to storage
        self.storage.save_articles(fresh_articles)

        return fresh_articles, fetch_results, raw_count, len(fresh_articles)

    def execute_digest(
        self,
        dry_run: bool = False,
        custom_date: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Execute end-to-end digest run with idempotent checks and structured reporting."""
        start_time = time.perf_counter()
        run_id, digest_date, cov_start, cov_end, now_dt = self.get_run_metadata(custom_date)

        logger.info(f"Starting Daily Tech Brief run for {digest_date} (ID: {run_id}, dry_run={dry_run})")

        # Duplicate run prevention
        latest_run = self.storage.get_latest_digest_run()
        if latest_run and latest_run.digest_date == digest_date and latest_run.status == "SUCCESS" and not force and not dry_run:
            msg = f"Digest for {digest_date} already successfully delivered. Use force=True to re-run."
            logger.warning(msg)
            return {
                "status": "ALREADY_COMPLETED",
                "message": msg,
                "duration_seconds": round(time.perf_counter() - start_time, 2),
            }

        # Collection & Deduplication
        fresh_articles, fetch_results, raw_count, dedup_count = self.collect_and_process_articles(now=now_dt)

        feeds_configured = len(self.sources_registry.get_enabled_sources())
        feeds_successful = sum(1 for f in fetch_results if f.status in ("SUCCESS", "NOT_MODIFIED"))

        # Ranking & Selection
        selected_stories, used_fallback = self.ranker.select_stories(
            articles=fresh_articles,
            primary_lookback_hours=self.settings.lookback_hours,
            fallback_lookback_hours=self.settings.fallback_lookback_hours,
            now=now_dt,
        )

        # Summarization
        summarized_count = 0
        for story in selected_stories:
            self.summarizer.process_article(story)
            if story.summary_method in ("llm", "cached"):
                summarized_count += 1

        # Render Formats
        pretty_date = now_dt.strftime("%A, %d %B %Y")
        subject = f"Daily Tech Brief — {now_dt.strftime('%d %b %Y')}"
        plain_text = self.renderer.render_plain_text(selected_stories, pretty_date, now_dt, used_fallback)
        telegram_chunks = self.renderer.render_telegram_html(selected_stories, pretty_date, now_dt, used_fallback)
        email_html = self.renderer.render_email_html(selected_stories, pretty_date, now_dt, used_fallback)

        if dry_run:
            duration = round(time.perf_counter() - start_time, 2)
            print("\n" + "=" * 60)
            print(" DRY RUN PREVIEW (NO MESSAGES DELIVERED)")
            print("=" * 60 + "\n")
            print(plain_text)
            print("\n" + "-" * 60)
            print(f"Selection Breakdown ({len(selected_stories)} stories):")
            for idx, s in enumerate(selected_stories, start=1):
                print(f"{idx}. [{s.combined_score:.1f}] {s.title} ({s.source_name})")
                print(f"   Reason: {s.ranking_explanation}")
            print("-" * 60)

            return {
                "status": "DRY_RUN_COMPLETE",
                "stories_count": len(selected_stories),
                "duration_seconds": duration,
                "plain_text": plain_text,
            }

        # Create or update digest run record
        digest_run = DigestRun(
            run_id=run_id,
            digest_date=digest_date,
            coverage_start=cov_start,
            coverage_end=cov_end,
            status="IN_PROGRESS",
            story_count=len(selected_stories),
            created_at=now_dt,
        )
        self.storage.create_digest_run(digest_run, selected_stories)

        # Check existing delivery status for safe retries
        existing_deliveries = self.storage.get_delivery_statuses(run_id)
        skip_channels = [ch for ch, res in existing_deliveries.items() if res.success]

        # Deliver to Telegram and Email
        delivery_results = self.delivery.deliver_all(
            subject=subject,
            telegram_chunks=telegram_chunks,
            plain_text=plain_text,
            email_html=email_html,
            skip_channels=skip_channels,
        )

        # Merge with already successful deliveries
        for ch, res in existing_deliveries.items():
            if ch not in delivery_results and res.success:
                delivery_results[ch] = res

        # Record results in storage
        for channel, res in delivery_results.items():
            if channel not in skip_channels:
                self.storage.record_delivery_attempt(
                    digest_id=run_id,
                    channel=channel,
                    success=res.success,
                    error_message=res.error_message,
                    message_id=res.message_id,
                )

        # Determine overall workflow status
        telegram_success = delivery_results.get("telegram", {}).success if "telegram" in delivery_results else False
        email_success = delivery_results.get("email", {}).success if "email" in delivery_results else False

        if telegram_success and email_success:
            final_status = "SUCCESS"
            # Mark articles delivered in storage
            self.storage.mark_articles_delivered([s.id for s in selected_stories])
        elif telegram_success or email_success:
            final_status = "PARTIAL_FAILURE"
        else:
            final_status = "FAILED"

        self.storage.update_digest_status(run_id, final_status)
        total_duration = round(time.perf_counter() - start_time, 2)

        # Print structured run summary
        print("\n" + "=" * 45)
        print(f"Run status: {final_status}")
        print(f"Feeds configured: {feeds_configured}")
        print(f"Feeds successful: {feeds_successful}")
        print(f"Articles collected: {raw_count}")
        print(f"Articles after deduplication: {dedup_count}")
        print(f"Stories selected: {len(selected_stories)}")
        print(f"AI summaries generated: {summarized_count}")
        print(f"Telegram: {'SUCCESS' if telegram_success else 'FAILED'}")
        print(f"Email: {'SUCCESS' if email_success else 'FAILED'}")
        print(f"Duration: {total_duration:.1f} seconds")
        print("=" * 45 + "\n")

        return {
            "status": final_status,
            "feeds_configured": feeds_configured,
            "feeds_successful": feeds_successful,
            "articles_collected": raw_count,
            "articles_after_deduplication": dedup_count,
            "stories_selected": len(selected_stories),
            "ai_summaries_generated": summarized_count,
            "telegram": "SUCCESS" if telegram_success else "FAILED",
            "email": "SUCCESS" if email_success else "FAILED",
            "duration_seconds": total_duration,
        }

    def retry_failed_deliveries(self) -> Dict[str, Any]:
        """Retry delivery channels that failed during the latest digest run."""
        latest_run = self.storage.get_latest_digest_run()
        if not latest_run:
            print("No previous digest runs found to retry.")
            return {"status": "NO_RUNS"}

        if latest_run.status == "SUCCESS":
            print(f"Latest run ({latest_run.run_id}) already succeeded on all channels. Nothing to retry.")
            return {"status": "NOTHING_TO_RETRY"}

        print(f"Retrying failed delivery channels for run {latest_run.run_id} ({latest_run.digest_date})...")

        # Retrieve stored articles
        articles = self.storage.get_digest_articles(latest_run.run_id)
        if not articles:
            print("No articles associated with this run.")
            return {"status": "NO_ARTICLES"}

        # Render content
        pretty_date = datetime.now(self.tz).strftime("%A, %d %B %Y")
        subject = f"Daily Tech Brief — {latest_run.digest_date}"
        plain_text = self.renderer.render_plain_text(articles, pretty_date, datetime.now(self.tz))
        telegram_chunks = self.renderer.render_telegram_html(articles, pretty_date, datetime.now(self.tz))
        email_html = self.renderer.render_email_html(articles, pretty_date, datetime.now(self.tz))

        # Check existing deliveries
        existing = self.storage.get_delivery_statuses(latest_run.run_id)
        skip_channels = [ch for ch, res in existing.items() if res.success]

        results = self.delivery.deliver_all(
            subject=subject,
            telegram_chunks=telegram_chunks,
            plain_text=plain_text,
            email_html=email_html,
            skip_channels=skip_channels,
        )

        for channel, res in results.items():
            self.storage.record_delivery_attempt(
                digest_id=latest_run.run_id,
                channel=channel,
                success=res.success,
                error_message=res.error_message,
                message_id=res.message_id,
            )

        updated_statuses = self.storage.get_delivery_statuses(latest_run.run_id)
        tg_ok = updated_statuses.get("telegram", {}).success if "telegram" in updated_statuses else False
        em_ok = updated_statuses.get("email", {}).success if "email" in updated_statuses else False

        if tg_ok and em_ok:
            final_status = "SUCCESS"
            self.storage.mark_articles_delivered([a.id for a in articles])
        elif tg_ok or em_ok:
            final_status = "PARTIAL_FAILURE"
        else:
            final_status = "FAILED"

        self.storage.update_digest_status(latest_run.run_id, final_status)
        print(f"Retry complete. Status: {final_status} (Telegram: {tg_ok}, Email: {em_ok})")
        return {"status": final_status, "telegram": tg_ok, "email": em_ok}
