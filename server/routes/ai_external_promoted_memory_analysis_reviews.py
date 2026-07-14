"""Human-only review routes for promoted-memory external analyses."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisQualityRubric,
    ExternalAnalysisReviewDecision,
    ProviderPricingSnapshot,
)
from server.ai_runtime.external_promoted_memory_analysis_reviews import (
    ExternalPromotedMemoryAnalysisReviewRejected,
    ExternalPromotedMemoryAnalysisReviewStore,
    HumanExternalPromotedMemoryAnalysisReviewRequest,
    HumanExternalPromotedMemoryAnalysisReviewService,
)
from server.ai_runtime.store import IdempotencyConflict
from server.routes.ai_external_analysis_reviews import (
    ExternalAnalysisQualityRubricPayload,
    ProviderPricingSnapshotPayload,
)
from server.routes.ai_external_promoted_memory_analyses import (
    build_human_external_promoted_memory_analysis_service,
)


class HumanExternalPromotedMemoryAnalysisReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    reviewed_by: str = Field(min_length=1, max_length=128)
    decision: Literal[
        "accept_as_reviewed_research",
        "request_revision",
        "reject",
    ]
    note: str = Field(min_length=1, max_length=4_000)
    quality_rubric: ExternalAnalysisQualityRubricPayload
    factual_error_count: int = Field(ge=0, le=10_000)
    unsupported_claim_count: int = Field(ge=0, le=10_000)
    pricing_snapshot: ProviderPricingSnapshotPayload | None = None
    pricing_unavailable_reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_000,
    )
    confirmation: Literal[
        "record_external_promoted_memory_analysis_review_without_memory_"
        "decision_or_trade_authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/external-promoted-memory-analyses/{analysis_id}/reviews")
    def review_external_promoted_memory_analysis(
        analysis_id: str,
        payload: HumanExternalPromotedMemoryAnalysisReviewPayload,
    ) -> dict:
        try:
            pricing = payload.pricing_snapshot
            result = _service(initialize=True).review(
                analysis_id,
                HumanExternalPromotedMemoryAnalysisReviewRequest(
                    idempotency_key=payload.idempotency_key,
                    reviewed_by=payload.reviewed_by,
                    decision=ExternalAnalysisReviewDecision(payload.decision),
                    note=payload.note,
                    quality_rubric=ExternalAnalysisQualityRubric(
                        **payload.quality_rubric.model_dump()
                    ),
                    factual_error_count=payload.factual_error_count,
                    unsupported_claim_count=payload.unsupported_claim_count,
                    pricing_snapshot=(
                        ProviderPricingSnapshot(**pricing.model_dump())
                        if pricing is not None
                        else None
                    ),
                    pricing_unavailable_reason=payload.pricing_unavailable_reason,
                    confirmation=payload.confirmation,
                ),
            )
            return result.to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-promoted-memory-analysis-reviews")
    def list_external_promoted_memory_analysis_reviews(
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
            "schema_version": (
                "karkinos.ai.external_promoted_memory_analysis_review_list.v1"
            ),
            "reviews": [item.to_dict() for item in reviews],
            "human_review_only": True,
            "review_external_model_invocation_count": 0,
            "memory_artifact_created": False,
            "memory_recall_eligible": False,
            "automatic_memory_promotion_enabled": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/external-promoted-memory-analysis-reviews/{review_id}")
    def get_external_promoted_memory_analysis_review(review_id: str) -> dict:
        try:
            return _service(initialize=False).get(review_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-promoted-memory-analysis-reviews/{review_id}/replay")
    def replay_external_promoted_memory_analysis_review(review_id: str) -> dict:
        try:
            return _service(initialize=False).replay(review_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def build_human_external_promoted_memory_analysis_review_service(
    state,
    *,
    initialize: bool,
) -> HumanExternalPromotedMemoryAnalysisReviewService:
    """Build a local review edge without loading provider credentials."""
    db_path = _database_path(state.db)
    analysis_service = build_human_external_promoted_memory_analysis_service(
        state,
        initialize=initialize,
    )
    review_store = ExternalPromotedMemoryAnalysisReviewStore(db_path)
    if initialize:
        review_store.init()
    return HumanExternalPromotedMemoryAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=_utc_now,
    )


def _service(
    *,
    initialize: bool,
) -> HumanExternalPromotedMemoryAnalysisReviewService:
    from server.app import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_external_promoted_memory_analysis_review_service(
        state,
        initialize=initialize,
    )


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ExternalPromotedMemoryAnalysisReviewRejected(
            "database path is unavailable"
        )
    return Path(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ExternalPromotedMemoryAnalysisReviewRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
