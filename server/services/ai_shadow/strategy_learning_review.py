"""Persisted-only strategy learning queue derived from human outcome reviews.

Backward-compatible facade for server.services.ai_shadow.learning_review.
"""

from __future__ import annotations

from server.services.ai_shadow.learning_review import (
    STRATEGY_LEARNING_REVIEW_SCHEMA_VERSION,
    StrategyLearningReviewService,
)

__all__ = [
    "STRATEGY_LEARNING_REVIEW_SCHEMA_VERSION",
    "StrategyLearningReviewService",
]
