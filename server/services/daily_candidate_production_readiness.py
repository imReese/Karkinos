"""Sanitized live-readiness projection for production daily candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
)

DAILY_CANDIDATE_PRODUCTION_READINESS_SCHEMA_VERSION = (
    "karkinos.daily_candidate_production_readiness.v2"
)

_OPERATOR_EVIDENCE_CONTRACT_VERSION = "karkinos.daily_candidate_operator_evidence.v1"
_CANONICAL_EVIDENCE_AUTHORITY = "canonical_persisted_evidence_only"

_EXPECTED_SCHEMAS = {
    "cockpit": "karkinos.automation_cockpit.v4",
    "preflight": "karkinos.daily_candidate_financial_preflight.v1",
    "runtime": "karkinos.daily_candidate_runtime_status.v1",
    "trial": "karkinos.daily_candidate_trial.v1",
    "research": "karkinos.ai.shadow_research_automation.v1",
    "research_policy": "karkinos.ai.shadow_research_policy.v2",
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
    policy = _mapping(research_status.get("policy"))

    source_contract_blockers = _schema_blockers(
        cockpit=cockpit,
        preflight=preflight,
        runtime=runtime,
        trial=trial,
        research=research_status,
        research_policy=policy,
    )
    source_contract_blockers.extend(_operator_checklist_contract_blockers(preflight))
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
    daily_operation_blockers = _unique(
        [
            *source_contract_blockers,
            *boundary_blockers,
            *financial_blockers,
            *hard_runtime_blockers,
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

    research_blockers = _research_policy_blockers(policy)
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


def _schema_blockers(**payloads: dict[str, Any]) -> list[str]:
    blockers = []
    for name, expected in _EXPECTED_SCHEMAS.items():
        if payloads[name].get("schema_version") != expected:
            blockers.append(f"{name}_contract_invalid")
    return blockers


def _operator_checklist_contract_blockers(
    preflight: dict[str, Any],
) -> list[str]:
    checklist = preflight.get("operator_checklist")
    if not isinstance(checklist, list) or not checklist:
        return ["preflight_operator_checklist_contract_invalid"]
    for expected_step, raw_item in enumerate(checklist, start=1):
        item = _mapping(raw_item)
        if (
            item.get("step") != expected_step
            or not _is_safe_code(item.get("gate"))
            or not _is_safe_code(item.get("action"))
            or not _is_safe_code(item.get("completion_mode"))
            or item.get("evidence_contract_version")
            != _OPERATOR_EVIDENCE_CONTRACT_VERSION
            or item.get("accepted_evidence_authority") != _CANONICAL_EVIDENCE_AUTHORITY
            or item.get("owner_attestation_is_financial_fact") is not False
            or item.get("private_xls_rows_required") is not False
            or item.get("private_account_identifiers_required") is not False
            or item.get("automatic_action_performed") is not False
            or item.get("authorizes_execution") is not False
            or item.get("changes_capital_authority") is not False
            or not _is_safe_code_list(item.get("blockers"), allow_empty=True)
            or not _is_safe_code_list(item.get("required_evidence"))
            or not _is_safe_code_list(item.get("completion_criteria"))
        ):
            return ["preflight_operator_checklist_contract_invalid"]
    return []


def _project_operator_checklist(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    if _operator_checklist_contract_blockers(preflight):
        return []
    projected = []
    for raw_item in preflight["operator_checklist"]:
        item = _mapping(raw_item)
        blockers = list(item["blockers"])
        blocker_summary = _summarize_operator_blockers(blockers)
        projected.append(
            {
                "step": item["step"],
                "gate": item["gate"],
                "action": item["action"],
                "completion_mode": item["completion_mode"],
                "blocker_count": len(blockers),
                "unique_blocker_count": len(blocker_summary),
                "blocker_summary": blocker_summary,
                "evidence_contract_version": item["evidence_contract_version"],
                "required_evidence": list(item["required_evidence"]),
                "completion_criteria": list(item["completion_criteria"]),
                "accepted_evidence_authority": item["accepted_evidence_authority"],
                "owner_attestation_is_financial_fact": False,
                "private_xls_rows_required": False,
                "private_account_identifiers_required": False,
                "automatic_action_performed": False,
                "authorizes_execution": False,
                "changes_capital_authority": False,
            }
        )
    return projected


def _summarize_operator_blockers(blockers: list[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    candidates: dict[str, set[str]] = {}
    for blocker in blockers:
        prefix, separator, remainder = blocker.partition(":")
        candidate_scoped = bool(
            separator
            and prefix.startswith("candidate_")
            and prefix.removeprefix("candidate_").isdigit()
            and remainder
        )
        code = remainder if candidate_scoped else blocker
        counts[code] = counts.get(code, 0) + 1
        if candidate_scoped:
            candidates.setdefault(code, set()).add(prefix)
    return [
        {
            "code": code,
            "occurrence_count": count,
            "affected_candidate_count": len(candidates.get(code, set())),
        }
        for code, count in counts.items()
    ]


def _project_next_reviewed_window(trial: dict[str, Any]) -> dict[str, Any]:
    schedule = _mapping(trial.get("background_schedule"))
    window = _mapping(schedule.get("next_reviewed_window"))
    if (
        schedule.get("schema_version")
        != "karkinos.daily_candidate_background_schedule.v3"
        or window.get("schema_version")
        != "karkinos.daily_candidate_next_reviewed_window.v1"
    ):
        return _unavailable_next_reviewed_window_projection(
            "next_reviewed_window_not_exposed_by_running_service"
        )

    boundaries_clear = all(
        window.get(field) is False
        for field in (
            "provider_contact_performed",
            "database_writes_performed",
            "permits_retry_or_backfill",
            "changes_attempt_eligibility",
            "broker_submission_enabled",
            "authorizes_execution",
            "changes_capital_authority",
        )
    )
    if not boundaries_clear:
        return _unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )

    status = window.get("status")
    blockers = _strings(window.get("blockers"))
    if any(not _is_safe_code(blocker) for blocker in blockers):
        return _unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )
    if status == "unavailable":
        if (
            not blockers
            or window.get("market_date") is not None
            or window.get("window_start") is not None
            or window.get("window_end") is not None
            or window.get("is_current_market_date") is not False
            or window.get("official_calendar_verified") is not False
        ):
            return _unavailable_next_reviewed_window_projection(
                "next_reviewed_window_contract_invalid"
            )
        return {
            **_unavailable_next_reviewed_window_projection(blockers[0]),
            "blockers": blockers,
        }

    market_date = str(window.get("market_date") or "")
    run_date = str(schedule.get("run_date") or "")
    try:
        parsed_date = datetime.strptime(market_date, "%Y-%m-%d").date()
        parsed_run_date = datetime.strptime(run_date, "%Y-%m-%d").date()
        window_start = datetime.fromisoformat(str(window.get("window_start") or ""))
        window_end = datetime.fromisoformat(str(window.get("window_end") or ""))
    except ValueError:
        return _unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )
    if (
        status != "available"
        or parsed_date.isoformat() != market_date
        or parsed_run_date.isoformat() != run_date
        or parsed_date < parsed_run_date
        or window_start.tzinfo is None
        or window_end.tzinfo is None
        or window_start.utcoffset() != timedelta(hours=8)
        or window_end.utcoffset() != timedelta(hours=8)
        or window_start.date() != parsed_date
        or window_end.date() != parsed_date
        or (window_start.hour, window_start.minute, window_start.second) != (9, 35, 0)
        or (window_end.hour, window_end.minute, window_end.second) != (9, 45, 0)
        or window_start.microsecond != 0
        or window_end.microsecond != 0
        or window_start.isoformat() != str(window.get("window_start") or "")
        or window_end.isoformat() != str(window.get("window_end") or "")
        or window.get("official_calendar_verified") is not True
        or blockers
        or not isinstance(window.get("is_current_market_date"), bool)
        or window.get("is_current_market_date") is not (market_date == run_date)
    ):
        return _unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )
    return {
        "schema_version": "karkinos.daily_candidate_next_reviewed_window.v1",
        "status": "available",
        "market_date": market_date,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "is_current_market_date": window["is_current_market_date"],
        "official_calendar_verified": True,
        "blockers": [],
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "permits_retry_or_backfill": False,
        "changes_attempt_eligibility": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _unavailable_next_reviewed_window_projection(blocker: str) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.daily_candidate_next_reviewed_window.v1",
        "status": "unavailable",
        "market_date": None,
        "window_start": None,
        "window_end": None,
        "is_current_market_date": False,
        "official_calendar_verified": False,
        "blockers": [_safe_code(blocker)],
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "permits_retry_or_backfill": False,
        "changes_attempt_eligibility": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _non_authority_boundary_blockers(
    *,
    cockpit: dict[str, Any],
    preflight: dict[str, Any],
    runtime: dict[str, Any],
    trial: dict[str, Any],
    research: dict[str, Any],
) -> list[str]:
    checks = {
        "cockpit_broker_submission_enabled": cockpit.get("broker_submission_enabled"),
        "preflight_provider_contact_performed": preflight.get(
            "provider_contact_performed"
        ),
        "preflight_database_writes_performed": preflight.get(
            "database_writes_performed"
        ),
        "preflight_broker_submission_enabled": preflight.get(
            "broker_submission_enabled"
        ),
        "preflight_authorizes_execution": preflight.get("authorizes_execution"),
        "preflight_changes_capital_authority": preflight.get(
            "changes_capital_authority"
        ),
        "runtime_provider_contact_performed": runtime.get("provider_contact_performed"),
        "runtime_database_writes_performed": runtime.get("database_writes_performed"),
        "runtime_broker_submission_enabled": runtime.get("broker_submission_enabled"),
        "runtime_authorizes_execution": runtime.get("authorizes_execution"),
        "runtime_changes_capital_authority": runtime.get("changes_capital_authority"),
        "trial_broker_submission_enabled": trial.get("broker_submission_enabled"),
        "trial_authorizes_execution": trial.get("authorizes_execution"),
        "trial_changes_capital_authority": trial.get("changes_capital_authority"),
        "research_broker_submission_enabled": research.get("broker_submission_enabled"),
        "research_production_strategy_mutation_enabled": research.get(
            "production_strategy_mutation_enabled"
        ),
        "research_automatic_strategy_replacement_enabled": research.get(
            "automatic_strategy_replacement_enabled"
        ),
    }
    return [
        f"{name}_boundary_invalid"
        for name, value in checks.items()
        if value is not False
    ]


def _research_policy_blockers(policy: dict[str, Any]) -> list[str]:
    blockers = []
    if policy.get("enabled") is not True:
        blockers.append("five_sequential_iteration_policy_disabled")
    if policy.get("max_candidates_per_run") != SHADOW_RESEARCH_MAX_CANDIDATES:
        blockers.append("five_sequential_iteration_count_not_authorized")
    if (
        policy.get("max_provider_calls_per_market_date")
        != SHADOW_RESEARCH_MAX_PROVIDER_CALLS
    ):
        blockers.append("ten_provider_call_limit_not_authorized")
    if (
        policy.get("daily_token_budget") is not None
        or policy.get("token_budget_mode")
        != SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED
    ):
        blockers.append("unbounded_daily_token_policy_not_authorized")
    if policy.get("authorization") != SHADOW_RESEARCH_POLICY_CONFIRMATION:
        blockers.append("five_sequential_iteration_authorization_missing")
    if policy.get("require_complete_account_evidence") is not True:
        blockers.append("complete_account_evidence_requirement_disabled")
    return blockers


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique([str(item) for item in value if str(item)])


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _safe_fingerprint(value: Any) -> str | None:
    normalized = str(value or "")
    if len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    ):
        return normalized
    return None


def _safe_code(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if not normalized or len(normalized) > 120:
        return "daily_candidate_production_readiness_unavailable"
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_:-."
        for character in normalized
    ):
        return "daily_candidate_production_readiness_unavailable"
    return normalized


def _is_safe_code(value: Any) -> bool:
    return isinstance(value, str) and value == _safe_code(value)


def _is_safe_code_list(value: Any, *, allow_empty: bool = False) -> bool:
    return bool(
        isinstance(value, list)
        and (value or allow_empty)
        and all(_is_safe_code(item) for item in value)
    )


def _fingerprint(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
