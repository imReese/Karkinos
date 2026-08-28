"""Sanitized live-readiness projection for production daily candidates."""

from __future__ import annotations

from typing import Any

from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
)
from server.services.daily_candidate_production_readiness_evidence import (
    CANONICAL_EVIDENCE_AUTHORITY as _CANONICAL_EVIDENCE_AUTHORITY,
)
from server.services.daily_candidate_production_readiness_evidence import (
    OPERATOR_EVIDENCE_CONTRACT_VERSION as _OPERATOR_EVIDENCE_CONTRACT_VERSION,
)
from server.services.daily_candidate_production_readiness_evidence import (
    execution_evidence_contract_blockers as _execution_evidence_contract_blockers,
)
from server.services.daily_candidate_production_readiness_evidence import (
    operator_checklist_contract_blockers as _operator_checklist_contract_blockers,
)
from server.services.daily_candidate_production_readiness_evidence import (
    project_execution_evidence as _project_execution_evidence,
)
from server.services.daily_candidate_production_readiness_evidence import (
    project_next_reviewed_window as _project_next_reviewed_window,
)
from server.services.daily_candidate_production_readiness_evidence import (
    project_operator_checklist as _project_operator_checklist,
)
from server.services.daily_candidate_production_readiness_evidence import (
    summarize_operator_blockers as _summarize_operator_blockers,
)
from server.services.daily_candidate_production_readiness_evidence import (
    unavailable_next_reviewed_window_projection as _unavailable_next_reviewed_window_projection,
)
from server.services.daily_candidate_readiness_support import (
    fingerprint as _fingerprint,
)
from server.services.daily_candidate_readiness_support import (
    is_nonnegative_int as _is_nonnegative_int,
)
from server.services.daily_candidate_readiness_support import (
    is_safe_code as _is_safe_code,
)
from server.services.daily_candidate_readiness_support import (
    is_safe_code_list as _is_safe_code_list,
)
from server.services.daily_candidate_readiness_support import is_sha256 as _is_sha256
from server.services.daily_candidate_readiness_support import mapping as _mapping
from server.services.daily_candidate_readiness_support import (
    matches_fingerprint as _matches_fingerprint,
)
from server.services.daily_candidate_readiness_support import (
    non_authority_boundary_blockers as _non_authority_boundary_blockers,
)
from server.services.daily_candidate_readiness_support import (
    nonnegative_int as _nonnegative_int,
)
from server.services.daily_candidate_readiness_support import (
    research_policy_blockers as _research_policy_blockers,
)
from server.services.daily_candidate_readiness_support import safe_code as _safe_code
from server.services.daily_candidate_readiness_support import (
    safe_fingerprint as _safe_fingerprint,
)
from server.services.daily_candidate_readiness_support import (
    schema_blockers as _schema_blockers,
)
from server.services.daily_candidate_readiness_support import strings as _strings
from server.services.daily_candidate_readiness_support import unique as _unique

DAILY_CANDIDATE_PRODUCTION_READINESS_SCHEMA_VERSION = (
    "karkinos.daily_candidate_production_readiness.v2"
)

_EXPECTED_SCHEMAS = {
    "cockpit": "karkinos.automation_cockpit.v4",
    "preflight": "karkinos.daily_candidate_financial_preflight.v1",
    "runtime": "karkinos.daily_candidate_runtime_status.v1",
    "trial": "karkinos.daily_candidate_trial.v2",
    "research": "karkinos.ai.shadow_research_automation.v1",
    "research_policy": "karkinos.ai.shadow_research_policy.v3",
}
_NON_FATAL_SCHEDULE_REASONS = {
    "daily_candidate_attempt_already_recorded",
    "daily_candidate_decision_window_not_open",
    "daily_candidate_run_already_recorded",
    "market_calendar_not_trading_day",
}


