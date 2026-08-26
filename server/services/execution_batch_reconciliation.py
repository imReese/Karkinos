"""Compatible façade for append-only execution batch reconciliation evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from server.services.execution_batch_reconciliation_commands import (
    record_execution_batch_reconciliation,
)
from server.services.execution_batch_reconciliation_projection import (
    build_execution_batch_reconciliation_preview,
)
from server.services.execution_batch_reconciliation_queries import (
    list_execution_batch_reconciliations,
    resolve_recorded_execution_batch_reconciliation,
)
from server.services.execution_batch_reconciliation_values import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
    EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
    EXECUTION_BATCH_RECONCILIATION_STATUS_SCHEMA_VERSION,
    MAX_BATCH_ORDER_COUNT,
    safety_flags,
)


class ExecutionBatchReconciliationRejected(ValueError):
    """Raised after an invalid record attempt is persisted."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ExecutionBatchReconciliationService:
    """Bind an exact prior order batch to immutable reconciliation evidence."""

    def __init__(
        self,
        *,
        db: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": EXECUTION_BATCH_RECONCILIATION_STATUS_SCHEMA_VERSION,
            "contract_status": "read_only_append_only_exact_batch_evidence",
            "maximum_batch_order_count": MAX_BATCH_ORDER_COUNT,
            "acknowledgement": EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
            "manual_mismatch_acceptance_enabled": False,
            "operator_identity_verified": False,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "safety": safety_flags(),
            "limitations": [
                "Only persisted no-action reconciliation items can produce a clear batch fact.",
                "Manual acceptance of a mismatch is intentionally not implemented.",
                "A clear batch fact can satisfy one prior-batch evidence gate but cannot authorize the next batch.",
            ],
        }

    def preview(
        self,
        *,
        batch_id: str,
        order_ids: list[str] | tuple[str, ...],
        reconciliation_run_id: str,
    ) -> dict[str, Any]:
        return build_execution_batch_reconciliation_preview(
            db=self._db,
            clock=self._clock,
            batch_id=batch_id,
            order_ids=order_ids,
            reconciliation_run_id=reconciliation_run_id,
        )

    def record(
        self,
        *,
        batch_id: str,
        order_ids: list[str] | tuple[str, ...],
        reconciliation_run_id: str,
        batch_reconciliation_fingerprint: str,
        operator_label: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        return record_execution_batch_reconciliation(
            db=self._db,
            clock=self._clock,
            preview_builder=self.preview,
            rejected_type=ExecutionBatchReconciliationRejected,
            batch_id=batch_id,
            order_ids=order_ids,
            reconciliation_run_id=reconciliation_run_id,
            batch_reconciliation_fingerprint=batch_reconciliation_fingerprint,
            operator_label=operator_label,
            acknowledgement=acknowledgement,
        )

    def resolve_recorded(
        self,
        fingerprint: str,
        *,
        expected_strategy_id: str | None = None,
    ) -> dict[str, Any]:
        return resolve_recorded_execution_batch_reconciliation(
            db=self._db,
            preview_builder=self.preview,
            fingerprint=fingerprint,
            expected_strategy_id=expected_strategy_id,
        )

    def list_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return list_execution_batch_reconciliations(db=self._db, limit=limit)


def resolve_prior_batch_reconciliation(
    *,
    db: Any,
    fingerprint: str,
    expected_strategy_id: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve one exact batch fact for proposal consumers."""
    result = ExecutionBatchReconciliationService(db=db).resolve_recorded(
        fingerprint,
        expected_strategy_id=expected_strategy_id,
    )
    return result, [str(item) for item in result.get("blockers") or []]
