"""Fail-closed policy gates for daily candidate evidence."""

from __future__ import annotations

from typing import Any

from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION,
    DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
    TRUSTED_MARKET_STATUSES,
)
from server.services.daily_decision_evidence_identity import (
    evidence_fingerprint,
    fingerprint_json,
)
from server.services.daily_decision_evidence_values import (
    aware_datetime,
    in_daily_candidate_decision_window,
    is_sha256,
    nonnegative_float,
    nonnegative_int,
    object_dict,
    object_list,
    policy_allows_paper_shadow,
    positive_float,
    positive_int,
    shanghai_date,
)
from server.services.daily_decision_preflight_operator import (
    build_preflight_gate,
    build_preflight_operator_checklist,
    build_preflight_operator_step,
    safe_preflight_blocker,
)
from server.services.daily_decision_strategy_gate import resolve_strategy_gate_binding


def build_daily_candidate_base_gate(
    *,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
    plan_date: str,
) -> dict[str, Any]:
    """Own the shared Decision, Account Truth, and market gate calculation."""

    gate_blockers: dict[str, list[str]] = {
        "decision_plan": [],
        "account_truth": [],
        "market_data": [],
    }
    decision_plan_blockers = gate_blockers["decision_plan"]
    account_truth_blockers = gate_blockers["account_truth"]
    market_blockers = gate_blockers["market_data"]

    decision_date = str(decision_payload.get("decision_date") or "")
    plan_contract_date = str(trading_plan.get("plan_date") or "")
    if not plan_date or not decision_date or not plan_contract_date:
        decision_plan_blockers.append("decision_or_plan_date_missing")
    elif len({plan_date, decision_date, plan_contract_date}) != 1:
        decision_plan_blockers.append("decision_plan_date_mismatch")
    if trading_plan.get("schema_version") != "karkinos.daily_trading_plan.v1":
        decision_plan_blockers.append("daily_trading_plan_contract_invalid")

    summary = object_dict(decision_payload.get("summary"))
    promoted_scan = object_dict(summary.get("promoted_strategy_universe_scan"))
    if promoted_scan and promoted_scan.get("status") == "blocked":
        scan_blockers = [
            str(item) for item in promoted_scan.get("blockers") or [] if str(item)
        ]
        decision_plan_blockers.extend(
            f"promoted_strategy_universe_scan:{item}" for item in scan_blockers
        )
        if not scan_blockers:
            decision_plan_blockers.append("promoted_strategy_universe_scan_blocked")
    portfolio = object_dict(summary.get("portfolio"))
    valuation_snapshot_id = str(portfolio.get("valuation_snapshot_id") or "")
    ledger_cutoff_id = positive_int(portfolio.get("ledger_cutoff_id"))
    if not valuation_snapshot_id:
        decision_plan_blockers.append("valuation_snapshot_id_missing")
    if ledger_cutoff_id is None:
        decision_plan_blockers.append("ledger_cutoff_id_invalid")

    account_truth = object_dict(summary.get("account_truth"))
    if account_truth.get("schema_version") != (
        "karkinos.account_truth.promotion_evidence.v1"
    ):
        account_truth_blockers.append("account_truth_promotion_contract_invalid")
    if str(account_truth.get("promotion_status") or "").lower() != "clear":
        account_truth_blockers.append("account_truth_promotion_status_not_clear")
    if str(account_truth.get("gate_status") or "").lower() != "pass":
        account_truth_blockers.append("account_truth_gate_not_pass")
    if str(account_truth.get("data_freshness_status") or "").lower() != "fresh":
        account_truth_blockers.append("account_truth_not_fresh")
    if nonnegative_int(account_truth.get("unresolved_mismatch_count")) != 0:
        account_truth_blockers.append("account_truth_unresolved_mismatch")
    account_truth_ref = str(account_truth.get("import_run_id") or "")
    if not account_truth_ref:
        account_truth_blockers.append("account_truth_import_run_missing")
    account_truth_source_fingerprint = str(
        account_truth.get("source_fingerprint") or ""
    )
    if not is_sha256(account_truth_source_fingerprint):
        account_truth_blockers.append("account_truth_source_fingerprint_invalid")
    account_truth_captured_at = aware_datetime(account_truth.get("captured_at"))
    if shanghai_date(account_truth_captured_at) != plan_date:
        account_truth_blockers.append("account_truth_not_bound_to_plan_date")
    account_truth_age = nonnegative_int(account_truth.get("current_age_seconds"))
    account_truth_max_age = positive_int(account_truth.get("max_age_seconds"))
    if account_truth_age is None or account_truth_max_age is None:
        account_truth_blockers.append("account_truth_age_evidence_invalid")
    elif account_truth_age > account_truth_max_age:
        account_truth_blockers.append("account_truth_age_exceeds_reviewed_limit")
    ledger_coverage = object_dict(account_truth.get("ledger_coverage"))
    if str(account_truth.get("reconciliation_status") or "").lower() != "pass":
        account_truth_blockers.append("account_truth_reconciliation_not_pass")
    if ledger_coverage.get("status") != "covered":
        account_truth_blockers.append("account_truth_ledger_coverage_not_complete")

    market = object_dict(summary.get("market_data"))
    if str(market.get("source_health") or "").lower() not in TRUSTED_MARKET_STATUSES:
        market_blockers.append("market_data_not_trusted")
    quote_timestamp = str(market.get("latest_quote_timestamp") or "")
    quote_at = aware_datetime(quote_timestamp)
    quote_date = shanghai_date(quote_at)
    if not quote_date:
        market_blockers.append("market_quote_timestamp_missing_or_invalid")
    elif quote_date != plan_date:
        market_blockers.append("market_quote_not_bound_to_plan_date")

    decision_generated_at = aware_datetime(decision_payload.get("generated_at"))
    plan_generated_at = aware_datetime(trading_plan.get("generated_at"))
    if shanghai_date(decision_generated_at) != plan_date:
        decision_plan_blockers.append("decision_generation_time_not_bound_to_plan_date")
    if shanghai_date(plan_generated_at) != plan_date:
        decision_plan_blockers.append("plan_generation_time_not_bound_to_plan_date")
    if quote_at is not None and decision_generated_at is not None:
        if quote_at > decision_generated_at:
            market_blockers.append("market_quote_after_decision_generation")
        elif (
            decision_generated_at - quote_at
        ).total_seconds() > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
            market_blockers.append("market_quote_too_old_for_decision")
    account_truth_age_at_decision: int | None = None
    if account_truth_captured_at is not None and decision_generated_at is not None:
        if account_truth_captured_at > decision_generated_at:
            account_truth_blockers.append("account_truth_after_decision_generation")
        else:
            account_truth_age_at_decision = int(
                (decision_generated_at - account_truth_captured_at).total_seconds()
            )
            if (
                account_truth_max_age is not None
                and account_truth_age_at_decision > account_truth_max_age
            ):
                account_truth_blockers.append("account_truth_too_old_for_decision")
    if (
        decision_generated_at is not None
        and plan_generated_at is not None
        and decision_generated_at > plan_generated_at
    ):
        decision_plan_blockers.append("plan_generated_before_decision")
    decision_in_window = in_daily_candidate_decision_window(
        decision_generated_at,
        plan_date=plan_date,
    )
    plan_in_window = in_daily_candidate_decision_window(
        plan_generated_at,
        plan_date=plan_date,
    )
    if not decision_in_window:
        decision_plan_blockers.append("decision_generated_outside_reviewed_window")
    if not plan_in_window:
        decision_plan_blockers.append("plan_generated_outside_reviewed_window")

    for blockers in gate_blockers.values():
        blockers[:] = list(dict.fromkeys(blockers))
    return {
        "gate_blockers": gate_blockers,
        "blockers": [
            blocker
            for gate_name in ("decision_plan", "account_truth", "market_data")
            for blocker in gate_blockers[gate_name]
        ],
        "decision_date": decision_date,
        "plan_contract_date": plan_contract_date,
        "valuation_snapshot_id": valuation_snapshot_id,
        "ledger_cutoff_id": ledger_cutoff_id,
        "account_truth": account_truth,
        "account_truth_ref": account_truth_ref,
        "account_truth_source_fingerprint": account_truth_source_fingerprint,
        "account_truth_captured_at": account_truth_captured_at,
        "account_truth_max_age": account_truth_max_age,
        "account_truth_age_at_decision": account_truth_age_at_decision,
        "ledger_coverage": ledger_coverage,
        "quote_timestamp": quote_timestamp,
        "quote_at": quote_at,
        "decision_generated_at": decision_generated_at,
        "plan_generated_at": plan_generated_at,
        "decision_in_window": decision_in_window,
        "plan_in_window": plan_in_window,
    }


def project_daily_candidate_financial_preflight(
    *,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
    reviewed_fee_schedule: dict[str, Any],
    execution_closure: dict[str, Any],
    automation_status: dict[str, Any],
    runtime_status: dict[str, Any],
) -> dict[str, Any]:
    """Project whether the current facts may enter risk plus paper/shadow.

    This is a zero-write read model. It does not run risk, simulate an order,
    create a ticket, or replace the canonical post-shadow production gate.
    """

    run_date = str(
        runtime_status.get("run_date")
        or trading_plan.get("plan_date")
        or decision_payload.get("decision_date")
        or ""
    )
    financial_gates: list[dict[str, Any]] = []

    policy_blockers: list[str] = []
    if not policy_allows_paper_shadow(automation_status):
        if automation_status.get("kill_switch_enabled") is True:
            policy_blockers.append("daily_candidate_kill_switch_enabled")
        else:
            policy_blockers.append("daily_candidate_safe_automation_policy_blocked")
    financial_gates.append(build_preflight_gate("automation_policy", policy_blockers))

    base_gate = build_daily_candidate_base_gate(
        decision_payload=decision_payload,
        trading_plan=trading_plan,
        plan_date=run_date,
    )
    base_gate_blockers = object_dict(base_gate.get("gate_blockers"))
    decision_plan_blockers = [
        str(item) for item in base_gate_blockers.get("decision_plan") or []
    ]
    for blocker in object_list(trading_plan.get("blockers")):
        reason = safe_preflight_blocker(blocker.get("reason"))
        if reason and reason != "awaiting_risk_gate":
            decision_plan_blockers.append(f"daily_trading_plan:{reason}")
    financial_gates.append(
        build_preflight_gate("decision_plan", decision_plan_blockers)
    )
    financial_gates.append(
        build_preflight_gate(
            "account_truth",
            [str(item) for item in base_gate_blockers.get("account_truth") or []],
        )
    )
    market_blockers = [
        str(item) for item in base_gate_blockers.get("market_data") or []
    ]
    decision_generated_at = base_gate.get("decision_generated_at")

    strategy_blockers: list[str] = []
    eligible_candidate_count = 0
    strategy_binding_fingerprints: list[str] = []
    active_fee_review = object_dict(reviewed_fee_schedule.get("review"))
    active_fee_review_fingerprint = str(
        active_fee_review.get("review_fingerprint") or ""
    )
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
    financial_gates.append(build_preflight_gate("market_data", market_blockers))
    financial_gates.append(build_preflight_gate("strategy", strategy_blockers))

    fee_blockers = [
        str(item) for item in reviewed_fee_schedule.get("blockers") or [] if str(item)
    ]
    if reviewed_fee_schedule.get("status") != "active":
        fee_blockers.append("reviewed_fee_schedule_not_active")
    if not is_sha256(active_fee_review_fingerprint):
        fee_blockers.append("reviewed_fee_schedule_review_fingerprint_invalid")
    expected_fee_boundaries = {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_fee_boundaries.items():
        if reviewed_fee_schedule.get(field) is not expected:
            fee_blockers.append(f"reviewed_fee_schedule_{field}_invalid")
    financial_gates.append(build_preflight_gate("reviewed_fees", fee_blockers))

    closure_blockers: list[str] = []
    if execution_closure.get("schema_version") != (
        "karkinos.daily_candidate_execution_closure.v1"
    ):
        closure_blockers.append("execution_closure_contract_invalid")
    if execution_closure.get("status") not in {"pass", "not_required"}:
        closure_blockers.extend(
            f"execution_closure:{item}"
            for item in execution_closure.get("blockers") or []
            if str(item)
        )
        closure_blockers.append("prior_execution_not_reconciled")
    if not is_sha256(execution_closure.get("evidence_fingerprint")):
        closure_blockers.append("execution_closure_fingerprint_invalid")
    financial_gates.append(build_preflight_gate("execution_closure", closure_blockers))

    financial_blockers = list(
        dict.fromkeys(
            blocker
            for gate in financial_gates
            for blocker in gate.get("blockers") or []
        )
    )
    runtime_blockers = [
        str(item)
        for item in runtime_status.get("operational_blockers") or []
        if str(item)
    ]
    expected_runtime_boundaries = {
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_runtime_boundaries.items():
        if runtime_status.get(field) is not expected:
            runtime_blockers.append(f"daily_candidate_runtime_{field}_invalid")
    if runtime_status.get("schema_version") != (
        "karkinos.daily_candidate_runtime_status.v1"
    ):
        runtime_blockers.append("daily_candidate_runtime_contract_invalid")
    runtime_blockers = list(dict.fromkeys(runtime_blockers))
    schedule_status = str(runtime_status.get("schedule_status") or "invalid")
    financial_clear = not financial_blockers
    manual_window_open = runtime_status.get("manual_run_window_open") is True
    background_ready = bool(
        financial_clear
        and manual_window_open
        and runtime_status.get("background_attempt_due") is True
        and runtime_status.get("background_monitor_running") is True
        and not runtime_blockers
    )
    manual_ready = bool(financial_clear and manual_window_open)

    no_action_reasons = [*financial_blockers, *runtime_blockers]
    if not manual_window_open:
        schedule_reason = {
            "waiting_for_decision_window": "daily_candidate_decision_window_not_open",
            "missed_decision_window": "daily_candidate_background_window_missed",
            "not_trading_day": "market_calendar_not_trading_day",
            "already_attempted": "daily_candidate_attempt_already_recorded",
            "already_recorded": "daily_candidate_run_already_recorded",
        }.get(schedule_status, "daily_candidate_decision_window_unavailable")
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
    elif schedule_status == "waiting_for_decision_window":
        status = "waiting_for_decision_window"
        next_safe_action = "keep_monitor_running_and_wait_for_reviewed_window"
    elif schedule_status == "not_trading_day":
        status = "no_action_not_trading_day"
        next_safe_action = "wait_for_next_verified_trading_day"
    elif schedule_status in {"already_attempted", "already_recorded"}:
        status = "daily_attempt_closed"
        next_safe_action = "review_persisted_daily_result"
    else:
        status = "no_action"
        next_safe_action = "resolve_runtime_or_schedule_blockers_before_next_window"

    operator_checklist = build_preflight_operator_checklist(
        gates=financial_gates,
        runtime_blockers=runtime_blockers,
        schedule_status=schedule_status,
        manual_window_open=manual_window_open,
        next_safe_action=next_safe_action,
    )

    core = {
        "schema_version": DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION,
        "status": status,
        "run_date": run_date or None,
        "financial_gate_status": "pass" if financial_clear else "blocked",
        "operational_gate_status": "pass" if not runtime_blockers else "blocked",
        "eligible_candidate_count": eligible_candidate_count,
        "normal_no_signal": normal_no_signal,
        "eligible_to_start_manual_attempt": manual_ready,
        "eligible_for_background_attempt": background_ready,
        "eligible_to_create_manual_ticket": False,
        "gates": financial_gates,
        "financial_blockers": financial_blockers,
        "operational_blockers": runtime_blockers,
        "no_action_reasons": [] if manual_ready else no_action_reasons,
        "next_safe_action": next_safe_action,
        "operator_checklist": operator_checklist,
        "decision_plan_fingerprint": evidence_fingerprint(
            decision_payload,
            trading_plan,
        ),
        "strategy_binding_fingerprints": sorted(strategy_binding_fingerprints),
        "reviewed_fee_schedule_fingerprint": (
            active_fee_review_fingerprint
            if is_sha256(active_fee_review_fingerprint)
            else None
        ),
        "execution_closure_fingerprint": execution_closure.get("evidence_fingerprint"),
        "financial_readiness_scope": "risk_and_paper_shadow_attempt_only",
        "risk_evaluation_performed": False,
        "paper_shadow_run_performed": False,
        "manual_ticket_created": False,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "profitability_claim": "not_established",
        "limitations": [
            "Passing this preflight permits only the canonical risk and paper/shadow attempt.",
            "A manual ticket still requires the post-shadow production gate and separate human confirmation.",
            "This projection does not establish current or future profitability.",
        ],
    }
    return {**core, "preflight_fingerprint": fingerprint_json(core)}


def unavailable_daily_candidate_financial_preflight(
    *,
    blocker: str = "daily_candidate_financial_preflight_source_unavailable",
) -> dict[str, Any]:
    """Return the canonical fail-closed shape when a read source is unavailable."""

    core = {
        "schema_version": DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION,
        "status": "no_action",
        "run_date": None,
        "financial_gate_status": "blocked",
        "operational_gate_status": "blocked",
        "eligible_candidate_count": 0,
        "eligible_to_start_manual_attempt": False,
        "eligible_for_background_attempt": False,
        "eligible_to_create_manual_ticket": False,
        "gates": [],
        "financial_blockers": [blocker],
        "operational_blockers": [],
        "no_action_reasons": [blocker],
        "next_safe_action": "restore_persisted_preflight_sources_before_next_window",
        "operator_checklist": [
            build_preflight_operator_step(
                step=1,
                gate="source_evidence",
                action="restore_persisted_preflight_sources_before_next_window",
                blockers=[blocker],
                completion_mode="persisted_evidence_refresh",
            )
        ],
        "decision_plan_fingerprint": None,
        "strategy_binding_fingerprints": [],
        "reviewed_fee_schedule_fingerprint": None,
        "execution_closure_fingerprint": None,
        "financial_readiness_scope": "risk_and_paper_shadow_attempt_only",
        "risk_evaluation_performed": False,
        "paper_shadow_run_performed": False,
        "manual_ticket_created": False,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "profitability_claim": "not_established",
        "limitations": [
            "A missing or invalid read source fails closed before risk or paper/shadow.",
            "No manual ticket, broker action, ledger mutation, or capital change is authorized.",
        ],
    }
    return {**core, "preflight_fingerprint": fingerprint_json(core)}