def project_daily_candidate_production_readiness(
    *,
    cockpit: dict[str, Any],
    research_status: dict[str, Any],
) -> dict[str, Any]:
    """Project current live readiness without copying private financial facts."""

    preflight = _mapping(cockpit.get("daily_candidate_financial_preflight"))
    runtime = _mapping(cockpit.get("daily_candidate_runtime"))
    trial = _mapping(cockpit.get("daily_candidate_trial"))
    execution_evidence = _mapping(trial.get("current_execution_evidence"))
    policy = _mapping(research_status.get("policy"))

    source_contract_blockers = _schema_blockers(
        _EXPECTED_SCHEMAS,
        cockpit=cockpit,
        preflight=preflight,
        runtime=runtime,
        trial=trial,
        research=research_status,
        research_policy=policy,
    )
    source_contract_blockers.extend(_operator_checklist_contract_blockers(preflight))
    execution_evidence_contract_blockers = _execution_evidence_contract_blockers(
        execution_evidence
    )
    source_contract_blockers.extend(execution_evidence_contract_blockers)
    source_contract_blockers = _unique(source_contract_blockers)
    boundary_blockers = _non_authority_boundary_blockers(
        cockpit=cockpit,
        preflight=preflight,
        runtime=runtime,
        trial=trial,
        research=research_status,
    )

    financial_blockers = _strings(preflight.get("financial_blockers"))
    runtime_blockers = _strings(runtime.get("operational_blockers"))
    hard_runtime_blockers = [
        blocker
        for blocker in runtime_blockers
        if blocker not in _NON_FATAL_SCHEDULE_REASONS
    ]
    schedule_reasons = [
        reason
        for reason in _strings(preflight.get("no_action_reasons"))
        if reason in _NON_FATAL_SCHEDULE_REASONS
    ]
    execution_evidence_ready = bool(
        not execution_evidence_contract_blockers
        and execution_evidence.get("comparison_coverage_complete") is True
    )
    execution_evidence_blockers = (
        [] if execution_evidence_ready else ["current_execution_evidence_incomplete"]
    )
    daily_operation_blockers = _unique(
        [
            *source_contract_blockers,
            *boundary_blockers,
            *financial_blockers,
            *hard_runtime_blockers,
            *execution_evidence_blockers,
        ]
    )
    monitor_running = runtime.get("background_monitor_running") is True
    financial_clear = preflight.get("financial_gate_status") == "pass"
    if not monitor_running:
        daily_operation_blockers.append(
            "daily_candidate_background_monitor_not_running"
        )
    daily_operation_blockers = _unique(daily_operation_blockers)
    operator_checklist = _project_operator_checklist(preflight)
    first_operator_step = operator_checklist[0] if operator_checklist else {}
    first_blocking_step = next(
        (item for item in operator_checklist if item["blocker_count"] > 0),
        {},
    )

    if daily_operation_blockers:
        daily_operation_status = "no_action"
    elif preflight.get("eligible_for_background_attempt") is True:
        daily_operation_status = "ready_for_current_background_attempt"
    elif preflight.get("eligible_to_start_manual_attempt") is True:
        daily_operation_status = "ready_for_current_manual_paper_shadow_attempt"
    else:
        daily_operation_status = "standing_by_for_reviewed_window"

    research_blockers = _research_policy_blockers(
        policy,
        max_candidates=SHADOW_RESEARCH_MAX_CANDIDATES,
        max_provider_calls=SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
        unbounded_token_budget_mode=SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
        policy_confirmation=SHADOW_RESEARCH_POLICY_CONFIRMATION,
    )
    research_cycle_status = (
        "ready_for_five_sequential_iterations"
        if not research_blockers and not source_contract_blockers
        else "blocked_by_policy"
    )

    trial_blockers = _strings(trial.get("blockers"))
    next_reviewed_window = _project_next_reviewed_window(trial)
    trial_eligible = trial.get("eligible_for_human_go_no_go_review") is True
    latest_review = _mapping(trial.get("latest_review"))
    if latest_review:
        forward_trial_status = "human_review_recorded_without_authority"
    elif trial_eligible:
        forward_trial_status = "eligible_for_human_go_no_go_review"
    else:
        forward_trial_status = "collecting_forward_operating_evidence"

    ready_for_production_operation = bool(
        not source_contract_blockers
        and not boundary_blockers
        and financial_clear
        and monitor_running
        and not hard_runtime_blockers
        and execution_evidence_ready
        and not research_blockers
        and trial.get("run_scan_truncated") is False
    )
    if not ready_for_production_operation:
        goal_status = "no_action_not_production_ready"
    elif latest_review:
        goal_status = "human_trial_review_recorded_without_authority"
    elif trial_eligible:
        goal_status = "eligible_for_human_go_no_go_review"
    else:
        goal_status = "collecting_forward_operating_evidence"

    core = {
        "schema_version": DAILY_CANDIDATE_PRODUCTION_READINESS_SCHEMA_VERSION,
        "status": goal_status,
        "ready_for_production_operation": ready_for_production_operation,
        "service_liveness_proven_by_local_api": True,
        "daily_operation": {
            "status": daily_operation_status,
            "run_date": preflight.get("run_date"),
            "financial_gate_status": preflight.get("financial_gate_status"),
            "operational_gate_status": preflight.get("operational_gate_status"),
            "background_monitor_running": monitor_running,
            "schedule_status": runtime.get("schedule_status"),
            "eligible_for_background_attempt": (
                preflight.get("eligible_for_background_attempt") is True
            ),
            "eligible_to_start_manual_attempt": (
                preflight.get("eligible_to_start_manual_attempt") is True
            ),
            "blockers": daily_operation_blockers,
            "blocking_summary": _summarize_operator_blockers(daily_operation_blockers),
            "schedule_reasons": _unique(schedule_reasons),
            "next_safe_action": str(preflight.get("next_safe_action") or "no_action"),
            "preflight_fingerprint": _safe_fingerprint(
                preflight.get("preflight_fingerprint")
            ),
            "next_reviewed_window": next_reviewed_window,
            "operator_checklist_status": (
                "available" if operator_checklist else "invalid"
            ),
            "blocking_gate_count": sum(
                1 for item in operator_checklist if item["blocker_count"] > 0
            ),
            "first_blocking_step": first_blocking_step.get("step"),
            "first_blocking_gate": first_blocking_step.get("gate"),
            "first_safe_action": first_operator_step.get("action"),
            "operator_checklist": operator_checklist,
        },
        "research_cycle": {
            "status": research_cycle_status,
            "enabled": policy.get("enabled") is True,
            "configured_sequential_iterations": _nonnegative_int(
                policy.get("max_candidates_per_run")
            ),
            "configured_provider_call_limit": _nonnegative_int(
                policy.get("max_provider_calls_per_market_date")
            ),
            "configured_daily_token_budget": policy.get("daily_token_budget"),
            "configured_token_budget_mode": policy.get("token_budget_mode"),
            "required_sequential_iterations": SHADOW_RESEARCH_MAX_CANDIDATES,
            "required_provider_call_limit": SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
            "required_token_budget_mode": (SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED),
            "blockers": research_blockers,
            "automatic_strategy_replacement_enabled": False,
        },
        "forward_trial": {
            "status": forward_trial_status,
            "trial_epoch_id": _safe_fingerprint(trial.get("trial_epoch_id")),
            "qualifying_trading_day_count": _nonnegative_int(
                trial.get("qualifying_trading_day_count")
            ),
            "target_qualifying_trading_days": _nonnegative_int(
                trial.get("target_qualifying_trading_days")
            ),
            "simulated_order_count": _nonnegative_int(
                trial.get("simulated_order_count")
            ),
            "target_simulated_orders": _nonnegative_int(
                trial.get("target_simulated_orders")
            ),
            "remaining_trading_days": _nonnegative_int(
                trial.get("remaining_trading_days")
            ),
            "remaining_simulated_orders": _nonnegative_int(
                trial.get("remaining_simulated_orders")
            ),
            "eligible_for_human_go_no_go_review": trial_eligible,
            "latest_review_decision": (
                str(latest_review.get("decision") or "") or None
            ),
            "execution_reconciliation": _project_execution_evidence(execution_evidence),
            "blockers": trial_blockers,
            "trial_fingerprint": _safe_fingerprint(trial.get("trial_fingerprint")),
        },
        "source_contract_blockers": source_contract_blockers,
        "non_authority_boundary_blockers": boundary_blockers,
        "profitability_claim": "not_established",
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "raw_xls_rows_included": False,
        "private_account_identifiers_included": False,
        "manual_confirmation_required": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "limitations": [
            "This report proves only current local service and persisted-evidence readiness, not future profitability.",
            "Twenty qualifying days and fifty simulated orders permit only a separate human GO/NO-GO review.",
            "Current real-order closure is reported separately and never counted toward or attributed to the simulated-order trial threshold.",
            "A ready report does not create a ticket, submit an order, or change strategy or capital authority.",
        ],
    }
    return {**core, "readiness_fingerprint": _fingerprint(core)}


