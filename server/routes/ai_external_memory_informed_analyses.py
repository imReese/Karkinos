"""Explicit external-provider routes for reviewed memory and current evidence."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.external_memory_informed_analysis import (
    ExternalMemoryAnalysisRejected,
    HumanExternalMemoryAnalysisRequest,
    HumanExternalMemoryAnalysisService,
)
from server.ai_runtime.provider_connectivity import ConnectivityConfigurationError
from server.ai_runtime.store import IdempotencyConflict
from server.composition.ai_application_services import (
    build_human_external_memory_analysis_service,
)


class HumanExternalMemoryAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=128)
    research_question: str = Field(min_length=1, max_length=4_000)
    confirmation: Literal[
        "send_reviewed_memory_and_current_canonical_evidence_to_configured_"
        "external_model_for_claim_debate_report_without_trade_authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/reviewed-memory-retrievals/{retrieval_id}/external-analyses")
    async def start_external_memory_analysis(
        retrieval_id: str,
        payload: HumanExternalMemoryAnalysisPayload,
    ) -> JSONResponse:
        try:
            result = await asyncio.to_thread(
                _service(initialize=True).start,
                HumanExternalMemoryAnalysisRequest(
                    retrieval_id=retrieval_id,
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    research_question=payload.research_question,
                    confirmation=payload.confirmation,
                ),
            )
        except Exception as exc:
            _raise_domain_http_error(exc)
        status_code = {
            "completed": 200,
            "pending": 202,
            "running": 202,
            "partial": 409,
            "blocked": 409,
            "failed": 502,
        }[result.workflow.status.value]
        return JSONResponse(status_code=status_code, content=result.to_dict())

    @router.get("/api/ai/external-memory-informed-analyses")
    def list_external_memory_analyses(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            analyses = _service(initialize=False).list(limit=limit)
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": "karkinos.ai.external_memory_analysis_list.v1",
            "analyses": [item.to_dict() for item in analyses],
            "explicit_human_start_required": True,
            "automatic_recall_enabled": False,
            "provider_side_tools_enabled": False,
            "memory_input_is_current_fact": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/external-memory-informed-analyses/{analysis_id}")
    def get_external_memory_analysis(analysis_id: str) -> dict:
        try:
            return _service(initialize=False).get(analysis_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-memory-informed-analyses/{analysis_id}/replay")
    def replay_external_memory_analysis(analysis_id: str) -> dict:
        try:
            return _service(initialize=False).replay(analysis_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def _service(*, initialize: bool) -> HumanExternalMemoryAnalysisService:
    from server.dependencies import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_external_memory_analysis_service(
        state,
        initialize=initialize,
    )


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ExternalMemoryAnalysisRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ConnectivityConfigurationError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
