"""Deterministic projection for an append-only controlled-ledger correction."""

from __future__ import annotations

from typing import Any

from server.projections.ledger_exclusion_correction import (
    LedgerExclusionCorrectionPlanError,
    build_ledger_exclusion_correction_plan,
    correction_plan_fingerprint,
)

CONTROLLED_SUBMISSION_LEDGER_CORRECTION_PLAN_SCHEMA_VERSION = (
    "karkinos.controlled_submission_ledger_correction_plan.v1"
)
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE = "controlled_projection_correction"
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE = (
    "controlled_submission_ledger_correction"
)


class ControlledSubmissionLedgerCorrectionPlanError(ValueError):
    """Raised when the original posting cannot be safely compensated."""

    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


def build_controlled_ledger_correction_plan(
    *,
    ledger_rows: list[dict[str, Any]],
    original_entry_ids: list[int],
    posting_id: str,
) -> dict[str, Any]:
    """Derive the only allowed correction from deterministic ledger replay."""

    try:
        return build_ledger_exclusion_correction_plan(
            ledger_rows=ledger_rows,
            original_entry_ids=original_entry_ids,
            required_sources={"controlled_submission_ledger_posting"},
            schema_version=(
                CONTROLLED_SUBMISSION_LEDGER_CORRECTION_PLAN_SCHEMA_VERSION
            ),
            correction_identity={"posting_id": posting_id},
            blocker_prefix="controlled_ledger_correction",
            derivation=("canonical_replay_excluding_exact_original_posting_entries"),
        )
    except LedgerExclusionCorrectionPlanError as exc:
        blocker = str(exc)
        if blocker == "controlled_ledger_correction_zero_entry_scope":
            blocker = "controlled_ledger_correction_zero_fill_posting"
        raise ControlledSubmissionLedgerCorrectionPlanError(blocker) from None


__all__ = [
    "CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE",
    "CONTROLLED_SUBMISSION_LEDGER_CORRECTION_PLAN_SCHEMA_VERSION",
    "CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE",
    "ControlledSubmissionLedgerCorrectionPlanError",
    "build_controlled_ledger_correction_plan",
    "correction_plan_fingerprint",
]
