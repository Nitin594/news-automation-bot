"""SQLite persistent state management, delivery tracking, and deduplication records."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from daily_tech_brief.models import Article, DeliveryResult, DigestRun, OpportunityMetadata

logger = logging.getLogger(__name__)


class Storage:
    """SQLite persistence layer for Daily Tech Brief."""

    def __init__(self, db_path: str = "data/daily_tech_brief.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for SQLite database connection with row factory and WAL mode."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=20.0,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create necessary database tables and indices if they do not exist."""
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    canonical_url TEXT UNIQUE NOT NULL,
                    original_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    source_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    author TEXT,
                    published_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    categories TEXT,
                    matched_keywords TEXT,
                    combined_score REAL DEFAULT 50.0,
                    ranking_explanation TEXT,
                    summary TEXT,
                    why_it_matters TEXT,
                    technical_context TEXT,
                    summary_method TEXT DEFAULT 'feed',
                    content_hash TEXT,
                    is_opportunity INTEGER DEFAULT 0,
                    opportunity_data TEXT,
                    is_delivered INTEGER DEFAULT 0,
                    corroborating_sources TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at);
                CREATE INDEX IF NOT EXISTS idx_articles_is_delivered ON articles (is_delivered);
                CREATE INDEX IF NOT EXISTS idx_articles_canonical_url ON articles (canonical_url);

                CREATE TABLE IF NOT EXISTS feed_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    status_code INTEGER,
                    status TEXT NOT NULL,
                    duration_ms INTEGER,
                    articles_count INTEGER,
                    etag TEXT,
                    last_modified TEXT,
                    error_message TEXT,
                    fetched_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_feed_runs_source_fetched ON feed_runs (source_id, fetched_at DESC);

                CREATE TABLE IF NOT EXISTS digest_runs (
                    run_id TEXT PRIMARY KEY,
                    digest_date TEXT NOT NULL,
                    coverage_start TEXT NOT NULL,
                    coverage_end TEXT NOT NULL,
                    status TEXT NOT NULL,
                    story_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_digest_runs_date ON digest_runs (digest_date);

                CREATE TABLE IF NOT EXISTS digest_articles (
                    digest_id TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    rank_position INTEGER NOT NULL,
                    section TEXT,
                    PRIMARY KEY (digest_id, article_id),
                    FOREIGN KEY (digest_id) REFERENCES digest_runs (run_id) ON DELETE CASCADE,
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    digest_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER DEFAULT 1,
                    last_error TEXT,
                    message_id TEXT,
                    delivered_at TEXT,
                    UNIQUE (digest_id, channel),
                    FOREIGN KEY (digest_id) REFERENCES digest_runs (run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS summary_cache (
                    content_hash TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    why_it_matters TEXT,
                    technical_context TEXT,
                    method TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def get_feed_cache_metadata(self, source_id: str) -> Dict[str, Optional[str]]:
        """Retrieve the last seen ETag and Last-Modified headers for a source."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT etag, last_modified FROM feed_runs
                WHERE source_id = ? AND (etag IS NOT NULL OR last_modified IS NOT NULL)
                ORDER BY id DESC LIMIT 1
                """,
                (source_id,),
            ).fetchone()
            if row:
                return {"etag": row["etag"], "last_modified": row["last_modified"]}
            return {"etag": None, "last_modified": None}

    def record_feed_run(
        self,
        source_id: str,
        status_code: Optional[int],
        status: str,
        duration_ms: int,
        articles_count: int,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        error_message: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> None:
        """Record the execution outcome of an RSS/Atom fetch."""
        now_str = (now or datetime.now(timezone.utc)).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO feed_runs (
                    source_id, status_code, status, duration_ms,
                    articles_count, etag, last_modified, error_message, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    status_code,
                    status,
                    duration_ms,
                    articles_count,
                    etag,
                    last_modified,
                    error_message,
                    now_str,
                ),
            )

    def save_articles(self, articles: List[Article]) -> None:
        """Insert or update articles."""
        with self._get_connection() as conn:
            for a in articles:
                pub_str = a.published_at.isoformat() if a.published_at else None
                seen_str = a.first_seen_at.isoformat() if a.first_seen_at else datetime.now(timezone.utc).isoformat()
                opp_str = json.dumps(a.opportunity_data.to_dict()) if a.opportunity_data else None
                cats_str = json.dumps(a.categories)
                kw_str = json.dumps(a.matched_keywords)
                corroborating_str = json.dumps(a.corroborating_sources)

                conn.execute(
                    """
                    INSERT INTO articles (
                        id, canonical_url, original_url, title, description,
                        source_id, source_name, author, published_at, first_seen_at,
                        categories, matched_keywords, combined_score, ranking_explanation,
                        summary, why_it_matters, technical_context, summary_method,
                        content_hash, is_opportunity, opportunity_data, is_delivered,
                        corroborating_sources
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_url) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        combined_score = excluded.combined_score,
                        ranking_explanation = excluded.ranking_explanation,
                        summary = COALESCE(excluded.summary, articles.summary),
                        why_it_matters = COALESCE(excluded.why_it_matters, articles.why_it_matters),
                        summary_method = COALESCE(excluded.summary_method, articles.summary_method),
                        corroborating_sources = excluded.corroborating_sources
                    """,
                    (
                        a.id,
                        a.canonical_url,
                        a.original_url,
                        a.title,
                        a.description,
                        a.source_id,
                        a.source_name,
                        a.author,
                        pub_str,
                        seen_str,
                        cats_str,
                        kw_str,
                        a.combined_score,
                        a.ranking_explanation,
                        a.summary,
                        a.why_it_matters,
                        a.technical_context,
                        a.summary_method,
                        a.content_hash,
                        1 if a.is_opportunity else 0,
                        opp_str,
                        1 if a.is_delivered else 0,
                        corroborating_str,
                    ),
                )

    def get_delivered_urls_and_titles(self, retention_days: int = 90) -> Tuple[Set[str], Set[str]]:
        """Retrieve set of canonical URLs and titles delivered within retention window."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        urls: Set[str] = set()
        titles: Set[str] = set()

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT a.canonical_url, a.title
                FROM articles a
                JOIN digest_articles da ON a.id = da.article_id
                JOIN digest_runs dr ON da.digest_id = dr.run_id
                WHERE dr.created_at >= ?
                  AND dr.status IN ('SUCCESS', 'PARTIAL_FAILURE')
                UNION
                SELECT canonical_url, title FROM articles WHERE is_delivered = 1
                """,
                (cutoff,),
            ).fetchall()

            for r in rows:
                if r["canonical_url"]:
                    urls.add(r["canonical_url"])
                if r["title"]:
                    # Clean title for comparison
                    from daily_tech_brief.deduplication import normalize_title
                    titles.add(normalize_title(r["title"]))

        return urls, titles

    def create_digest_run(self, run: DigestRun, articles: List[Article]) -> None:
        """Record a digest run and associate selected articles."""
        now_str = (run.created_at or datetime.now(timezone.utc)).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO digest_runs (
                    run_id, digest_date, coverage_start, coverage_end, status, story_count, created_at, last_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    story_count = excluded.story_count,
                    last_updated_at = excluded.last_updated_at
                """,
                (
                    run.run_id,
                    run.digest_date,
                    run.coverage_start.isoformat(),
                    run.coverage_end.isoformat(),
                    run.status,
                    len(articles),
                    now_str,
                    now_str,
                ),
            )

            # Insert digest articles mapping
            for idx, article in enumerate(articles, start=1):
                section = article.categories[0] if article.categories else "general"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO digest_articles (
                        digest_id, article_id, rank_position, section
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (run.run_id, article.id, idx, section),
                )

    def update_digest_status(self, run_id: str, status: str) -> None:
        """Update digest run status."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE digest_runs
                SET status = ?, last_updated_at = ?
                WHERE run_id = ?
                """,
                (status, now_str, run_id),
            )

    def mark_articles_delivered(self, article_ids: List[str]) -> None:
        """Flag articles as delivered in the database."""
        with self._get_connection() as conn:
            conn.executemany(
                "UPDATE articles SET is_delivered = 1 WHERE id = ?",
                [(aid,) for aid in article_ids],
            )

    def record_delivery_attempt(
        self,
        digest_id: str,
        channel: str,
        success: bool,
        error_message: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> None:
        """Record or update per-channel delivery status for a digest run."""
        status = "SUCCESS" if success else "FAILED"
        now_str = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            # Check if delivery attempt already exists
            existing = conn.execute(
                "SELECT id, attempt_count, status FROM deliveries WHERE digest_id = ? AND channel = ?",
                (digest_id, channel),
            ).fetchone()

            if existing:
                attempts = existing["attempt_count"] + 1
                conn.execute(
                    """
                    UPDATE deliveries SET
                        status = ?,
                        attempt_count = ?,
                        last_error = ?,
                        message_id = COALESCE(?, message_id),
                        delivered_at = ?
                    WHERE id = ?
                    """,
                    (status, attempts, error_message, message_id, now_str, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO deliveries (
                        digest_id, channel, status, attempt_count, last_error, message_id, delivered_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (digest_id, channel, status, error_message, message_id, now_str),
                )

    def get_delivery_statuses(self, digest_id: str) -> Dict[str, DeliveryResult]:
        """Fetch delivery status for all channels for a given digest run."""
        results: Dict[str, DeliveryResult] = {}
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT channel, status, last_error, message_id, delivered_at FROM deliveries WHERE digest_id = ?",
                (digest_id,),
            ).fetchall()

            for r in rows:
                results[r["channel"]] = DeliveryResult(
                    channel=r["channel"],
                    success=(r["status"] == "SUCCESS"),
                    status=r["status"],
                    error_message=r["last_error"],
                    message_id=r["message_id"],
                    timestamp=datetime.fromisoformat(r["delivered_at"]) if r["delivered_at"] else None,
                )
        return results

    def get_latest_digest_run(self) -> Optional[DigestRun]:
        """Fetch the most recent digest run."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM digest_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None

            return DigestRun(
                run_id=row["run_id"],
                digest_date=row["digest_date"],
                coverage_start=datetime.fromisoformat(row["coverage_start"]),
                coverage_end=datetime.fromisoformat(row["coverage_end"]),
                status=row["status"],
                story_count=row["story_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    def get_digest_articles(self, digest_id: str) -> List[Article]:
        """Fetch the articles associated with a digest run in their ranked order."""
        articles: List[Article] = []
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT a.*, da.rank_position
                FROM articles a
                JOIN digest_articles da ON a.id = da.article_id
                WHERE da.digest_id = ?
                ORDER BY da.rank_position ASC
                """,
                (digest_id,),
            ).fetchall()

            for r in rows:
                opp_data = OpportunityMetadata.from_dict(json.loads(r["opportunity_data"])) if r["opportunity_data"] else None
                pub_at = datetime.fromisoformat(r["published_at"]) if r["published_at"] else None
                first_seen = datetime.fromisoformat(r["first_seen_at"]) if r["first_seen_at"] else None

                art = Article(
                    id=r["id"],
                    canonical_url=r["canonical_url"],
                    original_url=r["original_url"],
                    title=r["title"],
                    description=r["description"] or "",
                    source_id=r["source_id"],
                    source_name=r["source_name"],
                    author=r["author"],
                    published_at=pub_at,
                    first_seen_at=first_seen,
                    categories=json.loads(r["categories"]) if r["categories"] else [],
                    matched_keywords=json.loads(r["matched_keywords"]) if r["matched_keywords"] else [],
                    combined_score=r["combined_score"],
                    ranking_explanation=r["ranking_explanation"] or "",
                    summary=r["summary"],
                    why_it_matters=r["why_it_matters"],
                    technical_context=r["technical_context"],
                    summary_method=r["summary_method"],
                    content_hash=r["content_hash"] or "",
                    is_opportunity=bool(r["is_opportunity"]),
                    opportunity_data=opp_data,
                    is_delivered=bool(r["is_delivered"]),
                    corroborating_sources=json.loads(r["corroborating_sources"]) if r["corroborating_sources"] else [],
                )
                articles.append(art)

        return articles

    def get_cached_summary(self, content_hash: str) -> Optional[Dict[str, str]]:
        """Fetch cached summary by content hash."""
        if not content_hash:
            return None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT summary, why_it_matters, technical_context, method FROM summary_cache WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if row:
                return {
                    "summary": row["summary"],
                    "why_it_matters": row["why_it_matters"],
                    "technical_context": row["technical_context"],
                    "method": row["method"],
                }
            return None

    def save_cached_summary(
        self,
        content_hash: str,
        summary: str,
        why_it_matters: Optional[str] = None,
        technical_context: Optional[str] = None,
        method: str = "llm",
    ) -> None:
        """Cache summary for an article."""
        if not content_hash or not summary:
            return
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO summary_cache (
                    content_hash, summary, why_it_matters, technical_context, method, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (content_hash, summary, why_it_matters, technical_context, method, now_str),
            )

    def cleanup_old_records(self, retention_days: int = 90) -> int:
        """Clean up records older than retention period without removing needed deduplication data."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._get_connection() as conn:
            # Delete old feed runs
            cur = conn.execute("DELETE FROM feed_runs WHERE fetched_at < ?", (cutoff,))
            deleted = cur.rowcount
            # Delete non-delivered old articles
            cur2 = conn.execute(
                "DELETE FROM articles WHERE first_seen_at < ? AND is_delivered = 0",
                (cutoff,),
            )
            deleted += cur2.rowcount
            return deleted
