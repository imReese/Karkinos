"""Human-only review routes for deterministic fixture analysis artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.analysis_reviews import (
    AnalysisReviewDecision,
    AnalysisReviewRejected,
    AnalysisReviewStore,
    HumanAnalysisReviewRequest,
    HumanAnalysisReviewService,
)
from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.store import IdempotencyConflict
from server.routes.ai_research_task_analyses import (
    build_human_fixture_analysis_service,
)


class HumanAnalysisReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    reviewed_by: str = Field(min_length=1, max_length=128)
    decision: Literal[
        "accept_as_reviewed_memory",
        "request_revision",
        "reject",
    ]
    note: str = Field(min_length=1, max_length=2_000)
    confirmation: Literal[
        "record_fixture_analysis_review_without_decision_or_execution_authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/research-task-analyses/{analysis_id}/reviews")
    def review_fixture_analysis(
        analysis_id: str,
        payload: HumanAnalysisReviewPayload,
    ) -> dict:
        try:
            result = _service(initialize=True).review(
                analysis_id,
                HumanAnalysisReviewRequest(
                    idempotency_key=payload.idempotency_key,
                    reviewed_by=payload.reviewed_by,
                    decision=AnalysisReviewDecision(payload.decision),
                    note=payload.note,
                    confirmation=payload.confirmation,
                ),
            )
            return result.to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/research-task-analysis-reviews")
    def list_fixture_analysis_reviews(
        analysis_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=256,
        ),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            reviews = _service(initialize=False).list(
                analysis_id=analysis_id,
                limit=limit,
            )
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": "karkinos.ai.fixture_analysis_review_list.v1",
            "reviews": [item.to_dict() for item in reviews],
            "fixture_only": True,
            "research_memory_only": True,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/research-task-analysis-reviews/{review_id}")
    def get_fixture_analysis_review(review_id: str) -> dict:
        try:
            return _service(initialize=False).get(review_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/research-task-analysis-reviews/{review_id}/replay")
    def replay_fixture_analysis_review(review_id: str) -> dict:
        try:
            return _service(initialize=False).replay(review_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def build_human_analysis_review_service(
    state,
    *,
    initialize: bool,
) -> HumanAnalysisReviewService:
    """Build the non-authoritative, human-only analysis review boundary."""
    db_path = _database_path(state.db)
    analysis_service = build_human_fixture_analysis_service(
        state,
        initialize=initialize,
    )
    review_store = AnalysisReviewStore(db_path)
    if initialize:
        review_store.init()
    return HumanAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=_utc_now,
    )


def _service(*, initialize: bool) -> HumanAnalysisReviewService:
    from server.app import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_analysis_review_service(state, initialize=initialize)


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise AnalysisReviewRejected("database path is unavailable")
    return Path(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, AnalysisReviewRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
