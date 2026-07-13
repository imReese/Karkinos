"""Human-created, evidence-bound AI research task audit routes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.capture import ContextCaptureAuditStore
from server.ai_runtime.evidence import (
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.ai_runtime.tasks import (
    HumanResearchTaskRequest,
    HumanResearchTaskReviewRequest,
    HumanResearchTaskService,
    ResearchTaskRejected,
    ResearchTaskReviewDecision,
    ResearchTaskStore,
)


class HumanResearchTaskCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    capture_id: str = Field(min_length=1, max_length=256)
    created_by: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    research_question: str = Field(min_length=1, max_length=4_000)
    confirmation: Literal["record_human_research_task_without_model_execution"]


class HumanResearchTaskReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    reviewed_by: str = Field(min_length=1, max_length=128)
    decision: ResearchTaskReviewDecision
    note: str = Field(min_length=1, max_length=4_000)
    confirmation: Literal["record_human_research_review_without_model_execution"]


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/ai/research-tasks", tags=["ai-research"])

    @router.post("")
    def create_research_task(payload: HumanResearchTaskCreatePayload) -> dict:
        try:
            result = _service(initialize=True).create(
                HumanResearchTaskRequest(
                    idempotency_key=payload.idempotency_key,
                    capture_id=payload.capture_id,
                    created_by=payload.created_by,
                    title=payload.title,
                    research_question=payload.research_question,
                    confirmation=payload.confirmation,
                )
            )
            return result.to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("")
    def list_research_tasks(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        try:
            tasks = _service(initialize=False).list(limit=limit)
        except Exception as exc:
            _raise_domain_http_error(exc)
        return {
            "schema_version": "karkinos.ai.human_research_task_list.v1",
            "tasks": [task.to_dict() for task in tasks],
            "model_execution_enabled": False,
            "workflow_started": False,
            "authority_effect": "none",
        }

    @router.get("/{task_id}")
    def get_research_task(task_id: str) -> dict:
        try:
            return _service(initialize=False).get(task_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.post("/{task_id}/reviews")
    def review_research_task(
        task_id: str,
        payload: HumanResearchTaskReviewPayload,
    ) -> dict:
        try:
            result = _service(initialize=True).review(
                task_id,
                HumanResearchTaskReviewRequest(
                    idempotency_key=payload.idempotency_key,
                    reviewed_by=payload.reviewed_by,
                    decision=payload.decision,
                    note=payload.note,
                    confirmation=payload.confirmation,
                ),
            )
            return result.to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    @router.get("/{task_id}/replay")
    def replay_research_task(task_id: str) -> dict:
        try:
            return _service(initialize=False).replay(task_id).to_dict()
        except Exception as exc:
            _raise_domain_http_error(exc)

    return router


def build_human_research_task_service(
    state,
    *,
    initialize: bool,
) -> HumanResearchTaskService:
    """Build the model-free research task audit service on application SQLite."""
    db_path = _database_path(state.db)
    evidence_repository = CanonicalEvidenceRepository(db_path)
    context_store = AiAuditStore(db_path)
    capture_store = ContextCaptureAuditStore(db_path)
    task_store = ResearchTaskStore(db_path)
    if initialize:
        evidence_repository.init()
        context_store.init()
        capture_store.init()
        task_store.init()
    return HumanResearchTaskService(
        evidence_repository=evidence_repository,
        context_store=context_store,
        capture_store=capture_store,
        task_store=task_store,
        now=_utc_now,
    )


def _service(*, initialize: bool) -> HumanResearchTaskService:
    from server.app import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return build_human_research_task_service(state, initialize=initialize)


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ResearchTaskRejected("database path is unavailable")
    return Path(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_domain_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, (IdempotencyConflict, EvidenceIdentityMismatch)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ResearchTaskRejected):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
