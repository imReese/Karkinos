"""Compatible façade for append-only execution batch reconciliation evidence.

Backward-compatible facade for server.services.controlled_execution.reconciliation.
"""

from __future__ import annotations

from server.services.controlled_execution.reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
    EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
    EXECUTION_BATCH_RECONCILIATION_STATUS_SCHEMA_VERSION,
    MAX_BATCH_ORDER_COUNT,
    ExecutionBatchReconciliationRejected,
    ExecutionBatchReconciliationService,
    build_execution_batch_reconciliation_preview,
    list_execution_batch_reconciliations,
    record_execution_batch_reconciliation,
    resolve_prior_batch_reconciliation,
    resolve_recorded_execution_batch_reconciliation,
    safety_flags,
)

__all__ = [
    "EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT",
    "EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE",
    "EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE",
    "EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE",
    "EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION",
    "EXECUTION_BATCH_RECONCILIATION_STATUS_SCHEMA_VERSION",
    "ExecutionBatchReconciliationRejected",
    "ExecutionBatchReconciliationService",
    "MAX_BATCH_ORDER_COUNT",
    "build_execution_batch_reconciliation_preview",
    "list_execution_batch_reconciliations",
    "record_execution_batch_reconciliation",
    "resolve_prior_batch_reconciliation",
    "resolve_recorded_execution_batch_reconciliation",
    "safety_flags",
]
