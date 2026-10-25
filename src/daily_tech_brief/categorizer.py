"""Categorization and keyword matching engine."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set, Tuple

from daily_tech_brief.models import Article

logger = logging.getLogger(__name__)


class ArticleCategorizer:
    """Categorizes articles, extracts keywords, and scores topic relevance."""

    def __init__(
        self,
        categories: Dict[str, Dict[str, Any]],
        excluded_topics: Optional[List[str]] = None,
    ) -> None:
        self.categories = categories
        self.excluded_topics = [t.lower().strip() for t in (excluded_topics or [])]

    def is_excluded(self, text: str) -> bool:
        """Check if article text matches any excluded topic filter."""
        lower_text = text.lower()
        for excluded in self.excluded_topics:
            if excluded and excluded in lower_text:
                return True
        return False

    def categorize(self, article: Article) -> Article:
        """Assign categories, match keywords, and compute initial relevance score."""
        full_text = f"{article.title} {article.description}".lower()

        # Check exclusion filter
        if self.is_excluded(full_text):
            article.relevance_score = 0.0
            article.ranking_explanation = "Article matches excluded topic filter."
            return article

        matched_categories: Set[str] = set(article.categories)
        matched_keywords: Set[str] = set()
        category_relevance_accum: float = 0.0

        for cat_id, cat_info in self.categories.items():
            keywords = cat_info.get("keywords", [])
            cat_weight = float(cat_info.get("weight", 1.0))
            cat_matches = 0

            for kw in keywords:
                # Word-boundary or token match
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, full_text):
                    matched_keywords.add(kw)
                    cat_matches += 1

            if cat_matches > 0:
                matched_categories.add(cat_id)
                category_relevance_accum += (cat_matches * 10.0 * cat_weight)

        # Opportunities handling
        if article.is_opportunity:
            matched_categories.add("internships_and_hackathons")
            category_relevance_accum += 20.0

        article.categories = sorted(list(matched_categories))
        article.matched_keywords = sorted(list(matched_keywords))

        # Base relevance calculation (0 - 100)
        # Having at least 1 keyword match gives a solid starting relevance of 60
        if article.matched_keywords:
            raw_relevance = 60.0 + min(35.0, category_relevance_accum * 0.5)
        elif article.categories:
            # Matched default source category but no explicit keywords
            raw_relevance = 50.0
        else:
            raw_relevance = 30.0

        article.relevance_score = max(0.0, min(100.0, raw_relevance))
        return article
