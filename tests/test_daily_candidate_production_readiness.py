from __future__ import annotations

from copy import deepcopy

from server.ai_runtime.contracts import content_fingerprint
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
)
from server.services.daily_candidate_production_readiness import (
    project_daily_candidate_production_readiness,
    unavailable_daily_candidate_production_readiness,
)


def _inputs() -> tuple[dict, dict]:
    execution_evidence = {
        "schema_version": ("karkinos.daily_candidate_execution_evidence_summary.v1"),
        "status": "not_required",
        "current_execution_closure_fingerprint": "d" * 64,
        "population_scope": "all_current_non_paper_shadow_oms_orders",
        "production_order_count": 0,
        "clear_order_count": 0,
        "reconciled_actual_order_count": 0,
        "reconciled_no_fill_order_count": 0,
        "comparison_coverage_complete": True,
        "blockers": [],
        "actual_orders_attributed_to_trial": False,
        "actual_orders_count_toward_simulated_trial_threshold": False,
        "persisted_evidence_only": True,
        "provider_contact_performed": False,
        "manual_review_required": False,
        "authorizes_execution": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_change_capital_authority": True,
    }
    execution_evidence["evidence_fingerprint"] = content_fingerprint(execution_evidence)
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
            "operator_checklist": [
                {
                    "step": 1,
                    "gate": "runtime_window",
                    "action": "keep_monitor_running_and_wait_for_reviewed_window",
                    "completion_mode": "canonical_runtime",
                    "blockers": ["daily_candidate_decision_window_not_open"],
                    "evidence_contract_version": (
                        "karkinos.daily_candidate_operator_evidence.v1"
                    ),
                    "required_evidence": [
                        "loaded_local_daily_candidate_service_and_live_monitor_task"
                    ],
                    "completion_criteria": [
                        "exactly_one_fail_closed_attempt_is_due_in_reviewed_window"
                    ],
                    "accepted_evidence_authority": (
                        "canonical_persisted_evidence_only"
                    ),
                    "owner_attestation_is_financial_fact": False,
                    "private_xls_rows_required": False,
                    "private_account_identifiers_required": False,
                    "automatic_action_performed": False,
                    "authorizes_execution": False,
                    "changes_capital_authority": False,
                }
            ],
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
            "schema_version": "karkinos.daily_candidate_trial.v2",
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
            "current_execution_evidence": execution_evidence,
            "background_schedule": {
                "schema_version": "karkinos.daily_candidate_background_schedule.v3",
                "status": "waiting_for_decision_window",
                "run_date": "2026-08-21",
                "next_reviewed_window": {
                    "schema_version": (
                        "karkinos.daily_candidate_next_reviewed_window.v1"
                    ),
                    "status": "available",
                    "market_date": "2026-08-21",
                    "window_start": "2026-08-21T09:35:00+08:00",
                    "window_end": "2026-08-21T09:45:00+08:00",
                    "is_current_market_date": True,
                    "official_calendar_verified": True,
                    "blockers": [],
                    "provider_contact_performed": False,
                    "database_writes_performed": False,
                    "permits_retry_or_backfill": False,
                    "changes_attempt_eligibility": False,
                    "broker_submission_enabled": False,
                    "authorizes_execution": False,
                    "changes_capital_authority": False,
                },
            },
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
            "schema_version": "karkinos.ai.shadow_research_policy.v3",
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
    assert report["daily_operation"]["operator_checklist_status"] == "available"
    assert report["daily_operation"]["first_blocking_gate"] == "runtime_window"
    assert report["daily_operation"]["blocking_gate_count"] == 1
    assert report["daily_operation"]["next_reviewed_window"]["market_date"] == (
        "2026-08-21"
    )
    assert (
        report["daily_operation"]["next_reviewed_window"]["permits_retry_or_backfill"]
        is False
    )
    assert report["research_cycle"]["status"] == (
        "ready_for_five_sequential_iterations"
    )
    assert report["forward_trial"]["qualifying_trading_day_count"] == 7
    assert (
        report["forward_trial"]["execution_reconciliation"][
            "comparison_coverage_complete"
        ]
        is True
    )
    assert (
        report["forward_trial"]["execution_reconciliation"][
            "actual_orders_attributed_to_trial"
        ]
        is False
    )
    assert report["raw_xls_rows_included"] is False
    assert report["private_account_identifiers_included"] is False
    assert report["provider_contact_performed"] is False
    assert report["database_writes_performed"] is False
    assert report["authorizes_execution"] is False


