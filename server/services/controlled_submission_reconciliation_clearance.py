"""Signed exact-terminal reconciliation clearance for one controlled submission."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import server.services.controlled_submission_clearance_evidence_values as _evidence_values
import server.services.controlled_submission_clearance_values as _clearance_values
from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_order_lifecycle import (
    BrokerOrderLifecycleEvidenceRepository,
    broker_order_lifecycle_terminal_outcome,
)
from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT as CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
)
from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_EVENT_SOURCE as CONTROLLED_SUBMISSION_CLEARANCE_EVENT_SOURCE,
)
from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS as CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
)
from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_ENTITY_TYPE as CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_ENTITY_TYPE,
)
from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_EVENT_TYPE as CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_EVENT_TYPE,
)
from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION as CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
)
from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_STATUS_SCHEMA_VERSION as CONTROLLED_SUBMISSION_CLEARANCE_STATUS_SCHEMA_VERSION,
)
from server.services.controlled_submission_clearance_command import (
    ControlledSubmissionClearanceCommandMixin as _ControlledSubmissionClearanceCommandMixin,
)
from server.services.controlled_submission_clearance_evidence import (
    ControlledSubmissionClearanceEvidenceMixin as _ControlledSubmissionClearanceEvidenceMixin,
)
from server.services.controlled_submission_clearance_preview import (
    ControlledSubmissionClearancePreviewMixin as _ControlledSubmissionClearancePreviewMixin,
)
from server.services.controlled_submission_clearance_queries import (
    ControlledSubmissionClearanceQueryMixin as _ControlledSubmissionClearanceQueryMixin,
)
from server.services.execution_identity import build_order_fingerprint
from server.services.operator_approval import resolve_operator_approval_with_proof

_FINGERPRINT_PATTERN = _clearance_values.FINGERPRINT_PATTERN
_ID_PATTERN = _clearance_values.ID_PATTERN
_controlled_post_trade_account_truth_delta = (
    _evidence_values.controlled_post_trade_account_truth_delta
)
_fill_descriptor = _evidence_values.fill_descriptor
_broker_event_contract = _evidence_values.broker_event_contract
_terminal_cancel_statement_blockers = (
    _evidence_values.terminal_cancel_statement_blockers
)
_reconciliation_item_contract = _evidence_values.reconciliation_item_contract
_clearance_response = _clearance_values.clearance_response
_decimal = _clearance_values.decimal_value
_decimal_string = _clearance_values.decimal_string
_fingerprint = _clearance_values.fingerprint
_json_object = _clearance_values.json_object
_mapping = _clearance_values.mapping
_parse_timestamp = _clearance_values.parse_timestamp
_aware_utc = _clearance_values.aware_utc
_safety_flags = _clearance_values.safety_flags


class ControlledSubmissionReconciliationClearanceRejected(ValueError):
    """Raised after a rejected signed clearance attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSubmissionReconciliationClearanceService(
    _ControlledSubmissionClearanceQueryMixin,
    _ControlledSubmissionClearancePreviewMixin,
    _ControlledSubmissionClearanceCommandMixin,
    _ControlledSubmissionClearanceEvidenceMixin,
):
    """Record an exact reviewed terminal outcome without ledger writes."""

    def __init__(
        self,
        *,
        db: Any,
        account_truth_provider: Callable[[], dict[str, Any]] | None = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._account_truth_provider = account_truth_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _build_order_fingerprint(self, order: dict[str, Any]) -> str:
        return build_order_fingerprint(order)

    def _resolve_operator_approval_with_proof(
        self,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_operator_approval_with_proof(**kwargs)

    def _broker_evidence_repository(self, path: Path) -> Any:
        return BrokerEvidenceRepository(path)

    def _broker_order_lifecycle_repository(
        self,
        path: Path,
        *,
        ensure_schema: bool,
    ) -> Any:
        return BrokerOrderLifecycleEvidenceRepository(
            path,
            ensure_schema=ensure_schema,
        )

    def _broker_order_lifecycle_terminal_outcome(
        self,
        order: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return broker_order_lifecycle_terminal_outcome(order, evidence)

    def _clearance_rejection(
        self,
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> ControlledSubmissionReconciliationClearanceRejected:
        return ControlledSubmissionReconciliationClearanceRejected(
            message,
            evidence=evidence,
        )
