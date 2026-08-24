"""Deterministic post-shadow production outcome projection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from server.services.account_truth_replay import verify_account_truth_replay_evidence
from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION,
    DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION,
    DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
    TERMINAL_EVIDENCE_STATUSES,
)
from server.services.daily_decision_evidence_identity import (
    manual_ticket_candidate_fingerprint,
)
from server.services.daily_decision_evidence_values import (
    aware_datetime,
    count,
    finite_float,
    is_sha256,
    nonnegative_float,
    object_dict,
    object_list,
    positive_float,
    shanghai_date,
    single_ref,
)
from server.services.daily_decision_policy_gates import (
    build_daily_candidate_base_gate,
)
from server.services.daily_decision_strategy_gate import resolve_strategy_gate_binding


def project_production_outcome(
    *,
    cycle_status: str,
    plan_date: str,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
    paper_shadow: dict[str, Any],
    execution_closure: dict[str, Any],
    account_truth_replay: dict[str, Any],
    additional_blockers: list[str],
) -> dict[str, Any]:
    """Resolve one deterministic ticket-candidate or NO-ACTION conclusion."""

    base_gate = build_daily_candidate_base_gate(
        decision_payload=decision_payload,
        trading_plan=trading_plan,
        plan_date=plan_date,
    )
    blockers = [*additional_blockers, *base_gate["blockers"]]
    _validate_account_truth_replay(
        blockers=blockers,
        base_gate=base_gate,
        account_truth_replay=account_truth_replay,
    )

    order_intents = object_list(trading_plan.get("order_intents"))
    (
        strategy_bindings,
        strategy_gate_bindings,
        market_quote_bindings,
        candidate_count,
    ) = _collect_order_intent_evidence(
        blockers=blockers,
        order_intents=order_intents,
        decision_payload=decision_payload,
        base_gate=base_gate,
        plan_date=plan_date,
    )
    _validate_terminal_evidence(
        blockers=blockers,
        cycle_status=cycle_status,
        order_intents=order_intents,
        paper_shadow=paper_shadow,
        execution_closure=execution_closure,
    )

    blockers = list(dict.fromkeys(blockers))
    gate_status = "pass" if not blockers else "blocked"
    decision_outcome = (
        "manual_order_ticket_candidate"
        if gate_status == "pass" and candidate_count > 0
        else "no_action"
    )
    decision_no_action_reasons = [
        str(item)
        for item in decision_payload.get("no_action_reasons") or []
        if str(item)
    ]
    no_action_reasons = (
        []
        if decision_outcome == "manual_order_ticket_candidate"
        else blockers or decision_no_action_reasons or ["no_strategy_action"]
    )
    account_truth_binding = _build_account_truth_binding(
        base_gate=base_gate,
        account_truth_replay=account_truth_replay,
    )
    decision_generated_at = base_gate["decision_generated_at"]
    manual_order_ticket_candidates = (
        [
            build_manual_order_ticket_candidate(
                plan_date=plan_date,
                intent=intent,
                paper_shadow=paper_shadow,
                execution_closure=execution_closure,
                decision_generated_at=decision_generated_at,
                strategy_gate_binding=next(
                    (
                        item
                        for item in strategy_gate_bindings
                        if str(item.get("action_id") or "")
                        == str(intent.get("action_id") or "")
                    ),
                    {},
                ),
                account_truth_binding=account_truth_binding,
            )
            for intent in order_intents
        ]
        if decision_outcome == "manual_order_ticket_candidate"
        else []
    )
    input_snapshot = _build_input_snapshot(
        base_gate=base_gate,
        account_truth_replay=account_truth_replay,
        account_truth_binding=account_truth_binding,
        paper_shadow=paper_shadow,
        execution_closure=execution_closure,
        order_intents=order_intents,
        strategy_bindings=strategy_bindings,
        strategy_gate_bindings=strategy_gate_bindings,
        market_quote_bindings=market_quote_bindings,
    )
    return {
        "decision_outcome": decision_outcome,
        "manual_ticket_candidate_count": len(manual_order_ticket_candidates),
        "manual_order_ticket_candidates": manual_order_ticket_candidates,
        "no_action_reasons": no_action_reasons,
        "strategy_bindings": strategy_bindings,
        "input_snapshot": input_snapshot,
        "production_gate": {
            "schema_version": "karkinos.daily_candidate_production_gate.v1",
            "status": gate_status,
            "blockers": blockers,
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
    }


def _validate_account_truth_replay(
    *,
    blockers: list[str],
    base_gate: dict[str, Any],
    account_truth_replay: dict[str, Any],
) -> None:
    if not verify_account_truth_replay_evidence(account_truth_replay):
        blockers.append("account_truth_replay_evidence_invalid")
    elif account_truth_replay.get("status") != "pass":
        blockers.extend(
            f"account_truth_replay:{item}"
            for item in account_truth_replay.get("blockers") or []
            if str(item)
        )
        blockers.append("account_truth_replay_not_clear")
    account_truth_ref = str(base_gate["account_truth_ref"])
    expected_account_truth_ref = (
        f"account_truth:{account_truth_ref}" if account_truth_ref else None
    )
    if account_truth_replay.get("account_truth_ref") != expected_account_truth_ref:
        blockers.append("account_truth_replay_import_ref_mismatch")
    if account_truth_replay.get("source_fingerprint") != (
        str(base_gate["account_truth_source_fingerprint"]) or None
    ):
        blockers.append("account_truth_replay_source_fingerprint_mismatch")
    if account_truth_replay.get("valuation_snapshot_id") != (
        str(base_gate["valuation_snapshot_id"]) or None
    ):
        blockers.append("account_truth_replay_valuation_snapshot_mismatch")
    if account_truth_replay.get("ledger_cutoff_id") != base_gate["ledger_cutoff_id"]:
        blockers.append("account_truth_replay_ledger_cutoff_mismatch")


def _collect_order_intent_evidence(
    *,
    blockers: list[str],
    order_intents: list[dict[str, Any]],
    decision_payload: dict[str, Any],
    base_gate: dict[str, Any],
    plan_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    strategy_bindings: list[dict[str, Any]] = []
    strategy_gate_bindings: list[dict[str, Any]] = []
    market_quote_bindings: list[dict[str, Any]] = []
    decision_candidates: dict[str, list[dict[str, Any]]] = {}
    for candidate in object_list(decision_payload.get("candidates")):
        candidate_key = str(candidate.get("action_id") or "")
        if candidate_key:
            decision_candidates.setdefault(candidate_key, []).append(candidate)

    decision_generated_at = base_gate["decision_generated_at"]
    account_truth_ref = str(base_gate["account_truth_ref"])
    candidate_count = 0
    for index, intent in enumerate(order_intents):
        prefix = f"order_intent_{index}"
        if str(intent.get("asset_class") or "").strip().lower() != "stock":
            blockers.append(f"{prefix}:asset_class_outside_daily_candidate_scope")
        evidence_refs = [
            str(item) for item in intent.get("evidence_refs") or [] if str(item)
        ]
        strategy_ref = single_ref(evidence_refs, "strategy:")
        advancement_ref = single_ref(evidence_refs, "strategy_advancement:")
        fee_review_ref = single_ref(evidence_refs, "reviewed_fee_schedule:")
        risk_ref = single_ref(evidence_refs, "risk:")
        intent_account_truth_ref = single_ref(evidence_refs, "account_truth:")
        action_key = str(intent.get("action_id") or "")
        matching_candidates = decision_candidates.get(action_key, [])
        if len(matching_candidates) != 1:
            blockers.append(f"{prefix}:decision_candidate_binding_not_unique")
            candidate = {}
        else:
            candidate = matching_candidates[0]
        strategy_gate_binding, strategy_gate_blockers = resolve_strategy_gate_binding(
            candidate=candidate,
            plan_date=plan_date,
            expected_strategy_ref=strategy_ref,
            expected_advancement_ref=advancement_ref,
            expected_fee_review_ref=fee_review_ref,
            action_id=intent.get("action_id"),
        )
        blockers.extend(f"{prefix}:{item}" for item in strategy_gate_blockers)
        if strategy_gate_binding:
            strategy_gate_bindings.append(strategy_gate_binding)
        if not strategy_ref:
            blockers.append(f"{prefix}:strategy_ref_missing_or_ambiguous")
        if not advancement_ref:
            blockers.append(f"{prefix}:strategy_advancement_ref_missing_or_ambiguous")
        if not fee_review_ref:
            blockers.append(f"{prefix}:reviewed_fee_schedule_ref_missing_or_ambiguous")
        if not risk_ref:
            blockers.append(f"{prefix}:risk_ref_missing_or_ambiguous")
        if intent_account_truth_ref != (
            f"account_truth:{account_truth_ref}" if account_truth_ref else None
        ):
            blockers.append(f"{prefix}:account_truth_ref_mismatch")
        if str(intent.get("risk_gate_status") or "").lower() != "passed":
            blockers.append(f"{prefix}:risk_gate_not_passed")
        if str(intent.get("submission_status") or "").lower() != (
            "manual_confirmation_required"
        ):
            blockers.append(f"{prefix}:manual_confirmation_not_ready")
        if not str(intent.get("fee_rule_id") or ""):
            blockers.append(f"{prefix}:fee_rule_id_missing")
        if nonnegative_float(intent.get("estimated_total_fee")) is None:
            blockers.append(f"{prefix}:estimated_fee_invalid")
        if positive_float(intent.get("estimated_quantity")) is None:
            blockers.append(f"{prefix}:estimated_quantity_invalid")
        if positive_float(intent.get("estimated_gross_amount")) is None:
            blockers.append(f"{prefix}:estimated_gross_amount_invalid")
        if finite_float(intent.get("estimated_net_cash_impact")) is None:
            blockers.append(f"{prefix}:estimated_net_cash_impact_invalid")
        constraint_checks = object_list(intent.get("constraint_checks"))
        if not constraint_checks:
            blockers.append(f"{prefix}:constraint_checks_missing")
        elif any(
            str(check.get("status") or "").lower() != "pass"
            for check in constraint_checks
        ):
            blockers.append(f"{prefix}:constraint_check_not_passed")
        fee_breakdown = object_dict(intent.get("fee_breakdown"))
        if not fee_breakdown:
            blockers.append(f"{prefix}:fee_breakdown_missing")
        intent_quote_at = aware_datetime(intent.get("market_quote_timestamp"))
        intent_quote_price = nonnegative_float(intent.get("market_quote_price"))
        intent_estimated_price = nonnegative_float(intent.get("estimated_price"))
        intent_quote_source = str(intent.get("market_quote_source") or "").strip()
        if shanghai_date(intent_quote_at) != plan_date:
            blockers.append(f"{prefix}:market_quote_not_bound_to_plan_date")
        if (
            intent_quote_at is not None
            and decision_generated_at is not None
            and intent_quote_at > decision_generated_at
        ):
            blockers.append(f"{prefix}:market_quote_after_decision_generation")
        elif (
            intent_quote_at is not None
            and decision_generated_at is not None
            and (decision_generated_at - intent_quote_at).total_seconds()
            > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS
        ):
            blockers.append(f"{prefix}:market_quote_too_old_for_decision")
        if not intent_quote_source:
            blockers.append(f"{prefix}:market_quote_source_missing")
        if intent_quote_price is None or intent_quote_price <= 0:
            blockers.append(f"{prefix}:market_quote_price_invalid")
        if (
            intent_estimated_price is None
            or intent_estimated_price <= 0
            or intent_estimated_price != intent_quote_price
        ):
            blockers.append(f"{prefix}:estimated_price_not_bound_to_market_quote")
        if intent.get("does_not_submit_broker_order") is not True:
            blockers.append(f"{prefix}:broker_boundary_invalid")
        if strategy_ref and advancement_ref:
            strategy_bindings.append(
                {
                    "strategy_ref": strategy_ref,
                    "strategy_advancement_ref": advancement_ref,
                    "reviewed_fee_schedule_ref": fee_review_ref,
                }
            )
        market_quote_bindings.append(
            {
                "intent_ref": str(
                    intent.get("intent_id") or intent.get("action_id") or index
                ),
                "timestamp": (
                    intent_quote_at.isoformat() if intent_quote_at is not None else None
                ),
                "source": intent_quote_source or None,
                "price": intent_quote_price,
            }
        )
        candidate_count += 1
    return (
        strategy_bindings,
        strategy_gate_bindings,
        market_quote_bindings,
        candidate_count,
    )


def _validate_terminal_evidence(
    *,
    blockers: list[str],
    cycle_status: str,
    order_intents: list[dict[str, Any]],
    paper_shadow: dict[str, Any],
    execution_closure: dict[str, Any],
) -> None:
    if order_intents:
        if paper_shadow.get("status") != "within_expectations":
            blockers.append("paper_shadow_status_not_within_expectations")
        if paper_shadow.get("divergence_status") != "within_expectations":
            blockers.append("paper_shadow_divergence_not_clear")
        if not paper_shadow.get("run_id") or not paper_shadow.get("input_fingerprint"):
            blockers.append("paper_shadow_identity_missing")
        if count(paper_shadow.get("simulated_order_count")) != len(order_intents):
            blockers.append("paper_shadow_order_count_mismatch")
        if count(paper_shadow.get("simulated_fill_count")) != len(order_intents):
            blockers.append("paper_shadow_fill_count_mismatch")
    elif paper_shadow.get("status") not in {"not_run", None}:
        blockers.append("paper_shadow_present_without_order_intent")

    if cycle_status not in TERMINAL_EVIDENCE_STATUSES:
        blockers.append(f"daily_cycle_not_evidence_clear:{cycle_status}")

    if execution_closure.get("schema_version") != (
        "karkinos.daily_candidate_execution_closure.v1"
    ):
        blockers.append("execution_closure_contract_invalid")
    if execution_closure.get("status") not in {"pass", "not_required"}:
        closure_blockers = [
            str(item) for item in execution_closure.get("blockers") or [] if str(item)
        ]
        blockers.extend(f"execution_closure:{item}" for item in closure_blockers)
        blockers.append("prior_execution_not_reconciled")
    if not is_sha256(execution_closure.get("evidence_fingerprint")):
        blockers.append("execution_closure_fingerprint_invalid")


def _build_account_truth_binding(
    *,
    base_gate: dict[str, Any],
    account_truth_replay: dict[str, Any],
) -> dict[str, Any]:
    account_truth = object_dict(base_gate["account_truth"])
    ledger_coverage = object_dict(base_gate["ledger_coverage"])
    captured_at = base_gate["account_truth_captured_at"]
    account_truth_ref = str(base_gate["account_truth_ref"])
    return {
        "schema_version": "karkinos.daily_candidate_account_truth_binding.v2",
        "account_truth_ref": (
            f"account_truth:{account_truth_ref}" if account_truth_ref else None
        ),
        "source_fingerprint": (
            str(base_gate["account_truth_source_fingerprint"]) or None
        ),
        "captured_at": captured_at.isoformat() if captured_at is not None else None,
        "age_seconds_at_decision": base_gate["account_truth_age_at_decision"],
        "max_age_seconds": base_gate["account_truth_max_age"],
        "valuation_snapshot_id": str(base_gate["valuation_snapshot_id"]) or None,
        "ledger_cutoff_id": base_gate["ledger_cutoff_id"],
        "reconciliation_status": account_truth.get("reconciliation_status"),
        "ledger_coverage_status": ledger_coverage.get("status"),
        "replay_evidence": account_truth_replay,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _build_input_snapshot(
    *,
    base_gate: dict[str, Any],
    account_truth_replay: dict[str, Any],
    account_truth_binding: dict[str, Any],
    paper_shadow: dict[str, Any],
    execution_closure: dict[str, Any],
    order_intents: list[dict[str, Any]],
    strategy_bindings: list[dict[str, Any]],
    strategy_gate_bindings: list[dict[str, Any]],
    market_quote_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    account_truth = object_dict(base_gate["account_truth"])
    ledger_coverage = object_dict(base_gate["ledger_coverage"])
    account_truth_ref = str(base_gate["account_truth_ref"])
    captured_at = base_gate["account_truth_captured_at"]
    quote_at = base_gate["quote_at"]
    decision_generated_at = base_gate["decision_generated_at"]
    plan_generated_at = base_gate["plan_generated_at"]
    decision_in_window = bool(base_gate["decision_in_window"])
    plan_in_window = bool(base_gate["plan_in_window"])
    return {
        "decision_date": str(base_gate["decision_date"]) or None,
        "plan_date": str(base_gate["plan_contract_date"]) or None,
        "valuation_snapshot_id": str(base_gate["valuation_snapshot_id"]) or None,
        "ledger_cutoff_id": base_gate["ledger_cutoff_id"],
        "account_truth_ref": (
            f"account_truth:{account_truth_ref}" if account_truth_ref else None
        ),
        "account_truth_source_fingerprint": (
            str(base_gate["account_truth_source_fingerprint"]) or None
        ),
        "account_truth_captured_at": (
            captured_at.isoformat() if captured_at is not None else None
        ),
        "account_truth_age_seconds_at_decision": base_gate[
            "account_truth_age_at_decision"
        ],
        "account_truth_max_age_seconds": base_gate["account_truth_max_age"],
        "account_truth_reconciliation_status": account_truth.get(
            "reconciliation_status"
        ),
        "account_truth_ledger_coverage_status": ledger_coverage.get("status"),
        "account_truth_replay_evidence": account_truth_replay,
        "account_truth_binding": account_truth_binding,
        "market_quote_timestamp": str(base_gate["quote_timestamp"]) or None,
        "market_quote_age_seconds_at_decision": (
            int((decision_generated_at - quote_at).total_seconds())
            if decision_generated_at is not None
            and quote_at is not None
            and quote_at <= decision_generated_at
            else None
        ),
        "market_quote_max_age_seconds": DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
        "decision_window": {
            "schema_version": DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION,
            "timezone": "Asia/Shanghai",
            "start": "09:35",
            "end_exclusive": "09:45",
            "decision_generated_at": (
                decision_generated_at.isoformat()
                if decision_generated_at is not None
                else None
            ),
            "plan_generated_at": (
                plan_generated_at.isoformat() if plan_generated_at is not None else None
            ),
            "status": "pass" if decision_in_window and plan_in_window else "blocked",
        },
        "paper_shadow_run_id": paper_shadow.get("run_id"),
        "paper_shadow_input_fingerprint": paper_shadow.get("input_fingerprint"),
        "execution_closure_fingerprint": execution_closure.get("evidence_fingerprint"),
        "prior_production_order_count": execution_closure.get("production_order_count"),
        "order_intent_count": len(order_intents),
        "strategy_advancement_refs": sorted(
            {
                item["strategy_advancement_ref"]
                for item in strategy_bindings
                if item.get("strategy_advancement_ref")
            }
        ),
        "reviewed_fee_schedule_refs": sorted(
            {
                item["reviewed_fee_schedule_ref"]
                for item in strategy_bindings
                if item.get("reviewed_fee_schedule_ref")
            }
        ),
        "strategy_gate_bindings": strategy_gate_bindings,
        "market_quote_bindings": market_quote_bindings,
    }


def build_manual_order_ticket_candidate(
    *,
    plan_date: str,
    intent: dict[str, Any],
    paper_shadow: dict[str, Any],
    execution_closure: dict[str, Any],
    decision_generated_at: datetime | None,
    strategy_gate_binding: dict[str, Any],
    account_truth_binding: dict[str, Any],
) -> dict[str, Any]:
    evidence_refs = sorted(
        {str(item) for item in intent.get("evidence_refs") or [] if str(item)}
    )
    quote_at = aware_datetime(intent.get("market_quote_timestamp"))
    quote_age_seconds = (
        int((decision_generated_at - quote_at).total_seconds())
        if decision_generated_at is not None
        and quote_at is not None
        and quote_at <= decision_generated_at
        else None
    )
    core = {
        "schema_version": DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION,
        "plan_date": plan_date,
        "intent_id": intent.get("intent_id"),
        "action_id": intent.get("action_id"),
        "symbol": intent.get("symbol"),
        "side": intent.get("side"),
        "asset_class": intent.get("asset_class"),
        "order_type": "limit",
        "quantity": intent.get("estimated_quantity"),
        "limit_price": intent.get("estimated_price"),
        "estimated_gross_amount": intent.get("estimated_gross_amount"),
        "estimated_total_fee": intent.get("estimated_total_fee"),
        "estimated_net_cash_impact": intent.get("estimated_net_cash_impact"),
        "available_cash_before": intent.get("available_cash_before"),
        "available_cash_after": intent.get("available_cash_after"),
        "cash_status": intent.get("cash_status"),
        "fee_rule_id": intent.get("fee_rule_id"),
        "fee_rule_version": intent.get("fee_rule_version"),
        "fee_breakdown": object_dict(intent.get("fee_breakdown")),
        "risk_gate_status": intent.get("risk_gate_status"),
        "constraint_checks": object_list(intent.get("constraint_checks")),
        "market_quote": {
            "price": intent.get("market_quote_price"),
            "timestamp": intent.get("market_quote_timestamp"),
            "source": intent.get("market_quote_source"),
            "age_seconds_at_decision": quote_age_seconds,
            "max_age_seconds": DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
        },
        "paper_shadow": {
            "run_id": paper_shadow.get("run_id"),
            "input_fingerprint": paper_shadow.get("input_fingerprint"),
            "status": paper_shadow.get("status"),
            "divergence_status": paper_shadow.get("divergence_status"),
        },
        "strategy_gate_binding": strategy_gate_binding,
        "strategy_operating_constraints": object_dict(
            strategy_gate_binding.get("strategy_operating_constraints")
        ),
        "account_truth_binding": account_truth_binding,
        "prior_execution_closure_fingerprint": execution_closure.get(
            "evidence_fingerprint"
        ),
        "evidence_refs": evidence_refs,
        "invalidation_conditions": [
            "plan_date_is_no_longer_current_market_date",
            "decision_or_plan_generated_outside_reviewed_window",
            "account_truth_source_or_ledger_coverage_changes",
            "market_quote_price_timestamp_or_source_changes",
            "risk_strategy_fee_or_paper_shadow_binding_changes",
            "prior_execution_closure_changes",
            "kill_switch_is_enabled",
        ],
        "manual_confirmation_required": True,
        "creates_oms_order": False,
        "authorizes_execution": False,
        "broker_submission_enabled": False,
        "does_not_change_capital_authority": True,
    }
    return {
        **core,
        "ticket_candidate_fingerprint": manual_ticket_candidate_fingerprint(core),
    }
