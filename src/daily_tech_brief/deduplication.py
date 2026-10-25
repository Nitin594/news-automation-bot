"""Multi-level deduplication and cross-day delivery suppression."""

from __future__ import annotations

import logging
import re
import string
from typing import Dict, List, Set, Tuple

from daily_tech_brief.models import Article

logger = logging.getLogger(__name__)

PUNCT_TRANSLATOR = str.maketrans("", "", string.punctuation)
STOP_WORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "is", "are", "was", "were", "by", "from", "its", "it", "this", "that"
}
TOKEN_RE = re.compile(r"\b[a-z0-9]+(?:\.[a-z0-9]+)*\b")


def normalize_title(title: str) -> str:
    """Normalize title for matching by lowercasing and removing punctuation."""
    if not title:
        return ""
    cleaned = title.lower().translate(PUNCT_TRANSLATOR)
    return " ".join(cleaned.split())


def stem_token(token: str) -> str:
    """Apply lightweight English stemming for common verb/plural suffixes."""
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def get_title_tokens(title: str) -> Set[str]:
    """Extract significant lowercase, stop-word filtered, stemmed tokens from title."""
    words = TOKEN_RE.findall(title.lower())
    tokens = set()
    for w in words:
        if w not in STOP_WORDS and len(w) >= 2:
            tokens.add(stem_token(w))
    return tokens


def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    """Calculate Jaccard similarity between two token sets."""
    if not set1 or not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return float(intersection) / float(union) if union > 0 else 0.0


class ArticleDeduplicator:
    """Deduplicates incoming articles within a run and suppresses previously delivered stories."""

    def __init__(self, similarity_threshold: float = 0.82) -> None:
        self.similarity_threshold = similarity_threshold

    def deduplicate_batch(self, articles: List[Article]) -> List[Article]:
        """Deduplicate articles within the current batch.
        
        Merges near-duplicates and records corroborating sources.
        """
        unique_articles: List[Article] = []
        seen_urls: Set[str] = set()
        seen_titles: Dict[str, Article] = {}

        for article in articles:
            # 1. Exact canonical URL deduplication
            if article.canonical_url in seen_urls:
                logger.debug(f"Duplicate canonical URL dropped: {article.canonical_url}")
                continue

            norm_title = normalize_title(article.title)
            if not norm_title:
                continue

            # 2. Normalized exact title match
            if norm_title in seen_titles:
                primary = seen_titles[norm_title]
                primary.corroborating_sources.append({
                    "source_id": article.source_id,
                    "source_name": article.source_name,
                    "url": article.original_url,
                })
                logger.debug(f"Duplicate title merged: '{article.title}' into '{primary.title}'")
                continue

            # 3. Near-duplicate title detection using token similarity
            article_tokens = get_title_tokens(article.title)
            is_near_duplicate = False

            for existing in unique_articles:
                existing_tokens = get_title_tokens(existing.title)
                sim = jaccard_similarity(article_tokens, existing_tokens)
                if sim >= self.similarity_threshold:
                    is_near_duplicate = True
                    # Record corroborating source
                    existing.corroborating_sources.append({
                        "source_id": article.source_id,
                        "source_name": article.source_name,
                        "url": article.original_url,
                    })
                    # If incoming article is from a substantially more credible source, upgrade existing
                    if article.source_credibility_score > existing.source_credibility_score + 10.0:
                        existing.source_credibility_score = article.source_credibility_score
                    logger.debug(
                        f"Near-duplicate merged (sim={sim:.2f}): '{article.title}' into '{existing.title}'"
                    )
                    break

            if not is_near_duplicate:
                seen_urls.add(article.canonical_url)
                seen_titles[norm_title] = article
                unique_articles.append(article)

        return unique_articles

    def filter_previously_delivered(
        self,
        articles: List[Article],
        delivered_urls: Set[str],
        delivered_titles: Set[str],
    ) -> List[Article]:
        """Filter out articles that were already delivered in prior daily digests."""
        fresh_articles: List[Article] = []

        for article in articles:
            if article.canonical_url in delivered_urls:
                logger.debug(f"Suppressed previously delivered URL: {article.canonical_url}")
                continue

            norm_title = normalize_title(article.title)
            if norm_title in delivered_titles:
                logger.debug(f"Suppressed previously delivered title: '{article.title}'")
                continue

            fresh_articles.append(article)

        return fresh_articles
