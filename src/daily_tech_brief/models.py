"""Data models for Daily Tech Brief."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class OpportunityMetadata:
    """Metadata for internships, hackathons, and student programs."""
    organization: str = ""
    opportunity_type: str = ""  # internship, hackathon, student_program, fellowship, mentorship
    location: str = ""         # e.g., Remote, Onsite, Hybrid
    application_url: str = ""
    deadline: Optional[str] = None
    eligibility: str = ""
    verification_status: str = "unverified"  # verified, unverified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "organization": self.organization,
            "opportunity_type": self.opportunity_type,
            "location": self.location,
            "application_url": self.application_url,
            "deadline": self.deadline,
            "eligibility": self.eligibility,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional[OpportunityMetadata]:
        if not data:
            return None
        return cls(
            organization=data.get("organization", ""),
            opportunity_type=data.get("opportunity_type", ""),
            location=data.get("location", ""),
            application_url=data.get("application_url", ""),
            deadline=data.get("deadline"),
            eligibility=data.get("eligibility", ""),
            verification_status=data.get("verification_status", "unverified"),
        )


@dataclass
class Article:
    """Normalized article model representing a tech news item or opportunity."""
    id: str  # Deterministic hash of canonical URL
    canonical_url: str
    original_url: str
    title: str
    description: str
    source_id: str
    source_name: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    first_seen_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    categories: List[str] = field(default_factory=list)
    matched_keywords: List[str] = field(default_factory=list)

    # Ranking sub-scores (0.0 to 100.0)
    source_credibility_score: float = 50.0
    recency_score: float = 50.0
    relevance_score: float = 50.0
    importance_score: float = 50.0
    novelty_score: float = 50.0
    combined_score: float = 50.0
    ranking_explanation: str = ""

    # Summarization
    summary: Optional[str] = None
    why_it_matters: Optional[str] = None
    technical_context: Optional[str] = None
    summary_method: str = "feed"  # 'feed', 'extractive', 'llm'
    content_hash: str = ""

    # Opportunity details
    is_opportunity: bool = False
    opportunity_data: Optional[OpportunityMetadata] = None

    # Delivery tracking
    is_delivered: bool = False
    delivered_channels: List[str] = field(default_factory=list)

    # Corroborating sources (for repeated coverage)
    corroborating_sources: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "canonical_url": self.canonical_url,
            "original_url": self.original_url,
            "title": self.title,
            "description": self.description,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "author": self.author,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "categories": self.categories,
            "matched_keywords": self.matched_keywords,
            "source_credibility_score": self.source_credibility_score,
            "recency_score": self.recency_score,
            "relevance_score": self.relevance_score,
            "importance_score": self.importance_score,
            "novelty_score": self.novelty_score,
            "combined_score": self.combined_score,
            "ranking_explanation": self.ranking_explanation,
            "summary": self.summary,
            "why_it_matters": self.why_it_matters,
            "technical_context": self.technical_context,
            "summary_method": self.summary_method,
            "content_hash": self.content_hash,
            "is_opportunity": self.is_opportunity,
            "opportunity_data": self.opportunity_data.to_dict() if self.opportunity_data else None,
            "is_delivered": self.is_delivered,
            "delivered_channels": self.delivered_channels,
            "corroborating_sources": self.corroborating_sources,
        }


@dataclass
class SourceConfig:
    """Configuration for an individual news or opportunity source."""
    id: str
    name: str
    url: str
    source_type: str = "rss"  # rss, atom, json
    categories: List[str] = field(default_factory=list)
    reliability_weight: float = 75.0  # Base reliability/credibility 0-100
    enabled: bool = True
    timeout_seconds: int = 15
    max_items: int = 30
    attribution: Optional[str] = None
    is_opportunity_source: bool = False


@dataclass
class DigestRun:
    """Metadata representing a single daily digest execution."""
    run_id: str
    digest_date: str  # YYYY-MM-DD
    coverage_start: datetime
    coverage_end: datetime
    status: str = "IN_PROGRESS"  # IN_PROGRESS, SUCCESS, PARTIAL_FAILURE, FAILED
    story_count: int = 0
    created_at: Optional[datetime] = None


@dataclass
class DeliveryResult:
    """Channel delivery attempt record."""
    channel: str  # 'telegram', 'email'
    success: bool
    status: str   # 'SUCCESS', 'FAILED', 'PENDING'
    error_message: Optional[str] = None
    message_id: Optional[str] = None
    timestamp: Optional[datetime] = None
