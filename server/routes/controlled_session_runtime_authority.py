"""Signed runtime-session issuance and one-way revocation routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
    ControlledSessionRuntimeAuthorityRejected,
    ControlledSessionRuntimeAuthorityService,
)


class ControlledSessionIssuancePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


class ControlledSessionIssuanceRequest(ControlledSessionIssuancePreviewRequest):
    issuance_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_proof_signature_base64: str = Field(min_length=80, max_length=128)
    acknowledgement: Literal["issue_exact_expiring_non_broker_controlled_session"] = (
        CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT
    )


class ControlledSessionRevocationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: Literal[
        "manual_operator_stop",
        "end_of_strategy_window",
        "operational_concern",
        "risk_review",
        "account_or_reconciliation_concern",
    ]


class ControlledSessionRevocationRequest(ControlledSessionRevocationPreviewRequest):
    revocation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_proof_signature_base64: str = Field(min_length=80, max_length=128)
    acknowledgement: Literal["revoke_exact_controlled_session_no_auto_resume"] = (
        CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT
    )


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-sessions/runtime-authority",
        tags=["automation", "controlled-session", "runtime-authority"],
    )

    @router.get("/status")
    async def get_controlled_session_runtime_authority_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/issuance/preview")
    async def preview_controlled_session_issuance(
        request: ControlledSessionIssuancePreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview_issuance(reservation_id=request.reservation_id)

    @router.post("/sessions")
    async def issue_controlled_session(
        request: ControlledSessionIssuanceRequest,
    ) -> dict[str, Any]:
        try:
            return _service().issue(
                reservation_id=request.reservation_id,
                issuance_fingerprint=request.issuance_fingerprint,
                operator_approval_id=request.operator_approval_id,
                operator_proof_signature_base64=(
                    request.operator_proof_signature_base64
                ),
                acknowledgement=request.acknowledgement,
            )
        except ControlledSessionRuntimeAuthorityRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/sessions")
    async def list_controlled_sessions(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_sessions(limit=limit)

    @router.get("/sessions/{session_id}")
    async def resolve_controlled_session(session_id: str) -> dict[str, Any]:
        return _service().resolve_current(session_id)

    @router.post("/sessions/{session_id}/revocation/preview")
    async def preview_controlled_session_revocation(
        session_id: str,
        request: ControlledSessionRevocationPreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview_revocation(
            session_id=session_id,
            reason_code=request.reason_code,
        )

    @router.post("/sessions/{session_id}/revocations")
    async def revoke_controlled_session(
        session_id: str,
        request: ControlledSessionRevocationRequest,
    ) -> dict[str, Any]:
        try:
            return _service().revoke(
                session_id=session_id,
                reason_code=request.reason_code,
                revocation_fingerprint=request.revocation_fingerprint,
                operator_approval_id=request.operator_approval_id,
                operator_proof_signature_base64=(
                    request.operator_proof_signature_base64
                ),
                acknowledgement=request.acknowledgement,
            )
        except ControlledSessionRuntimeAuthorityRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/revocations")
    async def list_controlled_session_revocations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_revocations(limit=limit)

    return router


def _service() -> ControlledSessionRuntimeAuthorityService:
    from server.app import get_app_state
    from server.routes.controlled_session_budget_reservation import (
        _service as controlled_session_budget_reservation_service,
    )
    from server.routes.controlled_session_envelope import (
        _service as controlled_session_envelope_service,
    )

    state = get_app_state()
    config = getattr(state, "config", None)
    return ControlledSessionRuntimeAuthorityService(
        db=state.db,
        reservation_provider=controlled_session_budget_reservation_service().resolve,
        attestation_provider=controlled_session_envelope_service().resolve_attestation,
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )
