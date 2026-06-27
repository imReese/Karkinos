from __future__ import annotations

from pathlib import Path

from analytics.acceptance_audit import (
    build_acceptance_audit,
    build_account_truth_acceptance_audit,
    build_account_truth_review_acceptance_audit,
    build_broker_fee_cost_basis_acceptance_audit,
    build_market_data_reliability_acceptance_audit,
    build_research_evidence_acceptance_audit,
    build_single_instrument_strategy_loop_acceptance_audit,
    build_strategy_assignment_acceptance_audit,
    build_strategy_lab_acceptance_audit,
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


def test_goal_acceptance_checkboxes_match_acceptance_audit() -> None:
    audit = build_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    profit_discipline_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.2", 1
    )[1].split("## v0.3", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in profit_discipline_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in profit_discipline_acceptance


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


def test_strategy_lab_goal_acceptance_checkboxes_match_audit() -> None:
    audit = build_strategy_lab_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    strategy_lab_acceptance = roadmap_text.split("### Acceptance Criteria for v0.4", 1)[
        1
    ].split("## Target for v0.5", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in strategy_lab_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in strategy_lab_acceptance


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


def test_research_evidence_goal_acceptance_checkboxes_match_audit() -> None:
    audit = build_research_evidence_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    research_evidence_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.5", 1
    )[1].split("## Target for v0.6", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in research_evidence_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in research_evidence_acceptance


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


def test_account_truth_goal_completed_checkboxes_match_audit() -> None:
    audit = build_account_truth_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    account_truth_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.6", 1
    )[1].split("## Target for v0.7", 1)[0]

    assert audit.is_complete is True
    for criterion in audit.criteria:
        assert criterion.checkbox_text in account_truth_acceptance

    completed_checkboxes = [
        line
        for line in account_truth_acceptance.splitlines()
        if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)


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


def test_account_truth_review_goal_checkboxes_match_audit() -> None:
    audit = build_account_truth_review_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    account_truth_review_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.7", 1
    )[1].split("## Future Candidate Milestones", 1)[0]

    assert audit.is_complete is True
    assert "* [ ]" not in account_truth_review_acceptance
    for criterion in audit.criteria:
        assert criterion.checkbox_text in account_truth_review_acceptance

    completed_checkboxes = [
        line
        for line in account_truth_review_acceptance.splitlines()
        if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)


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


def test_strategy_assignment_goal_completed_checkboxes_match_audit() -> None:
    audit = build_strategy_assignment_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    strategy_assignment_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v0.8", 1
    )[1].split("## Professional Quant Platform Track", 1)[0]

    assert audit.is_complete is True
    for criterion in audit.criteria:
        assert criterion.checkbox_text in strategy_assignment_acceptance

    completed_checkboxes = [
        line
        for line in strategy_assignment_acceptance.splitlines()
        if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)


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


def test_market_data_reliability_goal_completed_checkboxes_match_audit() -> None:
    audit = build_market_data_reliability_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    market_data_acceptance = roadmap_text.split("### Acceptance Criteria for v0.9", 1)[
        1
    ].split("## Target for v1.0", 1)[0]

    assert audit.is_complete is True
    for criterion in audit.criteria:
        assert criterion.checkbox_text in market_data_acceptance

    completed_checkboxes = [
        line for line in market_data_acceptance.splitlines() if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)


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


def test_broker_fee_cost_basis_goal_completed_checkboxes_match_audit() -> None:
    audit = build_broker_fee_cost_basis_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    broker_fee_cost_basis_acceptance = roadmap_text.split(
        "### Acceptance Criteria for v1.4", 1
    )[1].split(
        "### Active Goal Audit: Data-Trusted Single-Instrument Strategy Loop",
        1,
    )[
        0
    ]

    assert audit.is_complete is True
    for criterion in audit.criteria:
        assert criterion.checkbox_text in broker_fee_cost_basis_acceptance

    completed_checkboxes = [
        line
        for line in broker_fee_cost_basis_acceptance.splitlines()
        if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)


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
        "copy public-labels holding-detail-page decision-cockpit-page"
        in command
        for command in user_readable.validation_commands
    )


def test_single_instrument_strategy_loop_goal_checkboxes_match_audit() -> None:
    audit = build_single_instrument_strategy_loop_acceptance_audit()
    roadmap_text = Path("docs/ROADMAP.md").read_text()
    strategy_loop_acceptance = roadmap_text.split(
        "### Acceptance Criteria for Data-Trusted Single-Instrument Strategy Loop",
        1,
    )[1].split("## Target for v1.5", 1)[0]

    assert audit.is_complete is True
    for criterion in audit.criteria:
        assert criterion.checkbox_text in strategy_loop_acceptance

    completed_checkboxes = [
        line
        for line in strategy_loop_acceptance.splitlines()
        if line.startswith("* [x]")
    ]
    assert audit.required_count == len(completed_checkboxes)
