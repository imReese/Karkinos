"""Read-only preview and human-signed controlled ledger-posting routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.controlled_submission_ledger_posting import (
    CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT,
    CONTROLLED_SUBMISSION_LEDGER_POSTING_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
    ControlledSubmissionLedgerPostingRejected,
    ControlledSubmissionLedgerPostingService,
)


class ControlledSubmissionLedgerPostingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posting_fingerprint: str = Field(
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
    acknowledgement: Literal["apply_exact_reconciled_ledger_posting_once"] = (
        CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT
    )


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-ledger-posting",
        tags=["automation", "controlled-bridge", "ledger-posting"],
    )

    @router.get("/status")
    async def get_controlled_submission_ledger_posting_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/clearances/{clearance_id}/preview")
    async def preview_controlled_submission_ledger_posting(
        clearance_id: str,
    ) -> dict[str, Any]:
        return _service().preview(clearance_id=clearance_id)

    @router.post("/clearances/{clearance_id}/postings")
    async def apply_controlled_submission_ledger_posting(
        clearance_id: str,
        request: ControlledSubmissionLedgerPostingRequest,
    ) -> dict[str, Any]:
        try:
            return _service().apply(
                clearance_id=clearance_id,
                posting_fingerprint=request.posting_fingerprint,
                operator_approval_id=request.operator_approval_id,
                operator_proof_signature_base64=(
                    request.operator_proof_signature_base64
                ),
                acknowledgement=request.acknowledgement,
            )
        except ControlledSubmissionLedgerPostingRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/postings")
    async def list_controlled_submission_ledger_postings(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_postings(limit=limit)

    @router.get("/postings/{posting_id}")
    async def get_controlled_submission_ledger_posting(
        posting_id: str,
    ) -> dict[str, Any]:
        return _service().get_posting(posting_id)

    return router


def _service() -> ControlledSubmissionLedgerPostingService:
    from server.account_truth_gate import build_latest_account_truth_promotion_evidence
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    return ControlledSubmissionLedgerPostingService(
        db=state.db,
        account_truth_provider=(
            lambda: build_latest_account_truth_promotion_evidence(
                state,
                max_age_seconds=(
                    CONTROLLED_SUBMISSION_LEDGER_POSTING_MAX_ACCOUNT_TRUTH_AGE_SECONDS
                ),
            )
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )
