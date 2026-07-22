from __future__ import annotations

from pathlib import Path

from analytics.acceptance_audit import (
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
    build_controlled_submission_interlock_acceptance_audit,
    build_controlled_submission_reconciliation_clearance_acceptance_audit,
    build_execution_batch_reconciliation_acceptance_audit,
    build_execution_gateway_verification_acceptance_audit,
    build_market_data_reliability_acceptance_audit,
    build_operations_runbook_acceptance_audit,
    build_per_order_confirmation_foundation_acceptance_audit,
    build_per_order_gateway_verification_binding_acceptance_audit,
    build_research_evidence_acceptance_audit,
    build_session_start_account_truth_binding_acceptance_audit,
    build_signed_broker_adapter_release_review_acceptance_audit,
    build_signed_operator_approval_acceptance_audit,
    build_single_instrument_strategy_loop_acceptance_audit,
    build_strategy_assignment_acceptance_audit,
    build_strategy_lab_acceptance_audit,
    build_strategy_learning_review_acceptance_audit,
)


def test_acceptance_audit_has_evidence_for_every_goal_checkbox() -> None:
    audit = build_acceptance_audit()

    assert audit.required_count == 13
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_capital_authorization_stage0_acceptance_audit_is_complete() -> None:
    audit = build_capital_authorization_stage0_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_broker_connector_soak_foundation_acceptance_audit_is_complete() -> None:
    audit = build_broker_connector_soak_foundation_acceptance_audit()

    assert audit.required_count == 11
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_broker_connector_soak_promotion_acceptance_audit_is_complete() -> None:
    audit = build_broker_connector_soak_promotion_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_signed_broker_adapter_release_review_acceptance_audit_is_complete() -> None:
    audit = build_signed_broker_adapter_release_review_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert {criterion.key for criterion in audit.criteria} == {
        "strict_provider_neutral_release_manifest",
        "latest_conformance_exact_acceptance_binding",
        "exact_signed_operator_review_dossier",
        "preview_record_drift_and_retry_integrity",
        "append_only_reject_and_one_way_revoke",
        "strict_api_and_operator_approval_contract",
        "default_collapsed_no_database_edit_web_review",
        "eligibility_only_zero_provider_or_authority_side_effects",
    }
    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_strategy_learning_review_acceptance_audit_is_complete() -> None:
    audit = build_strategy_learning_review_acceptance_audit()

    assert audit.required_count == 7
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert {criterion.key for criterion in audit.criteria} == {
        "latest_persisted_human_review_projection",
        "stored_review_and_event_replay_integrity",
        "current_canonical_target_revalidation",
        "deterministic_learning_actions_and_exact_evidence",
        "copy_only_human_started_research_boundary",
        "read_only_fail_closed_learning_api",
        "strategy_lab_non_authorizing_action_queue",
    }
    for criterion in audit.criteria:
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_per_order_confirmation_foundation_acceptance_audit_is_complete() -> None:
    audit = build_per_order_confirmation_foundation_acceptance_audit()

    assert audit.required_count == 9
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_execution_gateway_verification_acceptance_audit_is_complete() -> None:
    audit = build_execution_gateway_verification_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_per_order_gateway_verification_binding_acceptance_audit_is_complete() -> None:
    audit = build_per_order_gateway_verification_binding_acceptance_audit()

    assert audit.required_count == 7
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_envelope_foundation_acceptance_audit_is_complete() -> None:
    audit = build_controlled_session_envelope_foundation_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_gateway_verification_binding_audit_is_complete() -> None:
    audit = build_controlled_session_gateway_verification_binding_acceptance_audit()

    assert audit.required_count == 7
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_session_start_account_truth_binding_acceptance_audit_is_complete() -> None:
    audit = build_session_start_account_truth_binding_acceptance_audit()

    assert audit.required_count == 7
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_budget_reservation_acceptance_audit_is_complete() -> None:
    audit = build_controlled_session_budget_reservation_acceptance_audit()

    assert audit.required_count == 7
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_symbol_budget_acceptance_audit_is_complete() -> None:
    audit = build_controlled_session_symbol_budget_acceptance_audit()

    assert audit.required_count == 7
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_runtime_rate_limiter_acceptance_audit_is_complete() -> None:
    audit = build_controlled_session_runtime_rate_limiter_acceptance_audit()

    assert audit.required_count == 13
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_automatic_pause_acceptance_audit_is_complete() -> None:
    audit = build_controlled_session_automatic_pause_acceptance_audit()

    assert audit.required_count == 7
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_runtime_authority_acceptance_audit_is_complete() -> None:
    audit = build_controlled_session_runtime_authority_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_live_gate_orchestration_audit_is_complete() -> None:
    audit = build_controlled_session_live_gate_orchestration_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_session_signed_replacement_audit_is_complete() -> None:
    audit = build_controlled_session_signed_replacement_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_broker_submission_audit_is_complete() -> None:
    audit = build_controlled_broker_submission_acceptance_audit()

    assert audit.required_count == 11
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_submission_interlock_audit_is_complete() -> None:
    audit = build_controlled_submission_interlock_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_controlled_submission_reconciliation_clearance_audit_is_complete() -> None:
    audit = build_controlled_submission_reconciliation_clearance_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_capital_scaling_review_foundation_acceptance_audit_is_complete() -> None:
    audit = build_capital_scaling_review_foundation_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_capital_scaling_evidence_resolution_acceptance_audit_is_complete() -> None:
    audit = build_capital_scaling_evidence_resolution_acceptance_audit()

    assert audit.required_count == 6
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_capital_scaling_evidence_window_acceptance_audit_is_complete() -> None:
    audit = build_capital_scaling_evidence_window_acceptance_audit()

    assert audit.required_count == 9
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_capital_scaling_operating_sample_acceptance_audit_is_complete() -> None:
    audit = build_capital_scaling_operating_sample_acceptance_audit()

    assert audit.required_count == 9
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_execution_batch_reconciliation_acceptance_audit_is_complete() -> None:
    audit = build_execution_batch_reconciliation_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_signed_operator_approval_acceptance_audit_is_complete() -> None:
    audit = build_signed_operator_approval_acceptance_audit()

    assert audit.required_count == 8
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_profit_discipline_acceptance_manifest_is_complete() -> None:
    audit = build_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_strategy_lab_acceptance_audit_has_evidence_for_every_goal_checkbox() -> None:
    audit = build_strategy_lab_acceptance_audit()

    assert audit.required_count == 14
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_strategy_lab_acceptance_manifest_is_complete() -> None:
    audit = build_strategy_lab_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_research_evidence_acceptance_audit_has_evidence_for_every_goal_checkbox() -> (
    None
):
    audit = build_research_evidence_acceptance_audit()

    assert audit.required_count == 12
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_research_evidence_acceptance_manifest_is_complete() -> None:
    audit = build_research_evidence_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_account_truth_acceptance_audit_has_evidence_for_every_completed_checkbox() -> (
    None
):
    audit = build_account_truth_acceptance_audit()

    assert audit.required_count == 15
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_account_truth_acceptance_manifest_is_complete() -> None:
    audit = build_account_truth_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_account_truth_review_acceptance_audit_has_evidence_for_every_completed_checkbox() -> (
    None
):
    audit = build_account_truth_review_acceptance_audit()

    assert audit.required_count == 13
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_account_truth_review_acceptance_manifest_is_complete() -> None:
    audit = build_account_truth_review_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_strategy_assignment_acceptance_audit_has_evidence_for_completed_checkboxes() -> (
    None
):
    audit = build_strategy_assignment_acceptance_audit()

    assert audit.required_count == 15
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_strategy_assignment_acceptance_manifest_is_complete() -> None:
    audit = build_strategy_assignment_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_market_data_reliability_acceptance_audit_has_evidence_for_completed_checkboxes() -> (
    None
):
    audit = build_market_data_reliability_acceptance_audit()

    assert audit.required_count == 13
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]
    assert {criterion.key for criterion in audit.criteria} >= {
        "backend_market_data_deterministic_tests",
        "frontend_market_data_status_tests",
        "one_day_net_value_chart_contract",
        "market_data_status_consumer_contract",
        "web_data_status_surface_copy",
        "market_data_reliability_docs",
    }

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_market_data_reliability_acceptance_manifest_is_complete() -> None:
    audit = build_market_data_reliability_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_broker_fee_cost_basis_acceptance_audit_has_evidence_for_completed_checkboxes() -> (
    None
):
    audit = build_broker_fee_cost_basis_acceptance_audit()

    assert audit.required_count == 16
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]
    assert {criterion.key for criterion in audit.criteria} >= {
        "structured_broker_fee_schedule_config",
        "deterministic_fee_breakdown",
        "ledger_entries_preserve_fee_cost_fields",
        "shared_fee_model_contract_across_research_and_ledger",
        "account_truth_cost_basis_method_precision_context",
        "strategy_health_states",
        "web_strategy_contribution_user_readable_surface",
        "shared_public_ledger_formatter_surface_contract",
        "public_ledger_surfaces_hide_internal_values",
        "public_ledger_notes_keep_core_facts_structured",
        "portfolio_cost_views_distinguish_local_and_broker_cost_basis",
        "sell_side_net_proceeds_broker_cost_basis",
        "backend_fee_cost_basis_deterministic_tests",
        "frontend_fee_cost_basis_display_tests",
    }

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_broker_fee_cost_basis_acceptance_manifest_is_complete() -> None:
    audit = build_broker_fee_cost_basis_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_single_instrument_strategy_loop_acceptance_audit_has_evidence() -> None:
    audit = build_single_instrument_strategy_loop_acceptance_audit()

    assert audit.required_count == 10
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]
    assert {criterion.key for criterion in audit.criteria} >= {
        "dataset_snapshot_and_strategy_registry",
        "single_symbol_after_cost_backtest",
        "today_signal_preview",
        "risk_gate_preview",
        "paper_shadow_preview",
        "attribution_preview_boundary",
        "holding_level_attribution_review_readiness",
        "decision_to_holding_attribution_handoff",
        "web_paper_shadow_attribution_boundary",
        "web_user_readable_loop_surface",
    }

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_single_instrument_strategy_loop_user_readable_surface_audit_covers_web_ux_contract() -> (
    None
):
    audit = build_single_instrument_strategy_loop_acceptance_audit()
    user_readable = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "web_user_readable_loop_surface"
    )

    assert "web/src/app/copy.test.ts" in user_readable.evidence_paths
    assert (
        "web/src/features/portfolio/components/holding-detail-page.test.tsx"
        in user_readable.evidence_paths
    )
    assert (
        "web/src/features/decision/components/decision-cockpit-page.test.tsx"
        in user_readable.evidence_paths
    )
    assert any(
        "copy public-labels holding-detail-page decision-cockpit-page" in command
        for command in user_readable.validation_commands
    )


