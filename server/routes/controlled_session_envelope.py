"""Proposal-only controlled-session envelope routes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.services.broker_connector_runtime import build_broker_connectors
from server.services.controlled_session_envelope import (
    CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    ControlledSessionAttestationRejected,
    ControlledSessionEnvelopeService,
)
from server.services.execution_gateway_verification import (
    ExecutionGatewayVerificationService,
)
from server.services.session_start_account_truth import (
    SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
    SessionStartAccountTruthService,
)

GatewayVerificationFingerprint = Annotated[
    str,
    Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"),
]
PerSymbolRuntimeLimit = Annotated[
    Decimal,
    Field(gt=0, max_digits=20, decimal_places=4),
]


class ControlledSessionEnvelopePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capital_evaluation_input_fingerprint: str = Field(min_length=64, max_length=64)
    prior_batch_reconciliation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    execution_gateway_verification_fingerprints: dict[
        str, GatewayVerificationFingerprint
    ] = Field(min_length=1, max_length=50)
    session_start_account_truth_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    per_symbol_runtime_limits: dict[str, PerSymbolRuntimeLimit] = Field(
        min_length=1,
        max_length=50,
    )
    order_ids: list[str] = Field(min_length=1, max_length=50)
    requested_start_at: datetime
    requested_expires_at: datetime


class ControlledSessionAttestationRequest(ControlledSessionEnvelopePreviewRequest):
    envelope_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_label: str = Field(min_length=1, max_length=128)
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    acknowledgement: Literal[
        "approve_exact_non_executing_session_envelope_for_review"
    ] = CONTROLLED_SESSION_ACKNOWLEDGEMENT


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-sessions",
        tags=["automation", "controlled-session", "session-envelope"],
    )

    @router.get("/status")
    async def get_controlled_session_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/envelopes/preview")
    async def preview_controlled_session_envelope(
        request: ControlledSessionEnvelopePreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview_envelope(
            capital_evaluation_input_fingerprint=(
                request.capital_evaluation_input_fingerprint
            ),
            prior_batch_reconciliation_fingerprint=(
                request.prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprints=(
                request.execution_gateway_verification_fingerprints
            ),
            session_start_account_truth_fingerprint=(
                request.session_start_account_truth_fingerprint
            ),
            per_symbol_runtime_limits=request.per_symbol_runtime_limits,
            order_ids=request.order_ids,
            requested_start_at=request.requested_start_at,
            requested_expires_at=request.requested_expires_at,
        )

    @router.post("/attestations")
    async def record_controlled_session_attestation(
        request: ControlledSessionAttestationRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record_attestation(
                capital_evaluation_input_fingerprint=(
                    request.capital_evaluation_input_fingerprint
                ),
                prior_batch_reconciliation_fingerprint=(
                    request.prior_batch_reconciliation_fingerprint
                ),
                execution_gateway_verification_fingerprints=(
                    request.execution_gateway_verification_fingerprints
                ),
                session_start_account_truth_fingerprint=(
                    request.session_start_account_truth_fingerprint
                ),
                per_symbol_runtime_limits=request.per_symbol_runtime_limits,
                order_ids=request.order_ids,
                requested_start_at=request.requested_start_at,
                requested_expires_at=request.requested_expires_at,
                envelope_fingerprint=request.envelope_fingerprint,
                operator_label=request.operator_label,
                operator_approval_id=request.operator_approval_id,
                acknowledgement=request.acknowledgement,
            )
        except ControlledSessionAttestationRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/attestations")
    async def list_controlled_session_attestations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_attestations(limit=limit)

    return router


def _service() -> ControlledSessionEnvelopeService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    return ControlledSessionEnvelopeService(
        db=state.db,
        connectors=build_broker_connectors(
            getattr(config, "broker_connectors", []) or []
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        trading_controls=getattr(state, "trading_controls", None),
        execution_gateway_verification_provider=(
            ExecutionGatewayVerificationService(
                db=state.db,
                gateways=getattr(state, "execution_gateways", []) or [],
            ).resolve
        ),
        session_start_account_truth_provider=(
            SessionStartAccountTruthService(
                db=state.db,
                account_truth_provider=(
                    lambda: build_latest_account_truth_promotion_evidence(
                        state,
                        max_age_seconds=(SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS),
                    )
                ),
            ).resolve
        ),
    )
