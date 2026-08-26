"""Status and persisted-clearance queries."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
    CONTROLLED_SUBMISSION_CLEARANCE_STATUS_SCHEMA_VERSION,
)
from server.services.controlled_submission_clearance_context import (
    ControlledSubmissionClearanceContext,
)
from server.services.controlled_submission_clearance_values import (
    clearance_response,
    safety_flags,
)


class ControlledSubmissionClearanceQueryMixin(ControlledSubmissionClearanceContext):
    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": CONTROLLED_SUBMISSION_CLEARANCE_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "signed_terminal_outcome_clearance_available"
                if callable(self._account_truth_provider)
                and self._trusted_operator_identities
                else "disabled_waiting_for_account_truth_and_operator_signature"
            ),
            "account_truth_provider_configured": callable(self._account_truth_provider),
            "trusted_operator_signature_configured": bool(
                self._trusted_operator_identities
            ),
            "maximum_account_truth_age_seconds": (
                CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS
            ),
            "full_fill_clearance_enabled": True,
            "partial_fill_terminal_cancel_clearance_enabled": True,
            "open_partial_fill_clearance_enabled": False,
            "no_fill_cancel_clearance_enabled": True,
            "automatic_ledger_mutation_enabled": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "acknowledgement": CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
            "safety": safety_flags(),
        }

    def get_clearance(self, clearance_id: str) -> dict[str, Any]:
        row = self._db.get_controlled_submission_reconciliation_clearance_sync(
            clearance_id
        )
        return (
            clearance_response(row, reused=False)
            if row is not None
            else {"status": "not_found", "clearance_id": clearance_id}
        )

    def list_clearances(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            clearance_response(row, reused=False)
            for row in self._db.list_controlled_submission_reconciliation_clearances_sync(
                limit=limit
            )
        ]
