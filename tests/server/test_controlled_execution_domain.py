"""Safety behavior for canonical controlled-execution service owners."""

from __future__ import annotations

from server.services.controlled_execution.gateway import (
    ExecutionGatewayVerificationService,
    build_execution_gateway_binding,
)
from server.services.controlled_execution.reconciliation import (
    ExecutionBatchReconciliationService,
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
