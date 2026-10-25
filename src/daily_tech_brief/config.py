"""Application configuration and environment variable management."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# Load .env file automatically from project root if present
load_dotenv()


@dataclass
class RankingWeights:
    """Configurable weights for the multi-factor ranking algorithm."""
    relevance: float = 0.35
    freshness: float = 0.25
    importance: float = 0.20
    credibility: float = 0.15
    novelty: float = 0.05

    def normalize(self) -> RankingWeights:
        """Ensure sum of weights equals 1.0."""
        total = self.relevance + self.freshness + self.importance + self.credibility + self.novelty
        if total <= 0:
            return RankingWeights()
        return RankingWeights(
            relevance=self.relevance / total,
            freshness=self.freshness / total,
            importance=self.importance / total,
            credibility=self.credibility / total,
            novelty=self.novelty / total,
        )


@dataclass
class Settings:
    """Core application settings with safe defaults and validation."""
    # Telegram
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", "").strip())

    # Email / SMTP
    email_host: str = field(default_factory=lambda: os.getenv("EMAIL_HOST", "smtp.gmail.com").strip())
    email_port: int = field(default_factory=lambda: int(os.getenv("EMAIL_PORT", "587")))
    email_username: str = field(default_factory=lambda: os.getenv("EMAIL_USERNAME", "").strip())
    email_password: str = field(default_factory=lambda: os.getenv("EMAIL_PASSWORD", "").strip())
    email_sender: str = field(default_factory=lambda: os.getenv("EMAIL_SENDER", "").strip())
    email_recipient: str = field(default_factory=lambda: os.getenv("EMAIL_RECIPIENT", "").strip())

    # Timezone & Schedule
    timezone_name: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata").strip())

    # Digest and Selection Rules
    digest_limit: int = field(default_factory=lambda: int(os.getenv("DIGEST_LIMIT", "10")))
    lookback_hours: int = field(default_factory=lambda: int(os.getenv("LOOKBACK_HOURS", "24")))
    fallback_lookback_hours: int = field(default_factory=lambda: int(os.getenv("FALLBACK_LOOKBACK_HOURS", "48")))
    max_articles_per_source: int = field(default_factory=lambda: int(os.getenv("MAX_ARTICLES_PER_SOURCE", "2")))
    enable_opportunities: bool = field(
        default_factory=lambda: os.getenv("ENABLE_OPPORTUNITIES", "true").lower() in ("true", "1", "yes")
    )

    # Persistence & Logging
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/daily_tech_brief.db").strip())
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").strip().upper())
    feeds_config_path: str = field(default_factory=lambda: os.getenv("FEEDS_CONFIG_PATH", "config/feeds.yaml").strip())
    retention_days: int = field(default_factory=lambda: int(os.getenv("RETENTION_DAYS", "90")))

    # AI Summarization
    enable_llm_summaries: bool = field(
        default_factory=lambda: os.getenv("ENABLE_LLM_SUMMARIES", "false").lower() in ("true", "1", "yes")
    )
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gemini").strip().lower())
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", "").strip())
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gemini-1.5-flash").strip())

    # Ranking weights
    weights: RankingWeights = field(default_factory=RankingWeights)

    def get_timezone(self) -> ZoneInfo:
        """Return the configured ZoneInfo instance or fall back to UTC."""
        try:
            return ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, Exception):
            return ZoneInfo("UTC")

    def validate_telegram(self) -> List[str]:
        """Validate Telegram credentials."""
        errors = []
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required for Telegram delivery.")
        if not self.telegram_chat_id:
            errors.append("TELEGRAM_CHAT_ID is required for Telegram delivery.")
        return errors

    def validate_email(self) -> List[str]:
        """Validate SMTP Email credentials."""
        errors = []
        if not self.email_host:
            errors.append("EMAIL_HOST is required for Email delivery.")
        if not self.email_username:
            errors.append("EMAIL_USERNAME is required for Email delivery.")
        if not self.email_password:
            errors.append("EMAIL_PASSWORD is required for Email delivery.")
        if not self.email_recipient:
            errors.append("EMAIL_RECIPIENT is required for Email delivery.")
        return errors

    def validate_llm(self) -> List[str]:
        """Validate LLM configuration if enabled."""
        errors = []
        if self.enable_llm_summaries and not self.llm_api_key:
            errors.append("ENABLE_LLM_SUMMARIES is true but LLM_API_KEY is not set.")
        return errors

    def validate_all(self, require_delivery: bool = False) -> Dict[str, List[str]]:
        """Validate all subsystems."""
        results: Dict[str, List[str]] = {
            "telegram": self.validate_telegram(),
            "email": self.validate_email(),
            "llm": self.validate_llm(),
            "database": [],
        }

        # Check database directory writability
        db_dir = Path(self.database_path).parent
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            results["database"].append(f"Cannot create or access database directory {db_dir}: {e}")

        return results


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
