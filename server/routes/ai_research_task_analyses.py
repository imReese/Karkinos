"""Explicit offline fixture analysis routes for accepted research tasks."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.store import IdempotencyConflict
from server.ai_runtime.task_analysis import (
    HumanFixtureAnalysisRequest,
    HumanResearchTaskFixtureAnalysisService,
    ResearchTaskAnalysisRejected,
)
from server.composition.ai_application_services import (
    build_human_fixture_analysis_service,
)


class HumanFixtureAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=128)
    confirmation: Literal["run_deterministic_fixture_analysis_without_external_model"]


def create_router() -> APIRouter:
    router = APIRouter(tags=["ai-research"])

    @router.post("/api/ai/research-tasks/{task_id}/fixture-analyses")
    def start_fixture_analysis(
        task_id: str,
        payload: HumanFixtureAnalysisPayload,
    ) -> dict:
        try:
            result = _service(initialize=True).start(
                HumanFixtureAnalysisRequest(
                    task_id=task_id,
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    confirmation=payload.confirmation,
                )
            )
            return result.to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/research-task-analyses")
    def list_fixture_analyses(
        task_id: str | None = Query(default=None, min_length=1, max_length=256),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            analyses = _service(initialize=False).list(
                task_id=task_id,
                limit=limit,
            )
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": "karkinos.ai.task_fixture_analysis_list.v1",
            "analyses": [item.to_dict() for item in analyses],
            "fixture_only": True,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "authority_effect": "none",
        }

    @router.get("/api/ai/research-task-analyses/{analysis_id}")
    def get_fixture_analysis(analysis_id: str) -> dict:
        try:
            return _service(initialize=False).get(analysis_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/api/ai/research-task-analyses/{analysis_id}/replay")
    def replay_fixture_analysis(analysis_id: str) -> dict:
        try:
            return _service(initialize=False).replay(analysis_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def _service(*, initialize: bool) -> HumanResearchTaskFixtureAnalysisService:
    from server.dependencies import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_fixture_analysis_service(state, initialize=initialize)


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ResearchTaskAnalysisRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
