"""Canonical contracts for signed controlled-submission clearance."""

from __future__ import annotations

CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION = (
    "karkinos.controlled_submission_reconciliation_clearance.v3"
)
CONTROLLED_SUBMISSION_CLEARANCE_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_submission_reconciliation_clearance_status.v3"
)
CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT = (
    "clear_exact_terminal_outcome_without_automatic_ledger_mutation"
)
CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS = 120
CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_EVENT_TYPE = (
    "controlled_broker.reconciliation_clearance_rejected"
)
CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_ENTITY_TYPE = (
    "controlled_submission_reconciliation_clearance_rejection"
)
CONTROLLED_SUBMISSION_CLEARANCE_EVENT_SOURCE = (
    "controlled_submission_reconciliation_clearance"
)
