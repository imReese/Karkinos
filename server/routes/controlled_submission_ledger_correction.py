"""Preview and signed apply routes for append-only ledger corrections."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.controlled_submission_ledger_correction import (
    CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT,
    CONTROLLED_SUBMISSION_LEDGER_CORRECTION_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
    ControlledSubmissionLedgerCorrectionRejected,
    ControlledSubmissionLedgerCorrectionService,
)

CorrectionReason = Literal[
    "broker_evidence_superseded",
    "duplicate_controlled_posting",
    "operator_confirmed_mapping_error",
]


class ControlledSubmissionLedgerCorrectionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: CorrectionReason
    operator_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )


class ControlledSubmissionLedgerCorrectionApplyRequest(
    ControlledSubmissionLedgerCorrectionPreviewRequest
):
    correction_fingerprint: str = Field(
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
    acknowledgement: Literal["apply_exact_compensating_ledger_correction_once"] = (
        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT
    )


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-ledger-corrections",
        tags=["automation", "controlled-bridge", "ledger-correction"],
    )

    @router.get("/status")
    async def get_controlled_submission_ledger_correction_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/postings/{posting_id}/preview")
    async def preview_controlled_submission_ledger_correction(
        posting_id: str,
        request: ControlledSubmissionLedgerCorrectionPreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview(
            posting_id=posting_id,
            reason_code=request.reason_code,
            operator_id=request.operator_id,
        )

    @router.post("/postings/{posting_id}/corrections")
    async def apply_controlled_submission_ledger_correction(
        posting_id: str,
        request: ControlledSubmissionLedgerCorrectionApplyRequest,
    ) -> dict[str, Any]:
        try:
            return _service().apply(
                posting_id=posting_id,
                reason_code=request.reason_code,
                operator_id=request.operator_id,
                correction_fingerprint=request.correction_fingerprint,
                operator_approval_id=request.operator_approval_id,
                operator_proof_signature_base64=(
                    request.operator_proof_signature_base64
                ),
                acknowledgement=request.acknowledgement,
            )
        except ControlledSubmissionLedgerCorrectionRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/corrections")
    async def list_controlled_submission_ledger_corrections(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_corrections(limit=limit)

    @router.get("/corrections/{correction_id}")
    async def get_controlled_submission_ledger_correction(
        correction_id: str,
    ) -> dict[str, Any]:
        return _service().get_correction(correction_id)

    return router


def _service() -> ControlledSubmissionLedgerCorrectionService:
    from server.account_truth_gate import build_latest_account_truth_promotion_evidence
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    return ControlledSubmissionLedgerCorrectionService(
        db=state.db,
        account_truth_provider=(
            lambda: build_latest_account_truth_promotion_evidence(
                state,
                max_age_seconds=(
                    CONTROLLED_SUBMISSION_LEDGER_CORRECTION_MAX_ACCOUNT_TRUTH_AGE_SECONDS
                ),
            )
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )
