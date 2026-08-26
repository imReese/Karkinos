"""Focused evaluators used by the daily-candidate financial preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
)
from server.services.daily_decision_evidence_identity import fingerprint_json
from server.services.daily_decision_evidence_values import (
    aware_datetime,
    is_sha256,
    object_dict,
    object_list,
    positive_float,
    shanghai_date,
)
from server.services.daily_decision_strategy_gate import resolve_strategy_gate_binding


@dataclass(frozen=True, slots=True)
class StrategyGateEvaluation:
    blockers: tuple[str, ...]
    eligible_candidate_count: int
    binding_fingerprints: tuple[str, ...]
    normal_no_signal: bool


@dataclass(frozen=True, slots=True)
class RuntimeGateEvaluation:
    blockers: tuple[str, ...]
    schedule_status: str
    manual_window_open: bool


@dataclass(frozen=True, slots=True)
class PreflightOutcome:
    background_ready: bool
    manual_ready: bool
    status: str
    next_safe_action: str
    no_action_reasons: tuple[str, ...]


def evaluate_strategy_gate(
    *,
    decision_payload: dict[str, Any],
    run_date: str,
    active_fee_review_fingerprint: str,
    decision_generated_at: Any,
) -> StrategyGateEvaluation:
    """Validate strategy and quote bindings for every projected candidate."""

    strategy_blockers: list[str] = []
    eligible_candidate_count = 0
    strategy_binding_fingerprints: list[str] = []
    candidates = object_list(decision_payload.get("candidates"))
    promoted_scan = object_dict(
        object_dict(decision_payload.get("summary")).get(
            "promoted_strategy_universe_scan"
        )
    )
    normal_no_signal = bool(
        not candidates
        and promoted_scan.get("status") == "completed_no_signal"
        and promoted_scan.get("normal_no_signal") is True
        and not promoted_scan.get("blockers")
    )
    if not candidates:
        if promoted_scan.get("status") == "blocked":
            scan_blockers = [
                str(item) for item in promoted_scan.get("blockers") or [] if str(item)
            ]
            strategy_blockers.extend(
                f"promoted_strategy_universe_scan:{item}" for item in scan_blockers
            )
            if not scan_blockers:
                strategy_blockers.append("promoted_strategy_universe_scan_blocked")
        elif not normal_no_signal:
            strategy_blockers.append("daily_candidate_strategy_candidate_missing")

    for index, candidate in enumerate(candidates):
        candidate_blockers: list[str] = []
        if str(candidate.get("asset_class") or "").strip().lower() != "stock":
            candidate_blockers.append(
                "daily_candidate_asset_class_outside_strategy_scope"
            )
        manual_status = str(candidate.get("manual_confirmation_status") or "")
        if manual_status not in {
            "awaiting_risk_gate",
            "paper_shadow_review_required",
            "ready_for_manual_confirmation",
        }:
            candidate_blockers.append("strategy_candidate_not_paper_shadow_eligible")
        strategy = object_dict(object_dict(candidate.get("evidence")).get("strategy"))
        strategy_id = str(strategy.get("strategy_id") or "")
        order_generation_gate = object_dict(strategy.get("order_generation_gate"))
        promotion = object_dict(order_generation_gate.get("promotion"))
        advancement_fingerprint = str(
            promotion.get("strategy_advancement_gate_fingerprint") or ""
        )
        fee_review_fingerprint = str(
            object_dict(promotion.get("fee_schedule_binding")).get(
                "fee_schedule_review_fingerprint"
            )
            or ""
        )
        binding, binding_blockers = resolve_strategy_gate_binding(
            candidate=candidate,
            plan_date=run_date,
            expected_strategy_ref=(f"strategy:{strategy_id}" if strategy_id else None),
            expected_advancement_ref=(
                f"strategy_advancement:{advancement_fingerprint}"
                if advancement_fingerprint
                else None
            ),
            expected_fee_review_ref=(
                f"reviewed_fee_schedule:{fee_review_fingerprint}"
                if fee_review_fingerprint
                else None
            ),
            action_id=candidate.get("action_id"),
        )
        candidate_blockers.extend(binding_blockers)
        if fee_review_fingerprint != active_fee_review_fingerprint:
            candidate_blockers.append("reviewed_fee_schedule_active_binding_mismatch")
        candidate_market = object_dict(
            object_dict(candidate.get("evidence")).get("data_freshness")
        )
        candidate_quote_at = aware_datetime(candidate_market.get("quote_timestamp"))
        if shanghai_date(candidate_quote_at) != run_date:
            candidate_blockers.append("candidate_market_quote_not_bound_to_plan_date")
        if positive_float(candidate_market.get("price")) is None:
            candidate_blockers.append("candidate_market_quote_price_invalid")
        if not str(candidate_market.get("quote_source") or "").strip():
            candidate_blockers.append("candidate_market_quote_source_missing")
        if candidate_quote_at is not None and decision_generated_at is not None:
            if candidate_quote_at > decision_generated_at:
                candidate_blockers.append("candidate_market_quote_after_decision")
            elif (
                decision_generated_at - candidate_quote_at
            ).total_seconds() > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
                candidate_blockers.append("candidate_market_quote_too_old")
        candidate_blockers = list(dict.fromkeys(candidate_blockers))
        if candidate_blockers:
            strategy_blockers.extend(
                f"candidate_{index}:{item}" for item in candidate_blockers
            )
        else:
            eligible_candidate_count += 1
            strategy_binding_fingerprints.append(fingerprint_json(binding))
    if candidates and eligible_candidate_count == 0:
        strategy_blockers.append("daily_candidate_strategy_candidate_not_eligible")
    return StrategyGateEvaluation(
        blockers=tuple(strategy_blockers),
        eligible_candidate_count=eligible_candidate_count,
        binding_fingerprints=tuple(strategy_binding_fingerprints),
        normal_no_signal=normal_no_signal,
    )


def reviewed_fee_schedule_blockers(
    reviewed_fee_schedule: dict[str, Any],
    *,
    active_fee_review_fingerprint: str,
) -> list[str]:
    blockers = [
        str(item) for item in reviewed_fee_schedule.get("blockers") or [] if str(item)
    ]
    if reviewed_fee_schedule.get("status") != "active":
        blockers.append("reviewed_fee_schedule_not_active")
    if not is_sha256(active_fee_review_fingerprint):
        blockers.append("reviewed_fee_schedule_review_fingerprint_invalid")
    expected_boundaries = {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_boundaries.items():
        if reviewed_fee_schedule.get(field) is not expected:
            blockers.append(f"reviewed_fee_schedule_{field}_invalid")
    return blockers


def execution_closure_blockers(execution_closure: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if execution_closure.get("schema_version") != (
        "karkinos.daily_candidate_execution_closure.v1"
    ):
        blockers.append("execution_closure_contract_invalid")
    if execution_closure.get("status") not in {"pass", "not_required"}:
        blockers.extend(
            f"execution_closure:{item}"
            for item in execution_closure.get("blockers") or []
            if str(item)
        )
        blockers.append("prior_execution_not_reconciled")
    if not is_sha256(execution_closure.get("evidence_fingerprint")):
        blockers.append("execution_closure_fingerprint_invalid")
    return blockers


def evaluate_runtime_gate(runtime_status: dict[str, Any]) -> RuntimeGateEvaluation:
    blockers = [
        str(item)
        for item in runtime_status.get("operational_blockers") or []
        if str(item)
    ]
    expected_boundaries = {
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_boundaries.items():
        if runtime_status.get(field) is not expected:
            blockers.append(f"daily_candidate_runtime_{field}_invalid")
    if runtime_status.get("schema_version") != (
        "karkinos.daily_candidate_runtime_status.v1"
    ):
        blockers.append("daily_candidate_runtime_contract_invalid")
    return RuntimeGateEvaluation(
        blockers=tuple(dict.fromkeys(blockers)),
        schedule_status=str(runtime_status.get("schedule_status") or "invalid"),
        manual_window_open=runtime_status.get("manual_run_window_open") is True,
    )


def resolve_preflight_outcome(
    *,
    financial_blockers: list[str],
    runtime: RuntimeGateEvaluation,
    runtime_status: dict[str, Any],
    normal_no_signal: bool,
) -> PreflightOutcome:
    financial_clear = not financial_blockers
    background_ready = bool(
        financial_clear
        and runtime.manual_window_open
        and runtime_status.get("background_attempt_due") is True
        and runtime_status.get("background_monitor_running") is True
        and not runtime.blockers
    )
    manual_ready = bool(financial_clear and runtime.manual_window_open)

    no_action_reasons = [*financial_blockers, *runtime.blockers]
    if not runtime.manual_window_open:
        schedule_reason = {
            "waiting_for_decision_window": "daily_candidate_decision_window_not_open",
            "missed_decision_window": "daily_candidate_background_window_missed",
            "not_trading_day": "market_calendar_not_trading_day",
            "already_attempted": "daily_candidate_attempt_already_recorded",
            "already_recorded": "daily_candidate_run_already_recorded",
        }.get(
            runtime.schedule_status,
            "daily_candidate_decision_window_unavailable",
        )
        no_action_reasons.append(schedule_reason)
    no_action_reasons = list(dict.fromkeys(no_action_reasons))

    if background_ready:
        status = (
            "ready_to_record_deterministic_no_action"
            if normal_no_signal
            else "ready_for_paper_shadow_attempt"
        )
        next_safe_action = (
            "record_full_market_scan_no_action"
            if normal_no_signal
            else "allow_single_claimed_fail_closed_background_attempt"
        )
    elif manual_ready:
        status = (
            "ready_to_record_deterministic_no_action"
            if normal_no_signal
            else "ready_for_manual_paper_shadow_attempt"
        )
        next_safe_action = (
            "record_full_market_scan_no_action"
            if normal_no_signal
            else "start_one_canonical_daily_candidate_attempt"
        )
    elif financial_blockers:
        status = "no_action"
        next_safe_action = "resolve_named_financial_blockers_before_next_window"
    elif runtime.schedule_status == "waiting_for_decision_window":
        status = "waiting_for_decision_window"
        next_safe_action = "keep_monitor_running_and_wait_for_reviewed_window"
    elif runtime.schedule_status == "not_trading_day":
        status = "no_action_not_trading_day"
        next_safe_action = "wait_for_next_verified_trading_day"
    elif runtime.schedule_status in {"already_attempted", "already_recorded"}:
        status = "daily_attempt_closed"
        next_safe_action = "review_persisted_daily_result"
    else:
        status = "no_action"
        next_safe_action = "resolve_runtime_or_schedule_blockers_before_next_window"
    return PreflightOutcome(
        background_ready=background_ready,
        manual_ready=manual_ready,
        status=status,
        next_safe_action=next_safe_action,
        no_action_reasons=tuple(no_action_reasons),
    )


__all__ = [
    "PreflightOutcome",
    "RuntimeGateEvaluation",
    "StrategyGateEvaluation",
    "evaluate_runtime_gate",
    "evaluate_strategy_gate",
    "execution_closure_blockers",
    "resolve_preflight_outcome",
    "reviewed_fee_schedule_blockers",
]
