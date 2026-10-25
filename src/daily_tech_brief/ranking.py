"""Explainable scoring, diversity filtering, and article selection engine."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from daily_tech_brief.config import RankingWeights
from daily_tech_brief.models import Article

logger = logging.getLogger(__name__)

# High-impact importance indicators
HIGH_IMPORTANCE_PATTERNS = [
    r"\bcve-\d{4}-\d+\b",
    r"\bzero-day\b",
    r"\bcritical vulnerability\b",
    r"\bremote code execution\b|\brce\b",
    r"\bactive(?:ly)? exploit(?:ed)?\b",
    r"\bmodel release\b|\bweights release(?:d)?\b",
    r"\bdeepseek[- ]r1\b|\bclaude[- ]3\b|\bgpt-4o\b|\bllama[- ]3\b|\bgemini[- ]1\.5\b",
    r"\bv1\.0\b|\bversion 1\.0\b|\bmajor release\b",
    r"\bopen[- ]source(?:d)?\b",
    r"\bdeadline approaching\b|\bapplications open\b",
    r"\braised? \$\d+(?:\.\d+)?(?:m|b| million| billion)\b",
    r"\bacquired by\b|\bacquisition of\b",
    r"\bstate of the art\b|\bsota\b",
]

# Clickbait words to penalize
CLICKBAIT_PATTERNS = [
    r"\byou won't believe\b",
    r"\bshocking\b",
    r"\bwill blow your mind\b",
    r"\bthis one trick\b",
    r"\bgame[- ]changer\b",
    r"\bdestroy(?:s)?\b",
]


class ArticleRanker:
    """Multi-factor explainable scoring and diversity-constrained selection."""

    def __init__(
        self,
        weights: Optional[RankingWeights] = None,
        max_per_source: int = 2,
        target_stories: int = 10,
        min_stories: int = 5,
    ) -> None:
        self.weights = (weights or RankingWeights()).normalize()
        self.max_per_source = max_per_source
        self.target_stories = target_stories
        self.min_stories = min_stories

    def compute_freshness_score(
        self, published_at: Optional[datetime], now: datetime
    ) -> float:
        """Calculate freshness score (0 - 100) based on age."""
        if not published_at:
            return 45.0  # Neutral fallback for missing publication timestamps

        age = now - published_at
        age_hours = age.total_seconds() / 3600.0

        if age_hours < 0:
            # Clock skew or future timestamp - treat as fresh
            return 95.0
        elif age_hours <= 6.0:
            # 0 to 6 hours old: 90 - 100
            return 100.0 - (age_hours / 6.0) * 10.0
        elif age_hours <= 24.0:
            # 6 to 24 hours old: 70 - 89
            return 89.0 - ((age_hours - 6.0) / 18.0) * 19.0
        elif age_hours <= 48.0:
            # 24 to 48 hours old: 40 - 69
            return 69.0 - ((age_hours - 24.0) / 24.0) * 29.0
        else:
            # Over 48 hours old
            return max(5.0, 39.0 - (age_hours - 48.0) * 0.5)

    def compute_importance_score(self, article: Article) -> float:
        """Calculate impact/importance score (0 - 100) based on verified signals."""
        text = f"{article.title} {article.description}".lower()
        base_importance = 50.0

        # High impact pattern matches
        impact_matches = 0
        for pattern in HIGH_IMPORTANCE_PATTERNS:
            if re.search(pattern, text):
                impact_matches += 1

        base_importance += min(40.0, impact_matches * 15.0)

        # Opportunities: boost if upcoming deadline or active application
        if article.is_opportunity and article.opportunity_data:
            if article.opportunity_data.deadline:
                base_importance += 15.0

        # Corroborating sources boost: story reported by multiple outlets
        if article.corroborating_sources:
            base_importance += min(15.0, len(article.corroborating_sources) * 5.0)

        # Clickbait penalty
        for pattern in CLICKBAIT_PATTERNS:
            if re.search(pattern, text):
                base_importance -= 15.0

        return max(10.0, min(100.0, base_importance))

    def compute_novelty_score(self, article: Article) -> float:
        """Calculate novelty score (0 - 100)."""
        base_novelty = 70.0
        # If it has corroborating reports, novelty of development is high
        if article.corroborating_sources:
            base_novelty += 15.0
        return min(100.0, base_novelty)

    def score_article(self, article: Article, now: datetime) -> Article:
        """Score article across all five dimensions and compute explainable combined score."""
        article.recency_score = self.compute_freshness_score(article.published_at, now)
        article.importance_score = self.compute_importance_score(article)
        article.novelty_score = self.compute_novelty_score(article)
        
        # Source credibility comes from source reliability weight
        credibility = max(10.0, min(100.0, article.source_credibility_score))

        # Combined weighted formula
        combined = (
            (article.relevance_score * self.weights.relevance)
            + (article.recency_score * self.weights.freshness)
            + (article.importance_score * self.weights.importance)
            + (credibility * self.weights.credibility)
            + (article.novelty_score * self.weights.novelty)
        )
        article.combined_score = round(combined, 2)

        # Explainable breakdown
        article.ranking_explanation = (
            f"Score: {article.combined_score:.1f} | "
            f"Rel({self.weights.relevance*100:.0f}%): {article.relevance_score:.1f}, "
            f"Fresh({self.weights.freshness*100:.0f}%): {article.recency_score:.1f}, "
            f"Imp({self.weights.importance*100:.0f}%): {article.importance_score:.1f}, "
            f"Cred({self.weights.credibility*100:.0f}%): {credibility:.1f}, "
            f"Nov({self.weights.novelty*100:.0f}%): {article.novelty_score:.1f}"
        )
        return article

    def filter_by_window(
        self,
        articles: List[Article],
        lookback_hours: int,
        now: datetime,
    ) -> List[Article]:
        """Filter articles published within the given lookback window."""
        cutoff = now - timedelta(hours=lookback_hours)
        valid: List[Article] = []

        for a in articles:
            # If publication date is missing, evaluate by first_seen_at
            pub_date = a.published_at or a.first_seen_at
            if pub_date is None or pub_date >= cutoff:
                valid.append(a)

        return valid

    def select_stories(
        self,
        articles: List[Article],
        primary_lookback_hours: int,
        fallback_lookback_hours: int,
        now: datetime,
    ) -> Tuple[List[Article], bool]:
        """Select top 8-10 diverse stories with fallback window support for low-news days.
        
        Returns:
            Tuple of (selected_articles, used_fallback_window)
        """
        # Score all articles
        for a in articles:
            self.score_article(a, now)

        # Primary window candidate pool
        candidates = self.filter_by_window(articles, primary_lookback_hours, now)
        used_fallback = False

        # If primary window yields insufficient stories, broaden to fallback window
        if len(candidates) < self.min_stories and fallback_lookback_hours > primary_lookback_hours:
            logger.info(
                f"Primary window ({primary_lookback_hours}h) yielded {len(candidates)} candidates; "
                f"extending to fallback window ({fallback_lookback_hours}h)."
            )
            candidates = self.filter_by_window(articles, fallback_lookback_hours, now)
            used_fallback = True

        # Sort descending by combined score
        candidates.sort(key=lambda x: x.combined_score, reverse=True)

        selected: List[Article] = []
        source_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}

        # First pass: Select top stories respecting source diversity cap
        for article in candidates:
            if len(selected) >= self.target_stories:
                break

            src = article.source_id
            curr_src_count = source_counts.get(src, 0)
            if curr_src_count >= self.max_per_source:
                continue

            # Check category diversity: avoid single category monopolizing (> 4 stories)
            primary_cat = article.categories[0] if article.categories else "general"
            curr_cat_count = category_counts.get(primary_cat, 0)
            if curr_cat_count >= 4 and len(candidates) > self.target_stories:
                continue

            selected.append(article)
            source_counts[src] = curr_src_count + 1
            category_counts[primary_cat] = curr_cat_count + 1

        # Second pass: if below minimum stories, relax strict source caps to include best remaining
        if len(selected) < self.min_stories and len(candidates) > len(selected):
            for article in candidates:
                if article not in selected:
                    selected.append(article)
                    if len(selected) >= self.target_stories:
                        break

        logger.info(f"Selected {len(selected)} stories (target {self.target_stories}, fallback={used_fallback})")
        return selected, used_fallback
