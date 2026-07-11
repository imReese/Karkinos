"""Short-lived, non-authorizing session-start Account Truth routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.services.session_start_account_truth import (
    SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
    SessionStartAccountTruthRejected,
    SessionStartAccountTruthService,
)


class SessionStartAccountTruthPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_connector_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    account_alias: str = Field(
        min_length=1,
        max_length=128,
    )


class SessionStartAccountTruthRecordRequest(SessionStartAccountTruthPreviewRequest):
    account_truth_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    acknowledgement: Literal["record_non_authorizing_session_start_account_truth"] = (
        SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT
    )


class SessionStartAccountTruthResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_truth_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/session-start-account-truth",
        tags=["automation", "controlled-session", "account-truth"],
    )

    @router.get("/status")
    async def get_session_start_account_truth_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/preview")
    async def preview_session_start_account_truth(
        request: SessionStartAccountTruthPreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview(
            evidence_connector_id=request.evidence_connector_id,
            account_alias=request.account_alias,
        )

    @router.post("/records")
    async def record_session_start_account_truth(
        request: SessionStartAccountTruthRecordRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record(
                evidence_connector_id=request.evidence_connector_id,
                account_alias=request.account_alias,
                account_truth_fingerprint=request.account_truth_fingerprint,
                acknowledgement=request.acknowledgement,
            )
        except SessionStartAccountTruthRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.post("/resolve")
    async def resolve_session_start_account_truth(
        request: SessionStartAccountTruthResolveRequest,
    ) -> dict[str, Any]:
        return _service().resolve(request.account_truth_fingerprint)

    @router.get("/records")
    async def list_session_start_account_truth_records(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_records(limit=limit)

    return router


def _service() -> SessionStartAccountTruthService:
    from server.app import get_app_state

    state = get_app_state()
    return SessionStartAccountTruthService(
        db=state.db,
        account_truth_provider=(
            lambda: build_latest_account_truth_promotion_evidence(
                state,
                max_age_seconds=SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
            )
        ),
    )