def test_live_readiness_compacts_repeated_candidate_blockers_for_operator() -> None:
    cockpit, research = _inputs()
    preflight = cockpit["daily_candidate_financial_preflight"]
    preflight["financial_gate_status"] = "blocked"
    preflight["financial_blockers"] = [
        "candidate_0:strategy_promotion_not_pass",
        "candidate_0:strategy_human_approval_missing",
        "candidate_1:strategy_promotion_not_pass",
        "candidate_1:strategy_human_approval_missing",
        "reviewed_fee_schedule_review_missing",
    ]
    preflight["operator_checklist"] = [
        {
            "step": 1,
            "gate": "strategy",
            "action": "promote_evidence_bound_strategy_for_paper_shadow",
            "completion_mode": "human_review",
            "blockers": list(preflight["financial_blockers"][:4]),
            "evidence_contract_version": (
                "karkinos.daily_candidate_operator_evidence.v1"
            ),
            "required_evidence": [
                "deterministic_local_backtest_and_promotion_evidence"
            ],
            "completion_criteria": [
                "promoted_strategy_replays_from_frozen_data_and_current_fee_review"
            ],
            "accepted_evidence_authority": "canonical_persisted_evidence_only",
            "owner_attestation_is_financial_fact": False,
            "private_xls_rows_required": False,
            "private_account_identifiers_required": False,
            "automatic_action_performed": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
        {
            "step": 2,
            "gate": "reviewed_fees",
            "action": "review_account_specific_fee_schedule",
            "completion_mode": "human_review",
            "blockers": ["reviewed_fee_schedule_review_missing"],
            "evidence_contract_version": (
                "karkinos.daily_candidate_operator_evidence.v1"
            ),
            "required_evidence": ["human_accepted_fee_effective_date_window"],
            "completion_criteria": ["fee_review_is_bounded_and_revocable"],
            "accepted_evidence_authority": "canonical_persisted_evidence_only",
            "owner_attestation_is_financial_fact": False,
            "private_xls_rows_required": False,
            "private_account_identifiers_required": False,
            "automatic_action_performed": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
    ]

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["daily_operation"]["blocking_gate_count"] == 2
    strategy_step = report["daily_operation"]["operator_checklist"][0]
    assert strategy_step["blocker_count"] == 4
    assert strategy_step["unique_blocker_count"] == 2
    assert strategy_step["blocker_summary"] == [
        {
            "code": "strategy_promotion_not_pass",
            "occurrence_count": 2,
            "affected_candidate_count": 2,
        },
        {
            "code": "strategy_human_approval_missing",
            "occurrence_count": 2,
            "affected_candidate_count": 2,
        },
    ]
    assert strategy_step["automatic_action_performed"] is False
    assert strategy_step["authorizes_execution"] is False
    assert strategy_step["changes_capital_authority"] is False


def test_live_readiness_fails_closed_on_invalid_operator_checklist() -> None:
    cockpit, research = _inputs()
    cockpit["daily_candidate_financial_preflight"]["operator_checklist"][0][
        "authorizes_execution"
    ] = True

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["ready_for_production_operation"] is False
    assert report["source_contract_blockers"] == [
        "preflight_operator_checklist_contract_invalid"
    ]
    assert report["daily_operation"]["operator_checklist_status"] == "invalid"
    assert report["daily_operation"]["operator_checklist"] == []


def test_live_readiness_fails_closed_on_execution_evidence_drift() -> None:
    cockpit, research = _inputs()
    cockpit["daily_candidate_trial"]["current_execution_evidence"][
        "production_order_count"
    ] = 1

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["ready_for_production_operation"] is False
    assert (
        "trial_current_execution_evidence_contract_invalid"
        in report["source_contract_blockers"]
    )
    assert report["daily_operation"]["status"] == "no_action"
    assert report["forward_trial"]["execution_reconciliation"]["status"] == ("blocked")


def test_live_readiness_hides_unsafe_next_window_without_changing_schedule() -> None:
    cockpit, research = _inputs()
    trial = cockpit["daily_candidate_trial"]
    trial["background_schedule"]["next_reviewed_window"][
        "permits_retry_or_backfill"
    ] = True

    report = project_daily_candidate_production_readiness(
        cockpit=cockpit,
        research_status=research,
    )

    assert report["ready_for_production_operation"] is True
    assert report["daily_operation"]["status"] == ("standing_by_for_reviewed_window")
    assert report["daily_operation"]["next_reviewed_window"]["status"] == (
        "unavailable"
    )
    assert report["daily_operation"]["next_reviewed_window"]["blockers"] == [
        "next_reviewed_window_contract_invalid"
    ]
    assert (
        report["daily_operation"]["next_reviewed_window"]["permits_retry_or_backfill"]
        is False
    )


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


def test_unavailable_live_readiness_exposes_only_non_authorizing_recovery() -> None:
    report = unavailable_daily_candidate_production_readiness()

    daily_operation = report["daily_operation"]
    assert daily_operation["operator_checklist_status"] == "unavailable"
    assert daily_operation["first_blocking_gate"] == "source_evidence"
    assert daily_operation["first_safe_action"] == (
        "start_and_verify_local_karkinos_service"
    )
    assert daily_operation["operator_checklist"] == [
        {
            "step": 1,
            "gate": "source_evidence",
            "action": "start_and_verify_local_karkinos_service",
            "completion_mode": "canonical_runtime",
            "blocker_count": 1,
            "unique_blocker_count": 1,
            "blocker_summary": [
                {
                    "code": "local_karkinos_service_unreachable",
                    "occurrence_count": 1,
                    "affected_candidate_count": 0,
                }
            ],
            "evidence_contract_version": (
                "karkinos.daily_candidate_operator_evidence.v1"
            ),
            "required_evidence": ["reachable_loopback_karkinos_service"],
            "completion_criteria": [
                "local_service_liveness_and_persisted_sources_are_verified"
            ],
            "accepted_evidence_authority": "canonical_persisted_evidence_only",
            "owner_attestation_is_financial_fact": False,
            "private_xls_rows_required": False,
            "private_account_identifiers_required": False,
            "automatic_action_performed": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }
    ]
