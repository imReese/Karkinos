"""Human-only routes for reviewed external-research memory promotion."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.external_reviewed_memory import (
    ExternalReviewedMemoryPromotionRejected,
    ExternalReviewedMemoryPromotionRequest,
    ExternalReviewedMemoryPromotionService,
    ExternalReviewedMemoryRevocationRequest,
    ExternalReviewedMemoryStore,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.routes.ai_external_analysis_reviews import (
    build_human_external_analysis_review_service,
)


class ExternalReviewedMemoryPromotionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    promoted_by: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=4_000)
    confirmation: Literal[
        "promote_reviewed_external_research_to_revocable_historical_memory_"
        "without_current_fact_decision_or_trade_authority"
    ]


class ExternalReviewedMemoryRevocationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    revoked_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=4_000)
    confirmation: Literal[
        "revoke_external_research_memory_recall_without_deleting_history_or_"
        "changing_trade_authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/external-analysis-reviews/{review_id}/memory-promotions")
    def promote_external_reviewed_memory(
        review_id: str,
        payload: ExternalReviewedMemoryPromotionPayload,
    ) -> dict:
        try:
            return (
                _service(initialize=True)
                .promote(
                    review_id,
                    ExternalReviewedMemoryPromotionRequest(
                        **payload.model_dump(),
                    ),
                )
                .to_dict()
            )
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.post(
        "/api/ai/external-reviewed-memory-promotions/{promotion_id}/revocations"
    )
    def revoke_external_reviewed_memory(
        promotion_id: str,
        payload: ExternalReviewedMemoryRevocationPayload,
    ) -> dict:
        try:
            return (
                _service(initialize=True)
                .revoke(
                    promotion_id,
                    ExternalReviewedMemoryRevocationRequest(
                        **payload.model_dump(),
                    ),
                )
                .to_dict()
            )
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-reviewed-memory-promotions")
    def list_external_reviewed_memory(
        review_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=256,
        ),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            results = _service(initialize=False).list(
                review_id=review_id,
                limit=limit,
            )
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": "karkinos.ai.external_reviewed_memory_list.v1",
            "promotions": [item.to_dict() for item in results],
            "explicit_human_promotion_required": True,
            "automatic_recall_enabled": False,
            "legacy_retrieval_contract_modified": False,
            "provider_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/external-reviewed-memory-promotions/{promotion_id}")
    def get_external_reviewed_memory(promotion_id: str) -> dict:
        try:
            return _service(initialize=False).get(promotion_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-reviewed-memory-promotions/{promotion_id}/replay")
    def replay_external_reviewed_memory(promotion_id: str) -> dict:
        try:
            return _service(initialize=False).replay(promotion_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def build_external_reviewed_memory_promotion_service(
    state,
    *,
    initialize: bool,
) -> ExternalReviewedMemoryPromotionService:
    """Build the local-only promotion edge without loading model credentials."""
    db_path = _database_path(state.db)
    review_service = build_human_external_analysis_review_service(
        state,
        initialize=initialize,
    )
    promotion_store = ExternalReviewedMemoryStore(db_path)
    if initialize:
        promotion_store.init()
    return ExternalReviewedMemoryPromotionService(
        review_service=review_service,
        ai_store=AiAuditStore(db_path),
        promotion_store=promotion_store,
        now=_utc_now,
    )


def _service(*, initialize: bool) -> ExternalReviewedMemoryPromotionService:
    from server.app import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_external_reviewed_memory_promotion_service(
        state,
        initialize=initialize,
    )


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ExternalReviewedMemoryPromotionRejected("database path is unavailable")
    return Path(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ExternalReviewedMemoryPromotionRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
