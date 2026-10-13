"""Executable verification for server.services.controlled_execution quarantine domain package."""

from __future__ import annotations

import server.services.broker_adapter_readiness as legacy_readiness
import server.services.broker_connector_runtime as legacy_connector_runtime
import server.services.broker_lifecycle_evidence_view as legacy_lifecycle
import server.services.citic_history_canonical_lineage as legacy_lineage
import server.services.citic_source_canonical_resolution as legacy_citic
import server.services.citic_source_follow_up as legacy_follow_up
import server.services.citic_source_query_window_review as legacy_query_window
import server.services.citic_source_scope_review as legacy_scope_review
import server.services.execution_batch_reconciliation as legacy_reconciliation
import server.services.execution_gateway_binding as legacy_gateway_binding
import server.services.execution_gateway_verification as legacy_gateway_verification
import server.services.execution_gateway_verification_binding as legacy_gateway_verification_binding
from server.services import controlled_execution
from server.services.controlled_execution import (
    BROKER_ADAPTER_READINESS_SCHEMA_VERSION,
    BROKER_LIFECYCLE_EVIDENCE_HEALTH_SCHEMA_VERSION,
    CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION,
    CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION,
    EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
    EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION,
    BrokerAdapterReadinessService,
    BrokerLifecycleEvidenceViewService,
    ExecutionBatchReconciliationRejected,
    ExecutionBatchReconciliationService,
    ExecutionGatewayVerificationService,
    build_broker_adapter_readiness,
    build_broker_connectors,
    build_citic_history_canonical_lineage_assessment,
    build_citic_source_follow_up,
    build_execution_gateway_binding,
    build_execution_gateway_order_contract,
    record_citic_source_canonical_resolution,
    resolve_execution_gateway_verification_binding,
    resolve_prior_batch_reconciliation,
)


def test_controlled_execution_exports_canonical_symbols() -> None:
    # Reconciliation
    assert (
        EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION
        == legacy_reconciliation.EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION
    )
    assert (
        ExecutionBatchReconciliationRejected
        is legacy_reconciliation.ExecutionBatchReconciliationRejected
    )
    assert (
        ExecutionBatchReconciliationService
        is legacy_reconciliation.ExecutionBatchReconciliationService
    )
    assert (
        resolve_prior_batch_reconciliation
        is legacy_reconciliation.resolve_prior_batch_reconciliation
    )

    # CITIC
    assert (
        record_citic_source_canonical_resolution
        is legacy_citic.record_citic_source_canonical_resolution
    )
    assert build_citic_source_follow_up is legacy_follow_up.build_citic_source_follow_up
    assert (
        CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION
        == legacy_follow_up.CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION
    )
    assert (
        build_citic_history_canonical_lineage_assessment
        is legacy_lineage.build_citic_history_canonical_lineage_assessment
    )
    assert (
        CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION
        == legacy_lineage.CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION
    )

    # Gateway
    assert (
        build_execution_gateway_binding
        is legacy_gateway_binding.build_execution_gateway_binding
    )
    assert (
        build_execution_gateway_order_contract
        is legacy_gateway_verification_binding.build_execution_gateway_order_contract
    )
    assert (
        resolve_execution_gateway_verification_binding
        is legacy_gateway_verification_binding.resolve_execution_gateway_verification_binding
    )
    assert (
        ExecutionGatewayVerificationService
        is legacy_gateway_verification.ExecutionGatewayVerificationService
    )
    assert (
        EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION
        == legacy_gateway_verification.EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION
    )

    # Broker
    assert build_broker_connectors is legacy_connector_runtime.build_broker_connectors
    assert (
        build_broker_adapter_readiness
        is legacy_readiness.build_broker_adapter_readiness
    )
    assert (
        BrokerAdapterReadinessService is legacy_readiness.BrokerAdapterReadinessService
    )
    assert (
        BROKER_ADAPTER_READINESS_SCHEMA_VERSION
        == legacy_readiness.BROKER_ADAPTER_READINESS_SCHEMA_VERSION
    )
    assert (
        BrokerLifecycleEvidenceViewService
        is legacy_lifecycle.BrokerLifecycleEvidenceViewService
    )
    assert (
        BROKER_LIFECYCLE_EVIDENCE_HEALTH_SCHEMA_VERSION
        == legacy_lifecycle.BROKER_LIFECYCLE_EVIDENCE_HEALTH_SCHEMA_VERSION
    )


def test_controlled_execution_safety_invariants() -> None:
    reconciliation_service = ExecutionBatchReconciliationService(db=None)
    recon_status = reconciliation_service.get_status()
    assert recon_status["broker_submission_enabled"] is False
    assert recon_status["runtime_execution_authority"] == "disabled"
    assert recon_status["manual_mismatch_acceptance_enabled"] is False

    gateway_service = ExecutionGatewayVerificationService(db=None)
    gateway_status = gateway_service.get_status()
    assert gateway_status["broker_submission_enabled"] is False
    assert gateway_status["runtime_execution_authority"] == "disabled"

    binding, blockers = build_execution_gateway_binding(
        gateway_id="gw1",
        health_status="healthy",
        can_submit_orders=True,
        account_binding_status="verified",
    )
    assert binding["broker_submission_enabled"] is False
    assert binding["authorizes_execution"] is False
    assert "execution_gateway_runtime_not_verified" in blockers
