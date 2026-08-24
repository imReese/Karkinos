"""Explicit retrieval of promoted external reviewed-research memory."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.external_reviewed_memory_retrieval import (
    ExternalReviewedMemoryRetrievalRejected,
    HumanExternalReviewedMemoryRetrievalRequest,
    HumanExternalReviewedMemoryRetrievalService,
)
from server.ai_runtime.store import IdempotencyConflict
from server.composition.ai_application_services import (
    build_human_external_reviewed_memory_retrieval_service,
)


class HumanExternalReviewedMemoryRetrievalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=2_000)
    current_context_snapshot_id: str = Field(min_length=1, max_length=256)
    promotion_ids: list[str] = Field(min_length=1, max_length=20)
    confirmation: Literal[
        "retrieve_promoted_external_reviewed_memory_with_current_canonical_"
        "evidence_as_non_authoritative_research_input"
    ]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/external-reviewed-memory-retrievals")
    def start_external_reviewed_memory_retrieval(
        payload: HumanExternalReviewedMemoryRetrievalPayload,
    ) -> dict:
        try:
            return (
                _service(initialize=True)
                .start(
                    HumanExternalReviewedMemoryRetrievalRequest(
                        idempotency_key=payload.idempotency_key,
                        requested_by=payload.requested_by,
                        purpose=payload.purpose,
                        current_context_snapshot_id=(
                            payload.current_context_snapshot_id
                        ),
                        promotion_ids=tuple(payload.promotion_ids),
                        confirmation=payload.confirmation,
                    )
                )
                .to_dict()
            )
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-reviewed-memory-retrievals")
    def list_external_reviewed_memory_retrievals(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            retrievals = _service(initialize=False).list(limit=limit)
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": (
                "karkinos.ai.external_reviewed_memory_retrieval_list.v1"
            ),
            "retrievals": [item.to_dict() for item in retrievals],
            "explicit_human_start_required": True,
            "automatic_recall_enabled": False,
            "legacy_retrieval_v1_modified": False,
            "external_model_consumption_enabled": False,
            "provider_tool_registered": False,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/external-reviewed-memory-retrievals/{retrieval_id}")
    def get_external_reviewed_memory_retrieval(retrieval_id: str) -> dict:
        try:
            return _service(initialize=False).get(retrieval_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-reviewed-memory-retrievals/{retrieval_id}/replay")
    def replay_external_reviewed_memory_retrieval(retrieval_id: str) -> dict:
        try:
            return _service(initialize=False).replay(retrieval_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def _service(*, initialize: bool) -> HumanExternalReviewedMemoryRetrievalService:
    from server.dependencies import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_external_reviewed_memory_retrieval_service(
        state,
        initialize=initialize,
    )


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ExternalReviewedMemoryRetrievalRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
