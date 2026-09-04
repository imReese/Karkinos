"""Account Truth capture boundary for qualification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    CaptureEvidenceType,
    HumanContextCaptureRequest,
)
from server.contracts.ai_shadow_research_qualification import (
    ShadowResearchQualificationRejected,
)
from server.contracts.content_identity import content_fingerprint
from server.services.ai_shadow_research_qualification_support import (
    account_total_equity,
    valid_fingerprint,
    valuation_fingerprint,
)


async def capture_qualification_account_state(
    capture_service: Any,
    *,
    batch: Mapping[str, Any],
    valuation: Mapping[str, Any],
    write_guard: Any | None = None,
) -> dict[str, Any]:
    request = HumanContextCaptureRequest(
        idempotency_key=(
            "account-qualification:"
            + content_fingerprint(
                {
                    "source_run_id": batch["run_id"],
                    "valuation_snapshot_id": valuation["snapshot_id"],
                    "ledger_cutoff_id": valuation["ledger_cutoff_id"],
                    "ledger_fingerprint": valuation["ledger_fingerprint"],
                }
            )
        ),
        requested_by="automation:account-qualification",
        research_question=(
            "Provider-free account qualification of the latest verified "
            "normalized Formula candidate batch."
        ),
        account_alias="current-canonical-account",
        evidence_types=(CaptureEvidenceType.ACCOUNT_STATE,),
        confirmation=CAPTURE_CONFIRMATION,
    )
    if callable(write_guard):
        write_guard()
    capture = await capture_service.capture(request, write_guard=write_guard)
    if callable(write_guard):
        write_guard()
    context = capture.context
    records = tuple(capture.records)
    if (
        context.valuation_snapshot_id != valuation["snapshot_id"]
        or context.ledger_cutoff_id != valuation["ledger_cutoff_id"]
        or context.ledger_fingerprint != valuation["ledger_fingerprint"]
        or context.persisted_facts_only is not True
        or len(records) != 1
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_account_capture_identity_mismatch"
        )
    record = records[0]
    if (
        record.tool_name != "account_state_projection.read"
        or record.status != "complete"
        or record.authoritative is not True
        or record.persisted_facts_only is not True
        or record.valuation_snapshot_id != valuation["snapshot_id"]
        or record.ledger_cutoff_id != valuation["ledger_cutoff_id"]
        or record.ledger_fingerprint != valuation["ledger_fingerprint"]
        or not valid_fingerprint(record.record_fingerprint)
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_account_evidence_not_authoritative"
        )
    return {
        "record": record,
        "total_equity": account_total_equity(record.payload, valuation),
        "valuation_snapshot_id": valuation["snapshot_id"],
        "valuation_snapshot_fingerprint": valuation_fingerprint(
            valuation["snapshot_id"]
        ),
        "ledger_cutoff_id": valuation["ledger_cutoff_id"],
        "ledger_fingerprint": valuation["ledger_fingerprint"],
    }


__all__ = ["capture_qualification_account_state"]