def unavailable_daily_candidate_production_readiness(
    *, blocker: str = "local_karkinos_service_unreachable"
) -> dict[str, Any]:
    """Return a sanitized fail-closed report when live reads are unavailable."""

    safe_blocker = _safe_code(blocker)
    core = {
        "schema_version": DAILY_CANDIDATE_PRODUCTION_READINESS_SCHEMA_VERSION,
        "status": "no_action_not_production_ready",
        "ready_for_production_operation": False,
        "service_liveness_proven_by_local_api": False,
        "daily_operation": {
            "status": "no_action",
            "run_date": None,
            "financial_gate_status": "blocked",
            "operational_gate_status": "blocked",
            "background_monitor_running": False,
            "schedule_status": "unavailable",
            "eligible_for_background_attempt": False,
            "eligible_to_start_manual_attempt": False,
            "blockers": [safe_blocker],
            "blocking_summary": [
                {
                    "code": safe_blocker,
                    "occurrence_count": 1,
                    "affected_candidate_count": 0,
                }
            ],
            "schedule_reasons": [],
            "next_safe_action": "start_and_verify_local_karkinos_service",
            "preflight_fingerprint": None,
            "next_reviewed_window": _unavailable_next_reviewed_window_projection(
                "next_reviewed_window_live_source_unavailable"
            ),
            "operator_checklist_status": "unavailable",
            "blocking_gate_count": 1,
            "first_blocking_step": 1,
            "first_blocking_gate": "source_evidence",
            "first_safe_action": "start_and_verify_local_karkinos_service",
            "operator_checklist": [
                {
                    "step": 1,
                    "gate": "source_evidence",
                    "action": "start_and_verify_local_karkinos_service",
                    "completion_mode": "canonical_runtime",
                    "blocker_count": 1,
                    "unique_blocker_count": 1,
                    "blocker_summary": [
                        {
                            "code": safe_blocker,
                            "occurrence_count": 1,
                            "affected_candidate_count": 0,
                        }
                    ],
                    "evidence_contract_version": (_OPERATOR_EVIDENCE_CONTRACT_VERSION),
                    "required_evidence": ["reachable_loopback_karkinos_service"],
                    "completion_criteria": [
                        "local_service_liveness_and_persisted_sources_are_verified"
                    ],
                    "accepted_evidence_authority": (_CANONICAL_EVIDENCE_AUTHORITY),
                    "owner_attestation_is_financial_fact": False,
                    "private_xls_rows_required": False,
                    "private_account_identifiers_required": False,
                    "automatic_action_performed": False,
                    "authorizes_execution": False,
                    "changes_capital_authority": False,
                }
            ],
        },
        "research_cycle": {
            "status": "unavailable",
            "enabled": False,
            "configured_sequential_iterations": 0,
            "configured_provider_call_limit": 0,
            "configured_daily_token_budget": None,
            "configured_token_budget_mode": "unavailable",
            "required_sequential_iterations": SHADOW_RESEARCH_MAX_CANDIDATES,
            "required_provider_call_limit": SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
            "required_token_budget_mode": (SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED),
            "blockers": [safe_blocker],
            "automatic_strategy_replacement_enabled": False,
        },
        "forward_trial": {
            "status": "unavailable",
            "trial_epoch_id": None,
            "qualifying_trading_day_count": 0,
            "target_qualifying_trading_days": 20,
            "simulated_order_count": 0,
            "target_simulated_orders": 50,
            "remaining_trading_days": 20,
            "remaining_simulated_orders": 50,
            "eligible_for_human_go_no_go_review": False,
            "latest_review_decision": None,
            "execution_reconciliation": {
                "schema_version": (
                    "karkinos.daily_candidate_execution_evidence_summary.v1"
                ),
                "status": "blocked",
                "current_execution_closure_fingerprint": None,
                "population_scope": "all_current_non_paper_shadow_oms_orders",
                "production_order_count": 0,
                "clear_order_count": 0,
                "reconciled_actual_order_count": 0,
                "reconciled_no_fill_order_count": 0,
                "comparison_coverage_complete": False,
                "blockers": [safe_blocker],
                "actual_orders_attributed_to_trial": False,
                "actual_orders_count_toward_simulated_trial_threshold": False,
                "persisted_evidence_only": True,
                "provider_contact_performed": False,
                "manual_review_required": True,
                "authorizes_execution": False,
                "does_not_submit_broker_order": True,
                "does_not_mutate_oms": True,
                "does_not_mutate_production_ledger": True,
                "does_not_change_capital_authority": True,
                "evidence_fingerprint": None,
            },
            "blockers": [safe_blocker],
            "trial_fingerprint": None,
        },
        "source_contract_blockers": [safe_blocker],
        "non_authority_boundary_blockers": [],
        "profitability_claim": "not_established",
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "raw_xls_rows_included": False,
        "private_account_identifiers_included": False,
        "manual_confirmation_required": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "limitations": [
            "Local service liveness and current persisted evidence could not be verified.",
            "No ticket, order, strategy change, or capital change is authorized.",
        ],
    }
    return {**core, "readiness_fingerprint": _fingerprint(core)}
