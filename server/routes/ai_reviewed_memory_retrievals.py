"""Explicit, read-only research-memory retrieval routes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.analysis_reviews import (
    AnalysisReviewStore,
    HumanAnalysisReviewService,
)
from server.ai_runtime.evidence import (
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from server.ai_runtime.memory_retrieval import (
    HumanReviewedMemoryRetrievalRequest,
    HumanReviewedMemoryRetrievalService,
    ReviewedMemoryRetrievalRejected,
    ReviewedMemoryRetrievalStore,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.routes.ai_research_task_analyses import (
    build_human_fixture_analysis_service,
)


class HumanReviewedMemoryRetrievalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=2_000)
    current_context_snapshot_id: str = Field(min_length=1, max_length=256)
    review_ids: list[str] = Field(min_length=1, max_length=20)
    confirmation: Literal[
        "retrieve_reviewed_memory_as_non_authoritative_research_input"
    ]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/reviewed-memory-retrievals")
    def start_reviewed_memory_retrieval(
        payload: HumanReviewedMemoryRetrievalPayload,
    ) -> dict:
        try:
            result = _service(initialize=True).start(
                HumanReviewedMemoryRetrievalRequest(
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    purpose=payload.purpose,
                    current_context_snapshot_id=(payload.current_context_snapshot_id),
                    review_ids=tuple(payload.review_ids),
                    confirmation=payload.confirmation,
                )
            )
            return result.to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/reviewed-memory-retrievals")
    def list_reviewed_memory_retrievals(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            retrievals = _service(initialize=False).list(limit=limit)
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": "karkinos.ai.reviewed_memory_retrieval_list.v1",
            "retrievals": [item.to_dict() for item in retrievals],
            "automatic_recall_enabled": False,
            "provider_tool_registered": False,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "memory_is_account_fact": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/reviewed-memory-retrievals/{retrieval_id}")
    def get_reviewed_memory_retrieval(retrieval_id: str) -> dict:
        try:
            return _service(initialize=False).get(retrieval_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/reviewed-memory-retrievals/{retrieval_id}/replay")
    def replay_reviewed_memory_retrieval(retrieval_id: str) -> dict:
        try:
            return _service(initialize=False).replay(retrieval_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def build_human_reviewed_memory_retrieval_service(
    state,
    *,
    initialize: bool,
) -> HumanReviewedMemoryRetrievalService:
    """Build the explicit boundary without registering a provider or AI tool."""
    db_path = _database_path(state.db)
    analysis_service = build_human_fixture_analysis_service(
        state,
        initialize=initialize,
    )
    review_store = AnalysisReviewStore(db_path)
    retrieval_store = ReviewedMemoryRetrievalStore(db_path)
    if initialize:
        review_store.init()
        retrieval_store.init()
    review_service = HumanAnalysisReviewService(
        analysis_service=analysis_service,
        review_store=review_store,
        now=_utc_now,
    )
    return HumanReviewedMemoryRetrievalService(
        review_service=review_service,
        analysis_service=analysis_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        retrieval_store=retrieval_store,
        now=_utc_now,
    )


def _service(*, initialize: bool) -> HumanReviewedMemoryRetrievalService:
    from server.app import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_reviewed_memory_retrieval_service(
        state,
        initialize=initialize,
    )


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ReviewedMemoryRetrievalRejected("database path is unavailable")
    return Path(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ReviewedMemoryRetrievalRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