def test_single_instrument_strategy_loop_acceptance_manifest_is_complete() -> None:
    audit = build_single_instrument_strategy_loop_acceptance_audit()

    assert audit.is_complete is True

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path


def test_operations_runbook_acceptance_audit_has_evidence_for_completed_capabilities() -> (
    None
):
    audit = build_operations_runbook_acceptance_audit()

    assert audit.required_count == 19
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]
    assert {criterion.key for criterion in audit.criteria} >= {
        "operations_today_runbook",
        "scheduler_run_persistence",
        "paper_shadow_run_storage",
        "paper_shadow_oms_state_machine",
        "paper_shadow_simulation_outcomes",
        "paper_shadow_run_review_outcomes",
        "paper_shadow_rich_divergence_report",
        "paper_shadow_fallback_review_queue",
        "paper_shadow_manual_handoff_gate",
        "frontend_paper_shadow_next_actions",
        "automation_run_failure_alerts",
        "connector_health_alerts",
        "daily_plan_risk_blocker_alerts",
        "stale_market_data_alerts",
        "account_truth_mismatch_alerts",
        "paper_shadow_order_divergence_alerts",
        "runtime_connector_degradation_alerts",
        "operations_source_control_hygiene",
        "simulation_evidence_safety_docs",
    }

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path

    fallback_review_queue = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "paper_shadow_fallback_review_queue"
    )
    assert "server/services/operations_today.py" in fallback_review_queue.evidence_paths
    assert "tests/test_operations_today.py" in fallback_review_queue.evidence_paths
    assert any(
        "legacy_diverged_run" in command and "missing_simulation" in command
        for command in fallback_review_queue.validation_commands
    )

    scheduler_run_persistence = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "scheduler_run_persistence"
    )
    assert "web/src/app/router.tsx" in scheduler_run_persistence.evidence_paths
    assert "web/src/app/overview-page.test.tsx" in (
        scheduler_run_persistence.evidence_paths
    )
    assert any(
        "overview-page.test.tsx" in command
        and "failed scheduler run recovery" in command
        for command in scheduler_run_persistence.validation_commands
    )

    simulation_outcomes = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "paper_shadow_simulation_outcomes"
    )
    assert "terminal reason" in simulation_outcomes.checkbox_text
    assert any(
        "cancelled_and_expired" in command
        for command in simulation_outcomes.validation_commands
    )

    manual_handoff_gate = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "paper_shadow_manual_handoff_gate"
    )
    assert "server/services/operations_today.py" in manual_handoff_gate.evidence_paths
    assert "web/src/app/overview-page.test.tsx" in manual_handoff_gate.evidence_paths
    assert "web/src/features/decision/components/decision-cockpit-page.test.tsx" in (
        manual_handoff_gate.evidence_paths
    )
    assert any(
        "manual_handoff" in command and "accepted_shadow_divergence" in command
        for command in manual_handoff_gate.validation_commands
    )
    assert any(
        "manual handoff gate" in command
        for command in manual_handoff_gate.validation_commands
    )
    assert any(
        "accepted paper shadow review" in command
        for command in manual_handoff_gate.validation_commands
    )

    frontend_next_actions = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "frontend_paper_shadow_next_actions"
    )
    assert "terminal reason" in frontend_next_actions.checkbox_text
    assert "input snapshot" in frontend_next_actions.checkbox_text
    assert any(
        "terminal paper shadow review reasons" in command
        for command in frontend_next_actions.validation_commands
    )
    assert any(
        "paper shadow review queue" in command
        for command in frontend_next_actions.validation_commands
    )
    assert any(
        "trading-page.test.tsx" in command
        and "terminal paper shadow review reasons" in command
        for command in frontend_next_actions.validation_commands
    )
    assert any(
        "trading-page.test.tsx" in command
        and "surfaces latest paper shadow run evidence" in command
        for command in frontend_next_actions.validation_commands
    )

    source_control_hygiene = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "operations_source_control_hygiene"
    )
    assert ".github/workflows/ci.yml" in source_control_hygiene.evidence_paths
    assert "tests/test_ci_workflow.py" in source_control_hygiene.evidence_paths
    assert any(
        "repository_hygiene" in command
        for command in source_control_hygiene.validation_commands
    )


