from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_acceptance_audit.py"


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd or REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_acceptance_audit_cli_outputs_parseable_stdout_json() -> None:
    result = _run_cli()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["generated_at"]
    assert payload["selected_audit"] == "all"
    assert payload["overall_is_complete"] is True
    assert payload["audits"]


def test_acceptance_audit_cli_research_evidence_filter_outputs_one_audit() -> None:
    result = _run_cli("--audit", "research_evidence")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "research_evidence"
    assert [audit["key"] for audit in payload["audits"]] == ["research_evidence"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 12
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]


def test_acceptance_audit_cli_account_truth_filter_outputs_one_audit() -> None:
    result = _run_cli("--audit", "account_truth")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "account_truth"
    assert [audit["key"] for audit in payload["audits"]] == ["account_truth"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 15
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]


def test_acceptance_audit_cli_account_truth_review_filter_outputs_one_audit() -> None:
    result = _run_cli("--audit", "account_truth_review")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "account_truth_review"
    assert [audit["key"] for audit in payload["audits"]] == ["account_truth_review"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 13
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]


def test_acceptance_audit_cli_strategy_assignment_filter_outputs_one_audit() -> None:
    result = _run_cli("--audit", "strategy_assignment")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "strategy_assignment"
    assert [audit["key"] for audit in payload["audits"]] == ["strategy_assignment"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 15
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]


def test_acceptance_audit_cli_market_data_reliability_filter_outputs_one_audit() -> (
    None
):
    result = _run_cli("--audit", "market_data_reliability")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "market_data_reliability"
    assert [audit["key"] for audit in payload["audits"]] == ["market_data_reliability"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 13
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]


def test_acceptance_audit_cli_broker_fee_cost_basis_filter_outputs_one_audit() -> None:
    result = _run_cli("--audit", "broker_fee_cost_basis")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "broker_fee_cost_basis"
    assert [audit["key"] for audit in payload["audits"]] == ["broker_fee_cost_basis"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 16
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]
    assert {criterion["key"] for criterion in audit["criteria"]} >= {
        "web_strategy_contribution_user_readable_surface",
        "shared_public_ledger_formatter_surface_contract",
        "public_ledger_surfaces_hide_internal_values",
        "public_ledger_notes_keep_core_facts_structured",
        "portfolio_cost_views_distinguish_local_and_broker_cost_basis",
        "sell_side_net_proceeds_broker_cost_basis",
        "backend_fee_cost_basis_deterministic_tests",
        "frontend_fee_cost_basis_display_tests",
    }


def test_acceptance_audit_cli_single_instrument_strategy_loop_filter_outputs_one_audit() -> (
    None
):
    result = _run_cli("--audit", "single_instrument_strategy_loop")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "single_instrument_strategy_loop"
    assert [audit["key"] for audit in payload["audits"]] == [
        "single_instrument_strategy_loop"
    ]
    audit = payload["audits"][0]
    assert audit["required_count"] == 10
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]


def test_acceptance_audit_cli_operations_runbook_filter_outputs_one_audit() -> None:
    result = _run_cli("--audit", "operations_runbook")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "operations_runbook"
    assert [audit["key"] for audit in payload["audits"]] == ["operations_runbook"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 17
    assert audit["completed_count"] == audit["required_count"]
    assert {criterion["key"] for criterion in audit["criteria"]} >= {
        "operations_today_runbook",
        "scheduler_run_persistence",
        "paper_shadow_run_storage",
        "paper_shadow_oms_state_machine",
        "paper_shadow_simulation_outcomes",
        "paper_shadow_run_review_outcomes",
        "paper_shadow_rich_divergence_report",
        "paper_shadow_fallback_review_queue",
        "frontend_paper_shadow_next_actions",
        "automation_run_failure_alerts",
        "connector_health_alerts",
        "daily_plan_risk_blocker_alerts",
        "stale_market_data_alerts",
        "account_truth_mismatch_alerts",
        "paper_shadow_order_divergence_alerts",
        "runtime_connector_degradation_alerts",
        "simulation_evidence_safety_docs",
    }


def test_acceptance_audit_cli_controlled_broker_bridge_foundation_filter_outputs_one_audit() -> (
    None
):
    result = _run_cli("--audit", "controlled_broker_bridge_foundation")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "controlled_broker_bridge_foundation"
    assert [audit["key"] for audit in payload["audits"]] == [
        "controlled_broker_bridge_foundation"
    ]
    audit = payload["audits"][0]
    assert audit["required_count"] == 14
    assert audit["completed_count"] == audit["required_count"]
    assert {criterion["key"] for criterion in audit["criteria"]} >= {
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
        "decision_cockpit_read_only_bridge_panel",
        "strategy_broker_boundary_static_guard",
    }


def test_acceptance_audit_cli_all_outputs_every_registered_audit() -> None:
    result = _run_cli("--audit", "all")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert [audit["key"] for audit in payload["audits"]] == [
        "profit_discipline",
        "strategy_lab",
        "research_evidence",
        "account_truth",
        "account_truth_review",
        "strategy_assignment",
        "market_data_reliability",
        "broker_fee_cost_basis",
        "single_instrument_strategy_loop",
        "operations_runbook",
        "controlled_broker_bridge_foundation",
    ]
    assert all(audit["is_complete"] for audit in payload["audits"])


def test_acceptance_audit_cli_pretty_keeps_valid_json() -> None:
    result = _run_cli("--audit", "all", "--pretty")

    assert result.returncode == 0, result.stderr
    assert "\n  " in result.stdout
    payload = json.loads(result.stdout)
    assert payload["overall_is_complete"] is True


def test_acceptance_audit_cli_does_not_write_default_output_file(
    tmp_path: Path,
) -> None:
    result = _run_cli("--audit", "research_evidence", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["selected_audit"] == "research_evidence"
    assert list(tmp_path.iterdir()) == []
