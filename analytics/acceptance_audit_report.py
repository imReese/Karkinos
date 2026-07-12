"""Shared acceptance audit report registry and JSON export helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from analytics.acceptance_audit import (
    AcceptanceAudit,
    build_acceptance_audit,
    build_account_truth_acceptance_audit,
    build_account_truth_review_acceptance_audit,
    build_broker_connector_soak_foundation_acceptance_audit,
    build_broker_connector_soak_promotion_acceptance_audit,
    build_broker_fee_cost_basis_acceptance_audit,
    build_capital_authorization_stage0_acceptance_audit,
    build_capital_scaling_evidence_resolution_acceptance_audit,
    build_capital_scaling_evidence_window_acceptance_audit,
    build_capital_scaling_operating_sample_acceptance_audit,
    build_capital_scaling_review_foundation_acceptance_audit,
    build_controlled_broker_bridge_foundation_acceptance_audit,
    build_controlled_broker_submission_acceptance_audit,
    build_controlled_session_automatic_pause_acceptance_audit,
    build_controlled_session_budget_reservation_acceptance_audit,
    build_controlled_session_envelope_foundation_acceptance_audit,
    build_controlled_session_gateway_verification_binding_acceptance_audit,
    build_controlled_session_live_gate_orchestration_acceptance_audit,
    build_controlled_session_runtime_authority_acceptance_audit,
    build_controlled_session_runtime_rate_limiter_acceptance_audit,
    build_controlled_session_signed_replacement_acceptance_audit,
    build_controlled_session_symbol_budget_acceptance_audit,
    build_execution_batch_reconciliation_acceptance_audit,
    build_execution_gateway_verification_acceptance_audit,
    build_market_data_reliability_acceptance_audit,
    build_operations_runbook_acceptance_audit,
    build_per_order_confirmation_foundation_acceptance_audit,
    build_per_order_gateway_verification_binding_acceptance_audit,
    build_research_evidence_acceptance_audit,
    build_session_start_account_truth_binding_acceptance_audit,
    build_signed_operator_approval_acceptance_audit,
    build_single_instrument_strategy_loop_acceptance_audit,
    build_strategy_assignment_acceptance_audit,
    build_strategy_lab_acceptance_audit,
)

AuditBuilder = Callable[[], AcceptanceAudit]

AUDIT_REGISTRY: dict[str, tuple[str, AuditBuilder]] = {
    "profit_discipline": ("Profit Discipline acceptance audit", build_acceptance_audit),
    "strategy_lab": (
        "Strategy Lab acceptance audit",
        build_strategy_lab_acceptance_audit,
    ),
    "research_evidence": (
        "Research Evidence acceptance audit",
        build_research_evidence_acceptance_audit,
    ),
    "account_truth": (
        "Account Truth acceptance audit",
        build_account_truth_acceptance_audit,
    ),
    "account_truth_review": (
        "Account Truth Review Center acceptance audit",
        build_account_truth_review_acceptance_audit,
    ),
    "strategy_assignment": (
        "Strategy Assignment acceptance audit",
        build_strategy_assignment_acceptance_audit,
    ),
    "market_data_reliability": (
        "Market Data Reliability acceptance audit",
        build_market_data_reliability_acceptance_audit,
    ),
    "broker_fee_cost_basis": (
        "Broker Fee & Cost Basis Fidelity acceptance audit",
        build_broker_fee_cost_basis_acceptance_audit,
    ),
    "single_instrument_strategy_loop": (
        "Single-Instrument Strategy Loop acceptance audit",
        build_single_instrument_strategy_loop_acceptance_audit,
    ),
    "operations_runbook": (
        "Operations Runbook & Paper/Shadow acceptance audit",
        build_operations_runbook_acceptance_audit,
    ),
    "controlled_broker_bridge_foundation": (
        "Controlled Broker Bridge Foundation acceptance audit",
        build_controlled_broker_bridge_foundation_acceptance_audit,
    ),
    "capital_authorization_stage0": (
        "Capital Authorization Stage 0 acceptance audit",
        build_capital_authorization_stage0_acceptance_audit,
    ),
    "broker_connector_soak_foundation": (
        "Read-Only Broker Connector Soak Foundation acceptance audit",
        build_broker_connector_soak_foundation_acceptance_audit,
    ),
    "broker_connector_soak_promotion": (
        "Signed Broker Soak Promotion acceptance audit",
        build_broker_connector_soak_promotion_acceptance_audit,
    ),
    "per_order_confirmation_foundation": (
        "Per-Order Confirmation Foundation acceptance audit",
        build_per_order_confirmation_foundation_acceptance_audit,
    ),
    "execution_gateway_verification": (
        "Execution Gateway Runtime Verification acceptance audit",
        build_execution_gateway_verification_acceptance_audit,
    ),
    "per_order_gateway_verification_binding": (
        "Per-Order Gateway Verification Binding acceptance audit",
        build_per_order_gateway_verification_binding_acceptance_audit,
    ),
    "controlled_session_envelope_foundation": (
        "Controlled Session Envelope Foundation acceptance audit",
        build_controlled_session_envelope_foundation_acceptance_audit,
    ),
    "controlled_session_gateway_verification_binding": (
        "Controlled Session Gateway Verification Binding acceptance audit",
        build_controlled_session_gateway_verification_binding_acceptance_audit,
    ),
    "session_start_account_truth_binding": (
        "Session-Start Account Truth Binding acceptance audit",
        build_session_start_account_truth_binding_acceptance_audit,
    ),
    "controlled_session_budget_reservation": (
        "Controlled Session Atomic Budget Reservation acceptance audit",
        build_controlled_session_budget_reservation_acceptance_audit,
    ),
    "controlled_session_symbol_budget": (
        "Controlled Session Per-Symbol Runtime Budget acceptance audit",
        build_controlled_session_symbol_budget_acceptance_audit,
    ),
    "controlled_session_runtime_rate_limiter": (
        "Controlled Session Runtime Rate Limiter acceptance audit",
        build_controlled_session_runtime_rate_limiter_acceptance_audit,
    ),
    "controlled_session_automatic_pause": (
        "Controlled Session Automatic Pause acceptance audit",
        build_controlled_session_automatic_pause_acceptance_audit,
    ),
    "controlled_session_runtime_authority": (
        "Controlled Session Runtime Authority acceptance audit",
        build_controlled_session_runtime_authority_acceptance_audit,
    ),
    "controlled_session_live_gate_orchestration": (
        "Controlled Session Live-Gate Orchestration acceptance audit",
        build_controlled_session_live_gate_orchestration_acceptance_audit,
    ),
    "controlled_session_signed_replacement": (
        "Controlled Session Signed Replacement acceptance audit",
        build_controlled_session_signed_replacement_acceptance_audit,
    ),
    "controlled_broker_submission": (
        "One-Shot Controlled Broker Submission acceptance audit",
        build_controlled_broker_submission_acceptance_audit,
    ),
    "capital_scaling_review_foundation": (
        "Capital Scaling Review Foundation acceptance audit",
        build_capital_scaling_review_foundation_acceptance_audit,
    ),
    "capital_scaling_evidence_resolution": (
        "Capital Scaling Evidence Resolution acceptance audit",
        build_capital_scaling_evidence_resolution_acceptance_audit,
    ),
    "capital_scaling_evidence_window": (
        "Capital Scaling Computed Evidence Window acceptance audit",
        build_capital_scaling_evidence_window_acceptance_audit,
    ),
    "capital_scaling_operating_sample": (
        "Capital Scaling Operating Sample acceptance audit",
        build_capital_scaling_operating_sample_acceptance_audit,
    ),
    "execution_batch_reconciliation": (
        "Exact Prior-Batch Reconciliation acceptance audit",
        build_execution_batch_reconciliation_acceptance_audit,
    ),
    "signed_operator_approval": (
        "Signed Operator Approval acceptance audit",
        build_signed_operator_approval_acceptance_audit,
    ),
}


def build_acceptance_audit_export(
    *,
    selected_audit: str = "all",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a stable JSON-serializable acceptance audit export."""
    if selected_audit == "all":
        selected_keys = tuple(AUDIT_REGISTRY)
    else:
        selected_keys = (selected_audit,)

    audits = [
        _audit_to_export(
            key=key, name=AUDIT_REGISTRY[key][0], audit=AUDIT_REGISTRY[key][1]()
        )
        for key in selected_keys
    ]
    return {
        "generated_at": generated_at or _utc_timestamp(),
        "selected_audit": selected_audit,
        "audits": audits,
        "overall_is_complete": all(audit["is_complete"] for audit in audits),
    }


def _audit_to_export(
    *,
    key: str,
    name: str,
    audit: AcceptanceAudit,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "required_count": audit.required_count,
        "completed_count": audit.completed_count,
        "is_complete": audit.is_complete,
        "criteria": [criterion.to_json_dict() for criterion in audit.criteria],
        "limitations": audit.limitations,
    }


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