def test_controlled_broker_bridge_foundation_acceptance_audit_has_evidence() -> None:
    audit = build_controlled_broker_bridge_foundation_acceptance_audit()

    assert audit.required_count == 15
    assert audit.completed_count == audit.required_count
    assert audit.is_complete is True
    assert "not investment advice" in audit.limitations[0]
    assert {criterion.key for criterion in audit.criteria} >= {
        "broker_submission_disabled_default",
        "controlled_bridge_policy_whitelist",
        "manual_ticket_preview_export_dry_run",
        "manual_execution_operator_form_context",
        "manual_execution_preview_draft",
        "manual_execution_evidence_record",
        "gateway_capability_health_contract",
        "gateway_evidence_and_kill_switch_gates",
        "staged_account_facts_and_order_query",
        "decision_cockpit_strategy_promotion_state",
        "default_rejected_cancel_audit",
        "execution_reconciliation_bridge_evidence",
        "manual_ticket_to_reconciliation_audit_chain",
        "decision_cockpit_read_only_bridge_panel",
        "strategy_broker_boundary_static_guard",
    }

    for criterion in audit.criteria:
        assert criterion.is_complete, criterion.key
        assert criterion.evidence_paths, criterion.key
        assert criterion.validation_commands, criterion.key
        for evidence_path in criterion.evidence_paths:
            assert Path(evidence_path).exists(), evidence_path

    reconciliation_evidence = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "execution_reconciliation_bridge_evidence"
    )
    assert "server/services/operations_today.py" in (
        reconciliation_evidence.evidence_paths
    )
    assert "tests/test_operations_today.py" in reconciliation_evidence.evidence_paths
    assert "web/src/app/overview-page.test.tsx" in (
        reconciliation_evidence.evidence_paths
    )
    assert any(
        "manual_execution_reconciliation_review" in command
        for command in reconciliation_evidence.validation_commands
    )
    assert any(
        "manual execution reconciliation review" in command
        for command in reconciliation_evidence.validation_commands
    )

    audit_chain = next(
        criterion
        for criterion in audit.criteria
        if criterion.key == "manual_ticket_to_reconciliation_audit_chain"
    )
    assert "tests/test_execution_reconciliation_service.py" in (
        audit_chain.evidence_paths
    )
    assert "web/src/features/trading/components/trading-page.test.tsx" in (
        audit_chain.evidence_paths
    )
    assert (
        "web/src/features/decision/components/decision-cockpit-page.test.tsx"
        in audit_chain.evidence_paths
    )
    assert "docs/ARCHITECTURE.md" in audit_chain.evidence_paths
    assert any(
        "audit_chain or cost_mismatch" in command
        for command in audit_chain.validation_commands
    )
    assert any(
        "manual versus broker reconciliation differences" in command
        for command in audit_chain.validation_commands
    )
