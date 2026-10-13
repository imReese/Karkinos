"""Quarantined live execution, broker adapters, and reconciliation infrastructure.

DURABLE INVARIANT (AGENTS.md & docs/PLAN.md):
- Real-money authority remains default-off, bounded, observable, pausable, revocable, and human-supervised.
- Live-trading safety constraints are durable boundaries, not current implementation scope.
- Strategy and research code never call a broker directly.
- All modules within this package are frozen under docs/PLAN.md.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "BROKER_ADAPTER_READINESS_SCHEMA_VERSION",
    "BROKER_LIFECYCLE_EVIDENCE_HEALTH_SCHEMA_VERSION",
    "BROKER_LIFECYCLE_EVIDENCE_QUERY_SCHEMA_VERSION",
    "BrokerAdapterReadinessService",
    "BrokerLifecycleEvidenceViewService",
    "CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION",
    "CITIC_QUERY_WINDOW_BATCH_ASSESSMENT_SCHEMA_VERSION",
    "CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION",
    "CITIC_SOURCE_QUERY_WINDOW_REVIEW_COMMAND_SCHEMA_VERSION",
    "CITIC_SOURCE_SCOPE_BATCH_ASSESSMENT_SCHEMA_VERSION",
    "CITIC_SOURCE_SCOPE_REVIEW_COMMAND_SCHEMA_VERSION",
    "EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION",
    "EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS",
    "EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT",
    "EXECUTION_GATEWAY_VERIFICATION_BINDING_SCHEMA_VERSION",
    "EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION",
    "EXECUTION_GATEWAY_VERIFICATION_STATUS_SCHEMA_VERSION",
    "ExecutionBatchReconciliationRejected",
    "ExecutionBatchReconciliationService",
    "ExecutionGatewayRuntimeProtocol",
    "ExecutionGatewayVerificationRejected",
    "ExecutionGatewayVerificationService",
    "build_broker_adapter_readiness",
    "build_broker_connectors",
    "build_citic_history_canonical_lineage_assessment",
    "build_citic_source_follow_up",
    "build_execution_gateway_binding",
    "build_execution_gateway_order_contract",
    "current_citic_source_set_fingerprint",
    "project_citic_history_canonical_lineage_assessment",
    "project_citic_query_window_batch_assessment",
    "project_citic_source_scope_batch_assessment",
    "record_citic_source_canonical_resolution",
    "record_citic_source_query_window_review",
    "record_citic_source_scope_review",
    "resolve_execution_gateway_verification_binding",
    "resolve_prior_batch_reconciliation",
    "revoke_citic_source_canonical_resolution",
    "revoke_citic_source_query_window_review",
    "revoke_citic_source_scope_review",
]

_SUBMODULE_MAP = {
    # Broker
    "BROKER_ADAPTER_READINESS_SCHEMA_VERSION": "broker",
    "BROKER_LIFECYCLE_EVIDENCE_HEALTH_SCHEMA_VERSION": "broker",
    "BROKER_LIFECYCLE_EVIDENCE_QUERY_SCHEMA_VERSION": "broker",
    "BrokerAdapterReadinessService": "broker",
    "BrokerLifecycleEvidenceViewService": "broker",
    "build_broker_adapter_readiness": "broker",
    "build_broker_connectors": "broker",
    # Citic
    "CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION": "citic",
    "CITIC_QUERY_WINDOW_BATCH_ASSESSMENT_SCHEMA_VERSION": "citic",
    "CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION": "citic",
    "CITIC_SOURCE_QUERY_WINDOW_REVIEW_COMMAND_SCHEMA_VERSION": "citic",
    "CITIC_SOURCE_SCOPE_BATCH_ASSESSMENT_SCHEMA_VERSION": "citic",
    "CITIC_SOURCE_SCOPE_REVIEW_COMMAND_SCHEMA_VERSION": "citic",
    "build_citic_history_canonical_lineage_assessment": "citic",
    "build_citic_source_follow_up": "citic",
    "current_citic_source_set_fingerprint": "citic",
    "project_citic_history_canonical_lineage_assessment": "citic",
    "project_citic_query_window_batch_assessment": "citic",
    "project_citic_source_scope_batch_assessment": "citic",
    "record_citic_source_canonical_resolution": "citic",
    "record_citic_source_query_window_review": "citic",
    "record_citic_source_scope_review": "citic",
    "revoke_citic_source_canonical_resolution": "citic",
    "revoke_citic_source_query_window_review": "citic",
    "revoke_citic_source_scope_review": "citic",
    # Gateway
    "EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS": "gateway",
    "EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT": "gateway",
    "EXECUTION_GATEWAY_VERIFICATION_BINDING_SCHEMA_VERSION": "gateway",
    "EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION": "gateway",
    "EXECUTION_GATEWAY_VERIFICATION_STATUS_SCHEMA_VERSION": "gateway",
    "ExecutionGatewayRuntimeProtocol": "gateway",
    "ExecutionGatewayVerificationRejected": "gateway",
    "ExecutionGatewayVerificationService": "gateway",
    "build_execution_gateway_binding": "gateway",
    "build_execution_gateway_order_contract": "gateway",
    "resolve_execution_gateway_verification_binding": "gateway",
    # Reconciliation
    "EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION": "reconciliation",
    "ExecutionBatchReconciliationRejected": "reconciliation",
    "ExecutionBatchReconciliationService": "reconciliation",
    "resolve_prior_batch_reconciliation": "reconciliation",
}


def __getattr__(name: str) -> Any:
    submodule = _SUBMODULE_MAP.get(name)
    if submodule:
        mod = importlib.import_module(
            f"server.services.controlled_execution.{submodule}"
        )
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
