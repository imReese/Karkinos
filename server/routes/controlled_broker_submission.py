"""One-shot, final-signature controlled broker submission routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
    ControlledBrokerSubmissionRejected,
    ControlledBrokerSubmissionService,
)
from server.services.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
    ControlledSubmissionReconciliationClearanceRejected,
    ControlledSubmissionReconciliationClearanceService,
)


class ControlledBrokerSubmissionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    release_evidence_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


class ControlledBrokerSubmissionRequest(ControlledBrokerSubmissionPreviewRequest):
    submit_fingerprint: str = Field(
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
    acknowledgement: Literal["submit_one_exact_manually_confirmed_order_once"] = (
        CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT
    )


class ControlledBrokerRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_fingerprint: str = Field(
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
    acknowledgement: Literal["query_exact_unknown_submission_once_without_resubmit"] = (
        CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT
    )


class ControlledSubmissionClearancePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_run_id: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$",
    )


class ControlledSubmissionClearanceRequest(ControlledSubmissionClearancePreviewRequest):
    clearance_fingerprint: str = Field(
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
    acknowledgement: Literal[
        "clear_exact_terminal_outcome_without_automatic_ledger_mutation"
    ] = CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-broker-submission",
        tags=["automation", "controlled-bridge", "broker-submission"],
    )

    @router.get("/status")
    async def get_controlled_broker_submission_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/orders/{order_id}/submission/preview")
    async def preview_controlled_broker_submission(
        order_id: str,
        request: ControlledBrokerSubmissionPreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview(
            order_id=order_id,
            confirmation_id=request.confirmation_id,
            release_evidence_id=request.release_evidence_id,
        )

    @router.post("/orders/{order_id}/submissions")
    async def submit_controlled_broker_order(
        order_id: str,
        request: ControlledBrokerSubmissionRequest,
    ) -> dict[str, Any]:
        try:
            return _service().submit(
                order_id=order_id,
                confirmation_id=request.confirmation_id,
                release_evidence_id=request.release_evidence_id,
                submit_fingerprint=request.submit_fingerprint,
                operator_approval_id=request.operator_approval_id,
                operator_proof_signature_base64=(
                    request.operator_proof_signature_base64
                ),
                acknowledgement=request.acknowledgement,
            )
        except ControlledBrokerSubmissionRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.post("/intents/{submit_intent_id}/recovery/preview")
    async def preview_controlled_broker_submission_recovery(
        submit_intent_id: str,
    ) -> dict[str, Any]:
        return _service().preview_recovery(submit_intent_id=submit_intent_id)

    @router.post("/intents/{submit_intent_id}/recoveries")
    async def recover_controlled_broker_submission(
        submit_intent_id: str,
        request: ControlledBrokerRecoveryRequest,
    ) -> dict[str, Any]:
        try:
            return _service().recover(
                submit_intent_id=submit_intent_id,
                recovery_fingerprint=request.recovery_fingerprint,
                operator_approval_id=request.operator_approval_id,
                operator_proof_signature_base64=(
                    request.operator_proof_signature_base64
                ),
                acknowledgement=request.acknowledgement,
            )
        except ControlledBrokerSubmissionRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/intents")
    async def list_controlled_broker_submit_intents(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_intents(limit=limit)

    @router.get("/intents/{submit_intent_id}")
    async def get_controlled_broker_submit_intent(
        submit_intent_id: str,
    ) -> dict[str, Any]:
        return _service().get_intent(submit_intent_id)

    @router.get("/reconciliation-clearance/status")
    async def get_controlled_submission_clearance_status() -> dict[str, Any]:
        return _clearance_service().get_status()

    @router.post("/intents/{submit_intent_id}/reconciliation-clearance/preview")
    async def preview_controlled_submission_clearance(
        submit_intent_id: str,
        request: ControlledSubmissionClearancePreviewRequest,
    ) -> dict[str, Any]:
        return _clearance_service().preview(
            submit_intent_id=submit_intent_id,
            reconciliation_run_id=request.reconciliation_run_id,
        )

    @router.post("/intents/{submit_intent_id}/reconciliation-clearances")
    async def record_controlled_submission_clearance(
        submit_intent_id: str,
        request: ControlledSubmissionClearanceRequest,
    ) -> dict[str, Any]:
        try:
            return _clearance_service().record(
                submit_intent_id=submit_intent_id,
                reconciliation_run_id=request.reconciliation_run_id,
                clearance_fingerprint=request.clearance_fingerprint,
                operator_approval_id=request.operator_approval_id,
                operator_proof_signature_base64=(
                    request.operator_proof_signature_base64
                ),
                acknowledgement=request.acknowledgement,
            )
        except ControlledSubmissionReconciliationClearanceRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/reconciliation-clearances")
    async def list_controlled_submission_clearances(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _clearance_service().list_clearances(limit=limit)

    @router.get("/reconciliation-clearances/{clearance_id}")
    async def get_controlled_submission_clearance(
        clearance_id: str,
    ) -> dict[str, Any]:
        return _clearance_service().get_clearance(clearance_id)

    return router


def _service() -> ControlledBrokerSubmissionService:
    from server.app import get_app_state
    from server.routes.per_order_confirmation import (
        _service as per_order_confirmation_service,
    )

    state = get_app_state()
    config = getattr(state, "config", None)
    return ControlledBrokerSubmissionService(
        db=state.db,
        gateways=getattr(state, "execution_gateways", []) or [],
        confirmation_provider=per_order_confirmation_service().resolve_confirmation,
        release_evidence_provider=getattr(
            state,
            "controlled_broker_release_evidence_provider",
            None,
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        trading_controls=getattr(state, "trading_controls", None),
    )


def _clearance_service() -> ControlledSubmissionReconciliationClearanceService:
    from server.account_truth_gate import build_latest_account_truth_promotion_evidence
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    return ControlledSubmissionReconciliationClearanceService(
        db=state.db,
        account_truth_provider=(
            lambda: build_latest_account_truth_promotion_evidence(
                state,
                max_age_seconds=(
                    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS
                ),
            )
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )
