"""Persisted-only strategy learning review routes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server.services.decision_outcome_review import (
    DecisionOutcomeReviewService,
    DecisionOutcomeReviewStore,
)
from server.services.strategy_learning_review import StrategyLearningReviewService


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/strategy-learning",
        tags=["strategy-learning", "review", "research"],
    )

    @router.get("/review-queue")
    async def get_strategy_learning_review_queue(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        """Project reviewed learning evidence without provider or write effects."""

        from server.app import get_app_state

        try:
            service = build_strategy_learning_review_service(get_app_state())
            return service.build(limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router


def build_strategy_learning_review_service(
    state: Any,
) -> StrategyLearningReviewService:
    db = getattr(state, "db", None)
    path = getattr(db, "_path", None)
    if db is None or path is None:
        raise ValueError("database is not initialized")
    store = DecisionOutcomeReviewStore(Path(path))
    review_service = DecisionOutcomeReviewService(
        db=db,
        store=store,
        now=lambda: datetime.now(timezone.utc).isoformat(),
    )
    return StrategyLearningReviewService(
        review_store=store,
        review_service=review_service,
    )


__all__ = [
    "build_strategy_learning_review_service",
    "create_router",
]
