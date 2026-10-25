"""Feed registry and source metadata loader."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from daily_tech_brief.models import SourceConfig

logger = logging.getLogger(__name__)


DEFAULT_CATEGORIES: List[Dict[str, Any]] = [
    {
        "id": "ai_and_llms",
        "name": "AI & LLMs",
        "weight": 1.2,
        "keywords": ["llm", "large language model", "foundation model", "gpt", "claude", "gemini", "llama", "deepseek", "ai agent", "inference", "rag"],
    },
    {
        "id": "software_dev",
        "name": "Software Development",
        "weight": 1.1,
        "keywords": ["python", "rust", "golang", "typescript", "react", "next.js", "database", "distributed systems", "docker", "kubernetes", "api"],
    },
    {
        "id": "cybersecurity",
        "name": "Cybersecurity Watch",
        "weight": 1.15,
        "keywords": ["cve", "vulnerability", "zero-day", "exploit", "ransomware", "malware", "data breach", "security advisory", "patch", "cisa"],
    },
    {
        "id": "internships_and_hackathons",
        "name": "Internships & Opportunities",
        "weight": 1.25,
        "keywords": ["internship", "intern", "hackathon", "fellowship", "student program", "gsoc", "mentorship", "grant", "scholarship"],
    },
    {
        "id": "startups_and_industry",
        "name": "Big Tech & Startups",
        "weight": 1.0,
        "keywords": ["startup", "funding", "seed round", "series a", "acquisition", "nvidia", "google", "microsoft", "meta", "semiconductor"],
    },
    {
        "id": "research_and_opensource",
        "name": "Research & Open Source",
        "weight": 1.1,
        "keywords": ["arxiv", "paper", "research", "preprint", "benchmark", "dataset", "open source", "github release", "repository", "sota"],
    },
]


class SourceRegistry:
    """Manages configured news feeds, categories, and keyword rules."""

    def __init__(self, config_path: str = "config/feeds.yaml") -> None:
        self.config_path = Path(config_path)
        self.sources: Dict[str, SourceConfig] = {}
        self.categories: Dict[str, Dict[str, Any]] = {}
        self.excluded_topics: List[str] = []
        self.load()

    def load(self) -> None:
        """Load feeds and categories from YAML file or fall back to safe defaults."""
        self.sources.clear()
        self.categories.clear()
        self.excluded_topics.clear()

        if not self.config_path.exists():
            logger.warning(f"Feeds configuration file not found at {self.config_path}. Loading built-in defaults.")
            self._load_fallback_defaults()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Load categories
            for cat in data.get("categories", []):
                cat_id = cat.get("id")
                if cat_id:
                    self.categories[cat_id] = {
                        "id": cat_id,
                        "name": cat.get("name", cat_id.replace("_", " ").title()),
                        "weight": float(cat.get("weight", 1.0)),
                        "description": cat.get("description", ""),
                        "keywords": [k.lower().strip() for k in cat.get("keywords", []) if k],
                    }

            if not self.categories:
                self._load_default_categories()

            # Load excluded topics
            self.excluded_topics = [
                str(t).lower().strip() for t in data.get("excluded_topics", []) if t
            ]

            # Load feeds
            for entry in data.get("feeds", []):
                feed_id = entry.get("id")
                url = entry.get("url")
                if not feed_id or not url:
                    logger.warning(f"Skipping invalid feed entry without id or url: {entry}")
                    continue

                source = SourceConfig(
                    id=feed_id,
                    name=entry.get("name", feed_id),
                    url=url,
                    source_type=entry.get("source_type", "rss"),
                    categories=entry.get("categories", []),
                    reliability_weight=float(entry.get("reliability_weight", 75.0)),
                    enabled=bool(entry.get("enabled", True)),
                    timeout_seconds=int(entry.get("timeout_seconds", 15)),
                    attribution=entry.get("attribution", entry.get("name")),
                    is_opportunity_source=bool(entry.get("is_opportunity_source", False)),
                )
                self.sources[feed_id] = source

            logger.info(f"Loaded {len(self.sources)} feeds and {len(self.categories)} categories from {self.config_path}")

        except Exception as e:
            logger.error(f"Failed to parse feeds configuration from {self.config_path}: {e}. Using fallback defaults.")
            self._load_fallback_defaults()

    def _load_default_categories(self) -> None:
        for cat in DEFAULT_CATEGORIES:
            self.categories[cat["id"]] = cat

    def _load_fallback_defaults(self) -> None:
        self._load_default_categories()
        # Minimal set of rock-solid default feeds
        default_feeds = [
            SourceConfig(
                id="arxiv_ai",
                name="arXiv cs.AI",
                url="https://rss.arxiv.org/rss/cs.AI",
                categories=["ai_and_llms", "research_and_opensource"],
                reliability_weight=90.0,
            ),
            SourceConfig(
                id="github_blog",
                name="GitHub Blog",
                url="https://github.blog/feed/",
                categories=["software_dev", "research_and_opensource"],
                reliability_weight=92.0,
            ),
            SourceConfig(
                id="hnrss_frontpage",
                name="Hacker News Frontpage",
                url="https://hnrss.org/frontpage",
                categories=["software_dev", "ai_and_llms", "startups_and_industry"],
                reliability_weight=85.0,
            ),
            SourceConfig(
                id="cisa_advisories",
                name="CISA Advisories",
                url="https://www.cisa.gov/cybersecurity-advisories/all.xml",
                categories=["cybersecurity"],
                reliability_weight=98.0,
            ),
        ]
        for f in default_feeds:
            self.sources[f.id] = f

    def get_enabled_sources(self) -> List[SourceConfig]:
        """Return all active, enabled sources."""
        return [s for s in self.sources.values() if s.enabled]

    def get_source(self, source_id: str) -> Optional[SourceConfig]:
        """Retrieve source config by ID."""
        return self.sources.get(source_id)
