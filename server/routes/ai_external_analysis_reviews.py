"""Human-only review routes for external evidence-bound AI analyses."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisQualityRubric,
    ExternalAnalysisReviewDecision,
    ExternalAnalysisReviewRejected,
    HumanExternalAnalysisReviewRequest,
    HumanExternalAnalysisReviewService,
    ProviderPricingSnapshot,
)
from server.ai_runtime.store import IdempotencyConflict
from server.composition.ai_application_services import (
    build_human_external_analysis_review_service,
)
from server.contracts.http.ai_reviews import (
    ExternalAnalysisQualityRubricPayload,
    ProviderPricingSnapshotPayload,
)


class HumanExternalAnalysisReviewPayload(BaseModel):
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
        "record_external_analysis_review_without_memory_decision_or_trade_" "authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/external-memory-informed-analyses/{analysis_id}/reviews")
    def review_external_analysis(
        analysis_id: str,
        payload: HumanExternalAnalysisReviewPayload,
    ) -> dict:
        try:
            pricing = payload.pricing_snapshot
            result = _service(initialize=True).review(
                analysis_id,
                HumanExternalAnalysisReviewRequest(
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
                    pricing_unavailable_reason=(payload.pricing_unavailable_reason),
                    confirmation=payload.confirmation,
                ),
            )
            return result.to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-analysis-reviews")
    def list_external_analysis_reviews(
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
            "schema_version": "karkinos.ai.external_analysis_review_list.v1",
            "reviews": [item.to_dict() for item in reviews],
            "human_review_only": True,
            "review_external_model_invocation_count": 0,
            "memory_recall_eligible": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/external-analysis-reviews/{review_id}")
    def get_external_analysis_review(review_id: str) -> dict:
        try:
            return _service(initialize=False).get(review_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-analysis-reviews/{review_id}/replay")
    def replay_external_analysis_review(review_id: str) -> dict:
        try:
            return _service(initialize=False).replay(review_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def _service(*, initialize: bool) -> HumanExternalAnalysisReviewService:
    from server.dependencies import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_external_analysis_review_service(
        state,
        initialize=initialize,
    )


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ExternalAnalysisReviewRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
