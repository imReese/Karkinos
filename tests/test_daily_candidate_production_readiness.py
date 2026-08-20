from __future__ import annotations

from copy import deepcopy

from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
)
from server.services.daily_candidate_production_readiness import (
    project_daily_candidate_production_readiness,
    unavailable_daily_candidate_production_readiness,
)


def _inputs() -> tuple[dict, dict]:
    cockpit = {
        "schema_version": "karkinos.automation_cockpit.v4",
        "broker_submission_enabled": False,
        "daily_candidate_financial_preflight": {
            "schema_version": "karkinos.daily_candidate_financial_preflight.v1",
            "status": "waiting_for_decision_window",
            "run_date": "2026-08-21",
            "financial_gate_status": "pass",
            "operational_gate_status": "pass",
            "eligible_to_start_manual_attempt": False,
            "eligible_for_background_attempt": False,
            "financial_blockers": [],
            "no_action_reasons": ["daily_candidate_decision_window_not_open"],
            "next_safe_action": "keep_monitor_running_and_wait_for_reviewed_window",
            "preflight_fingerprint": "a" * 64,
            "provider_contact_performed": False,
            "database_writes_performed": False,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
        "daily_candidate_runtime": {
            "schema_version": "karkinos.daily_candidate_runtime_status.v1",
            "status": "monitor_running_waiting",
            "background_monitor_running": True,
            "schedule_status": "waiting_for_decision_window",
            "operational_blockers": ["daily_candidate_decision_window_not_open"],
            "provider_contact_performed": False,
            "database_writes_performed": False,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
        "daily_candidate_trial": {
            "schema_version": "karkinos.daily_candidate_trial.v1",
            "status": "collecting_forward_operating_evidence",
            "trial_epoch_id": "b" * 64,
            "qualifying_trading_day_count": 7,
            "target_qualifying_trading_days": 20,
            "simulated_order_count": 18,
            "target_simulated_orders": 50,
            "remaining_trading_days": 13,
            "remaining_simulated_orders": 32,
            "eligible_for_human_go_no_go_review": False,
            "latest_review": None,
            "blockers": [
                "qualifying_trading_days_insufficient",
                "simulated_order_count_insufficient",
            ],
            "run_scan_truncated": False,
            "trial_fingerprint": "c" * 64,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
    }
    research = {
        "schema_version": "karkinos.ai.shadow_research_automation.v1",
        "policy": {
            "schema_version": "karkinos.ai.shadow_research_policy.v2",
            "enabled": True,
            "max_candidates_per_run": 5,
            "max_provider_calls_per_market_date": 10,
            "daily_token_budget": None,
            "token_budget_mode": "unbounded_daily",
            "authorization": SHADOW_RESEARCH_POLICY_CONFIRMATION,
            "require_complete_account_evidence": True,
        },
        "automatic_strategy_replacement_enabled": False,
        "production_strategy_mutation_enabled": False,
        "broker_submission_enabled": False,
    }
    return cockpit, research


def test_live_readiness_accepts_waiting_service_and_collects_forward_evidence() -> None:
    cockpit, research = _inputs()

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["status"] == "collecting_forward_operating_evidence"
    assert report["ready_for_production_operation"] is True
    assert report["daily_operation"]["status"] == ("standing_by_for_reviewed_window")
    assert report["daily_operation"]["blockers"] == []
    assert report["research_cycle"]["status"] == (
        "ready_for_five_sequential_iterations"
    )
    assert report["forward_trial"]["qualifying_trading_day_count"] == 7
    assert report["raw_xls_rows_included"] is False
    assert report["private_account_identifiers_included"] is False
    assert report["provider_contact_performed"] is False
    assert report["database_writes_performed"] is False
    assert report["authorizes_execution"] is False


def test_live_readiness_fails_closed_on_financial_or_runtime_blockers() -> None:
    cockpit, research = _inputs()
    preflight = cockpit["daily_candidate_financial_preflight"]
    preflight["financial_gate_status"] = "blocked"
    preflight["financial_blockers"] = ["account_truth_snapshot_stale"]
    runtime = cockpit["daily_candidate_runtime"]
    runtime["background_monitor_running"] = False
    runtime["operational_blockers"] = [
        "daily_candidate_background_monitor_task_missing"
    ]

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["status"] == "no_action_not_production_ready"
    assert report["ready_for_production_operation"] is False
    assert report["daily_operation"]["status"] == "no_action"
    assert report["daily_operation"]["blockers"] == [
        "account_truth_snapshot_stale",
        "daily_candidate_background_monitor_task_missing",
        "daily_candidate_background_monitor_not_running",
    ]


def test_live_readiness_requires_exact_five_round_research_policy() -> None:
    cockpit, research = _inputs()
    research["policy"].update(
        {
            "max_candidates_per_run": 1,
            "max_provider_calls_per_market_date": 2,
            "daily_token_budget": 2_252_800,
            "token_budget_mode": "legacy_bounded_daily",
            "authorization": "legacy_authorization",
        }
    )

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["ready_for_production_operation"] is False
    assert report["research_cycle"]["status"] == "blocked_by_policy"
    assert report["research_cycle"]["blockers"] == [
        "five_sequential_iteration_count_not_authorized",
        "ten_provider_call_limit_not_authorized",
        "unbounded_daily_token_policy_not_authorized",
        "five_sequential_iteration_authorization_missing",
    ]


def test_live_readiness_surfaces_trial_review_without_granting_authority() -> None:
    cockpit, research = _inputs()
    trial = cockpit["daily_candidate_trial"]
    trial.update(
        {
            "qualifying_trading_day_count": 20,
            "simulated_order_count": 50,
            "remaining_trading_days": 0,
            "remaining_simulated_orders": 0,
            "eligible_for_human_go_no_go_review": True,
            "blockers": [],
            "latest_review": {
                "decision": "go_to_bounded_manual_trial",
            },
        }
    )

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["status"] == "human_trial_review_recorded_without_authority"
    assert report["forward_trial"]["status"] == (
        "human_review_recorded_without_authority"
    )
    assert report["forward_trial"]["latest_review_decision"] == (
        "go_to_bounded_manual_trial"
    )
    assert report["broker_submission_enabled"] is False
    assert report["changes_capital_authority"] is False


def test_live_readiness_rejects_boundary_drift() -> None:
    cockpit, research = _inputs()
    drifted = deepcopy(cockpit)
    drifted["daily_candidate_financial_preflight"]["database_writes_performed"] = True

    report = project_daily_candidate_production_readiness(
        cockpit=drifted,
        research_status=research,
    )

    assert report["ready_for_production_operation"] is False
    assert report["non_authority_boundary_blockers"] == [
        "preflight_database_writes_performed_boundary_invalid"
    ]


def test_unavailable_live_readiness_is_sanitized_no_action() -> None:
    report = unavailable_daily_candidate_production_readiness(
        blocker="local_karkinos_service_unreachable"
    )

    assert report["status"] == "no_action_not_production_ready"
    assert report["service_liveness_proven_by_local_api"] is False
    assert report["daily_operation"]["blockers"] == [
        "local_karkinos_service_unreachable"
    ]
    assert report["raw_xls_rows_included"] is False
    assert report["private_account_identifiers_included"] is False
    assert report["broker_submission_enabled"] is False
