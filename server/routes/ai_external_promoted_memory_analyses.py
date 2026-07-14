"""Explicit model analysis of versioned promoted-memory retrievals."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.evidence import (
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from server.ai_runtime.external_memory_informed_analysis import (
    ExternalMemoryAnalysisRejected,
    HumanExternalMemoryAnalysisRequest,
    HumanExternalMemoryAnalysisService,
)
from server.ai_runtime.external_promoted_memory_analysis import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION,
    ExternalPromotedMemoryAnalysisStore,
    HumanExternalPromotedMemoryAnalysisService,
)
from server.ai_runtime.provider_connectivity import (
    ConnectivityConfigurationError,
    load_provider_connectivity_settings,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.bootstrap import resolve_config_path
from server.routes.ai_external_reviewed_memory_retrievals import (
    build_human_external_reviewed_memory_retrieval_service,
)


class HumanExternalPromotedMemoryAnalysisPayload(BaseModel):
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

    @router.post(
        "/api/ai/external-reviewed-memory-retrievals/{retrieval_id}/"
        "external-analyses"
    )
    async def start_external_promoted_memory_analysis(
        retrieval_id: str,
        payload: HumanExternalPromotedMemoryAnalysisPayload,
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
                    schema_version=(EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION),
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
        }[result.analysis.workflow.status.value]
        return JSONResponse(status_code=status_code, content=result.to_dict())

    @router.get("/api/ai/external-promoted-memory-analyses")
    def list_external_promoted_memory_analyses(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            analyses = _service(initialize=False).list(limit=limit)
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": ("karkinos.ai.external_promoted_memory_analysis_list.v1"),
            "analyses": [item.to_dict() for item in analyses],
            "memory_source": "promoted_external_reviewed_memory",
            "explicit_human_start_required": True,
            "automatic_recall_enabled": False,
            "provider_side_tools_enabled": False,
            "model_reasoning_mode_preserved": True,
            "reasoning_content_persisted": False,
            "requires_human_review": True,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }

    @router.get("/api/ai/external-promoted-memory-analyses/{analysis_id}")
    def get_external_promoted_memory_analysis(analysis_id: str) -> dict:
        try:
            return _service(initialize=False).get(analysis_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/external-promoted-memory-analyses/{analysis_id}/replay")
    def replay_external_promoted_memory_analysis(analysis_id: str) -> dict:
        try:
            return _service(initialize=False).replay(analysis_id)
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def build_human_external_promoted_memory_analysis_service(
    state,
    *,
    initialize: bool,
) -> HumanExternalPromotedMemoryAnalysisService:
    """Build a lazy external edge over the versioned promoted-memory source."""
    db_path = _database_path(state.db)
    retrieval_service = build_human_external_reviewed_memory_retrieval_service(
        state,
        initialize=initialize,
    )
    store = ExternalPromotedMemoryAnalysisStore(db_path)
    if initialize:
        store.init()
    analysis_service = HumanExternalMemoryAnalysisService(
        settings_loader=lambda: load_provider_connectivity_settings(
            resolve_config_path()
        ),
        retrieval_service=retrieval_service,
        ai_store=AiAuditStore(db_path),
        evidence_repository=CanonicalEvidenceRepository(db_path),
        analysis_store=store,
        now=_utc_now,
    )
    return HumanExternalPromotedMemoryAnalysisService(
        analysis_service=analysis_service,
        retrieval_service=retrieval_service,
    )


def _service(*, initialize: bool) -> HumanExternalPromotedMemoryAnalysisService:
    from server.app import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_external_promoted_memory_analysis_service(
        state,
        initialize=initialize,
    )


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ConnectivityConfigurationError("database path is unavailable")
    return Path(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
