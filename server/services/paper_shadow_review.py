"""Review projections for deterministic paper/shadow runs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from execution.paper_broker import PaperBrokerResult
from server.services.paper_shadow_values import (
    account_truth_snapshot as _account_truth_snapshot,
)
from server.services.paper_shadow_values import (
    broker_account_truth_state as _broker_account_truth_state,
)
from server.services.paper_shadow_values import (
    current_account_facts as _current_account_facts,
)
from server.services.paper_shadow_values import decimal_or_zero as _decimal_or_zero
from server.services.paper_shadow_values import dedupe_refs as _dedupe_refs
from server.services.paper_shadow_values import dict_value as _dict
from server.services.paper_shadow_values import (
    fill_count_by_order as _fill_count_by_order,
)
from server.services.paper_shadow_values import float_or_none as _float_or_none
from server.services.paper_shadow_values import order_intent_ref as _order_intent_ref
from server.services.paper_shadow_values import (
    order_intent_snapshot as _order_intent_snapshot,
)
from server.services.paper_shadow_values import refs_with_prefix as _refs_with_prefix
from server.services.paper_shadow_values import string_or_none as _string_or_none
from server.services.paper_shadow_values import value_counts as _value_counts


def _run_status(
    *,
    order_intent_count: int,
    simulated_order_count: int,
    order_summaries: list[dict[str, Any]],
    limitations: list[str],
) -> tuple[str, str, str]:
    if order_intent_count == 0:
        return "not_required", "not_required", "none"
    if any(
        order.get("status") == "failed" or order.get("divergence_status") == "failed"
        for order in order_summaries
    ):
        return "failed", "failed", "inspect_failed_run"
    if limitations or simulated_order_count < order_intent_count:
        return "review_required", "review_required", "review_shadow_divergence"
    if all(order.get("status") == "filled" for order in order_summaries):
        return (
            "within_expectations",
            "within_expectations",
            "review_manual_confirmation",
        )
    if any(order.get("divergence_status") == "diverged" for order in order_summaries):
        return "diverged", "diverged", "resolve_shadow_divergence"
    return "review_required", "review_required", "review_shadow_divergence"


def _divergence_status(result: PaperBrokerResult) -> str:
    if result.order.status.value == "filled":
        return "within_expectations"
    if result.order.status.value in {
        "partially_filled",
        "rejected",
        "cancelled",
        "expired",
    }:
        return "diverged"
    return "review_required"


def _divergence_summary(
    *,
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
    divergence_status: str,
    next_manual_review_step: str,
) -> dict[str, Any]:
    return {
        "status": divergence_status,
        "order_intent_count": len(order_intents),
        "simulated_order_count": len(order_summaries),
        "simulated_fill_count": len(fill_summaries),
        "missing_simulation_count": max(
            len(order_intents) - len(order_summaries),
            0,
        ),
        "diverged_order_count": sum(
            1
            for order in order_summaries
            if order.get("divergence_status") in {"diverged", "failed"}
        ),
        "current_account_facts": _current_account_facts(
            trading_plan,
            order_intents,
        ),
        "broker_account_truth_state": _broker_account_truth_state(trading_plan),
        "cost_summary": _cost_summary(order_intents, fill_summaries),
        "expected_strategy_behavior": _expected_strategy_behavior(
            trading_plan,
            order_intents,
        ),
        "execution_comparison": _execution_comparison(
            order_intents=order_intents,
            order_summaries=order_summaries,
            fill_summaries=fill_summaries,
        ),
        "realized_market_context": _realized_market_context(
            order_intents=order_intents,
            fill_summaries=fill_summaries,
        ),
        "next_manual_review_step": next_manual_review_step,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _run_evidence_refs(
    *,
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> list[str]:
    refs: list[str] = []
    for index, intent in enumerate(order_intents, start=1):
        refs.append(_order_intent_ref(intent, index))
        refs.extend(str(item) for item in intent.get("evidence_refs") or [])
    refs.extend(
        f"paper_order:{order['order_id']}"
        for order in order_summaries
        if order.get("order_id")
    )
    refs.extend(
        f"paper_fill:{fill['fill_id']}"
        for fill in fill_summaries
        if fill.get("fill_id")
    )
    for order in order_summaries:
        order_id = str(order.get("order_id") or "").strip()
        if not order_id:
            continue
        for transition in order.get("oms_transitions") or []:
            if not isinstance(transition, dict):
                continue
            sequence = transition.get("sequence")
            to_status = str(transition.get("to_status") or "").strip()
            if sequence is None or not to_status:
                continue
            refs.append(f"oms_transition:{order_id}:{sequence}:{to_status}")
    return _dedupe_refs(refs)


def _review_queue(
    *,
    run_id: str,
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
    limitations: list[str],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    simulated_refs: set[str] = set()
    intents_by_ref = {
        _order_intent_ref(intent, index): intent
        for index, intent in enumerate(order_intents, start=1)
    }
    fills_by_order = _fills_by_order(fill_summaries)
    for order in order_summaries:
        intent = _dict(order.get("order_intent"))
        intent_ref = str(intent.get("action_ref") or "").strip()
        source_intent = intents_by_ref.get(intent_ref, intent)
        order_fills = fills_by_order.get(str(order.get("order_id") or ""), [])
        if intent_ref:
            simulated_refs.add(intent_ref)
        status = str(order.get("status") or "").strip()
        divergence_status = str(order.get("divergence_status") or "").strip()
        if status == "filled" and divergence_status == "within_expectations":
            continue
        if status == "failed" or divergence_status == "failed":
            required_action = "inspect_failed_run"
            severity = "danger"
            reason = (
                f"Paper/shadow simulation failed for {intent_ref}: "
                f"{order.get('error_type')}: {order.get('error')}"
            )
        elif divergence_status == "diverged":
            required_action = "resolve_shadow_divergence"
            severity = "warning"
            reason = (
                f"Paper/shadow order {status}; compare simulated execution "
                "with the original order intent before manual confirmation."
            )
        else:
            required_action = "review_shadow_divergence"
            severity = "warning"
            reason = "Paper/shadow order requires review before manual confirmation."
        item = {
            "review_id": f"{run_id}:{_review_ref_suffix(intent_ref)}",
            "order_intent_ref": intent_ref,
            "order_id": order.get("order_id"),
            "symbol": order.get("symbol"),
            "status": status,
            "divergence_status": divergence_status or "review_required",
            "severity": severity,
            "required_action": required_action,
            "reason": reason,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
        item.update(
            _review_evidence(
                trading_plan=trading_plan,
                intent_ref=intent_ref,
                intent=source_intent,
                order=order,
                fills=order_fills,
            )
        )
        item.update(_terminal_order_review_evidence(order))
        for key in ("filled_quantity", "remaining_quantity"):
            if order.get(key) is not None:
                item[key] = order.get(key)
        queue.append(item)

    for index, intent in enumerate(order_intents, start=1):
        intent_ref = _order_intent_ref(intent, index)
        if intent_ref in simulated_refs:
            continue
        reasons = [
            limitation
            for limitation in limitations
            if f"order_intent[{index}]" in limitation
        ]
        reason = "; ".join(reasons) if reasons else "Order intent was not simulated."
        queue.append(
            {
                "review_id": f"{run_id}:{_review_ref_suffix(intent_ref)}",
                "order_intent_ref": intent_ref,
                "order_id": None,
                "symbol": str(intent.get("symbol") or ""),
                "status": "missing_simulation",
                "divergence_status": "review_required",
                "severity": "warning",
                "required_action": "review_shadow_divergence",
                "reason": reason,
                "does_not_submit_broker_order": True,
                "does_not_mutate_production_ledger": True,
                **_review_evidence(
                    trading_plan=trading_plan,
                    intent_ref=intent_ref,
                    intent=intent,
                    order={},
                    fills=[],
                ),
            }
        )
    return queue


def _review_evidence(
    *,
    trading_plan: dict[str, Any],
    intent_ref: str,
    intent: dict[str, Any],
    order: dict[str, Any],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    refs = [str(item) for item in intent.get("evidence_refs") or []]
    order_id = str(order.get("order_id") or "").strip()
    return {
        "strategy_refs": _dedupe_refs(_refs_with_prefix(refs, "strategy:")),
        "risk_refs": _dedupe_refs(_refs_with_prefix(refs, "risk:")),
        "signal_refs": _dedupe_refs(_refs_with_prefix(refs, "signal:")),
        "evidence_refs": _dedupe_refs(
            [intent_ref]
            + refs
            + ([f"paper_order:{order_id}"] if order_id else [])
            + [f"paper_fill:{fill['fill_id']}" for fill in fills if fill.get("fill_id")]
        ),
        "account_truth": _broker_account_truth_state(trading_plan),
        "risk_gate_status": intent.get("risk_gate_status"),
        "manual_confirmation_status": intent.get("manual_confirmation_status"),
        "submission_status": intent.get("submission_status"),
        "cash_status": intent.get("cash_status"),
        "constraint_status_counts": _constraint_status_counts(intent),
        "cost_evidence": _review_cost_evidence(intent, fills),
        "market_context": _review_market_context(intent, fills),
        **_review_oms_transition_evidence(order),
    }


def _terminal_order_review_evidence(order: dict[str, Any]) -> dict[str, Any]:
    status = str(order.get("status") or "").strip()
    if status not in {"rejected", "cancelled", "expired"}:
        return {}
    transitions = [
        item for item in order.get("oms_transitions") or [] if isinstance(item, dict)
    ]
    terminal = next(
        (
            item
            for item in reversed(transitions)
            if str(item.get("to_status") or "").strip() == status
        ),
        None,
    )
    if terminal is None:
        return {"terminal_status": status}
    order_id = str(order.get("order_id") or "").strip()
    sequence = terminal.get("sequence")
    evidence = {
        "terminal_status": status,
        "terminal_reason": str(terminal.get("reason") or ""),
    }
    if order_id and sequence is not None:
        evidence["terminal_oms_transition_ref"] = (
            f"oms_transition:{order_id}:{sequence}:{status}"
        )
    return evidence


def _review_oms_transition_evidence(order: dict[str, Any]) -> dict[str, Any]:
    transitions = [
        item for item in order.get("oms_transitions") or [] if isinstance(item, dict)
    ]
    order_id = str(order.get("order_id") or "").strip()
    summarized = [_review_oms_transition(item) for item in transitions]
    return {
        "oms_status_path": [
            str(item["to_status"]) for item in summarized if item.get("to_status")
        ],
        "oms_transition_refs": [
            f"oms_transition:{order_id}:{item['sequence']}:{item['to_status']}"
            for item in summarized
            if order_id and item.get("sequence") is not None and item.get("to_status")
        ],
        "oms_transitions": summarized,
    }


def _review_oms_transition(transition: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": transition.get("sequence"),
        "from_status": transition.get("from_status"),
        "to_status": transition.get("to_status"),
        "source": transition.get("source"),
        "reason": transition.get("reason") or "",
        "filled_quantity": transition.get("filled_quantity"),
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _constraint_status_counts(intent: dict[str, Any]) -> dict[str, int]:
    checks = intent.get("constraint_checks")
    if not isinstance(checks, list):
        return {}
    return _value_counts(
        check.get("status") for check in checks if isinstance(check, dict)
    )


def _review_cost_evidence(
    intent: dict[str, Any],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    simulated_fee_tax_cost = sum(
        _decimal_or_zero(fill.get("commission")) for fill in fills
    )
    simulated_slippage_cost = sum(
        _decimal_or_zero(fill.get("slippage")) for fill in fills
    )
    return {
        "estimated_gross_amount": _string_or_none(intent.get("estimated_gross_amount")),
        "estimated_total_fee": _string_or_none(intent.get("estimated_total_fee")),
        "simulated_fee_tax_cost": str(simulated_fee_tax_cost),
        "simulated_slippage_cost": str(simulated_slippage_cost),
        "fee_rule_id": intent.get("fee_rule_id"),
    }


def _review_market_context(
    intent: dict[str, Any],
    fills: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "price_basis": str(intent.get("price_basis") or "estimated_price"),
        "expected_price": _string_or_none(intent.get("estimated_price")),
        "simulated_fill_prices": [
            str(fill.get("fill_price"))
            for fill in fills
            if fill.get("fill_price") is not None
        ],
    }


def _fills_by_order(
    fill_summaries: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    fills_by_order: dict[str, list[dict[str, Any]]] = {}
    for fill in fill_summaries:
        order_id = str(fill.get("order_id") or "").strip()
        if not order_id:
            continue
        fills_by_order.setdefault(order_id, []).append(fill)
    return fills_by_order


def _review_ref_suffix(intent_ref: str) -> str:
    if ":" in intent_ref:
        return intent_ref.split(":", 1)[1]
    return intent_ref or "unknown"


def _expected_strategy_behavior(
    trading_plan: dict[str, Any],
    order_intents: list[dict[str, Any]],
) -> dict[str, Any]:
    refs: list[str] = []
    for intent in order_intents:
        refs.extend(str(item) for item in intent.get("evidence_refs") or [])
    return {
        "source_decision": trading_plan.get("source_decision"),
        "expected_order_count": len(order_intents),
        "symbols": _dedupe_refs(
            [
                str(intent.get("symbol"))
                for intent in order_intents
                if intent.get("symbol")
            ]
        ),
        "side_counts": _value_counts(intent.get("side") for intent in order_intents),
        "strategy_refs": _dedupe_refs(_refs_with_prefix(refs, "strategy:")),
        "risk_refs": _dedupe_refs(_refs_with_prefix(refs, "risk:")),
        "signal_refs": _dedupe_refs(_refs_with_prefix(refs, "signal:")),
        "risk_gate_status_counts": _value_counts(
            intent.get("risk_gate_status") for intent in order_intents
        ),
        "manual_confirmation_status_counts": _value_counts(
            intent.get("manual_confirmation_status") for intent in order_intents
        ),
        "submission_status_counts": _value_counts(
            intent.get("submission_status") for intent in order_intents
        ),
    }


def _execution_comparison(
    *,
    order_intents: list[dict[str, Any]],
    order_summaries: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_refs = [
        _order_intent_ref(intent, index)
        for index, intent in enumerate(order_intents, start=1)
    ]
    orders_by_ref = {
        str(_dict(order.get("order_intent")).get("action_ref")): order
        for order in order_summaries
        if _dict(order.get("order_intent")).get("action_ref")
    }
    missing_refs = [ref for ref in expected_refs if ref not in orders_by_ref]
    diverged_refs = [
        str(_dict(order.get("order_intent")).get("action_ref"))
        for order in order_summaries
        if order.get("divergence_status") == "diverged"
        and _dict(order.get("order_intent")).get("action_ref")
    ]
    failed_refs = [
        str(_dict(order.get("order_intent")).get("action_ref"))
        for order in order_summaries
        if order.get("divergence_status") == "failed"
        and _dict(order.get("order_intent")).get("action_ref")
    ]
    return {
        "matched_order_count": len(expected_refs) - len(missing_refs),
        "missing_order_intent_refs": missing_refs,
        "diverged_order_refs": diverged_refs,
        "failed_order_refs": failed_refs,
        "simulated_status_counts": _value_counts(
            order.get("status") for order in order_summaries
        ),
        "fill_count_by_order": _fill_count_by_order(fill_summaries),
        "filled_quantity_by_order": {
            str(order["order_id"]): str(order.get("filled_quantity"))
            for order in order_summaries
            if order.get("order_id") and order.get("filled_quantity") is not None
        },
        "remaining_quantity_by_order": {
            str(order["order_id"]): str(order.get("remaining_quantity"))
            for order in order_summaries
            if order.get("order_id") and order.get("remaining_quantity") is not None
        },
    }


def _realized_market_context(
    *,
    order_intents: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    fills_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for fill in fill_summaries:
        symbol = str(fill.get("symbol") or "")
        if not symbol:
            continue
        fills_by_symbol.setdefault(symbol, []).append(fill)
    symbols: list[dict[str, Any]] = []
    for intent in order_intents:
        symbol = str(intent.get("symbol") or "")
        if not symbol:
            continue
        symbol_fills = fills_by_symbol.get(symbol, [])
        symbols.append(
            {
                "symbol": symbol,
                "price_basis": str(intent.get("price_basis") or "estimated_price"),
                "expected_price": _float_or_none(intent.get("estimated_price")),
                "simulated_fill_prices": [
                    str(fill.get("fill_price"))
                    for fill in symbol_fills
                    if fill.get("fill_price") is not None
                ],
                "simulated_slippage_cost": str(
                    sum(_decimal_or_zero(fill.get("slippage")) for fill in symbol_fills)
                ),
            }
        )
    return {
        "symbol_count": len(symbols),
        "price_basis_counts": _value_counts(
            str(intent.get("price_basis") or "estimated_price")
            for intent in order_intents
        ),
        "symbols": symbols,
    }


def _cost_summary(
    order_intents: list[dict[str, Any]],
    fill_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    estimated_total_fee = sum(
        _decimal_or_zero(intent.get("estimated_total_fee")) for intent in order_intents
    )
    simulated_fee_tax_cost = sum(
        _decimal_or_zero(fill.get("commission")) for fill in fill_summaries
    )
    simulated_slippage_cost = sum(
        _decimal_or_zero(fill.get("slippage")) for fill in fill_summaries
    )
    fee_rule_ids = _dedupe_refs(
        [
            str(intent.get("fee_rule_id"))
            for intent in order_intents
            if intent.get("fee_rule_id")
        ]
    )
    return {
        "estimated_total_fee": str(estimated_total_fee),
        "simulated_fee_tax_cost": str(simulated_fee_tax_cost),
        "simulated_slippage_cost": str(simulated_slippage_cost),
        "simulated_total_execution_cost": str(
            simulated_fee_tax_cost + simulated_slippage_cost
        ),
        "fee_rule_ids": fee_rule_ids,
        "fill_count_with_cost_evidence": len(
            [
                fill
                for fill in fill_summaries
                if fill.get("commission") is not None or fill.get("fee_breakdown")
            ]
        ),
    }


run_status = _run_status
divergence_status = _divergence_status
divergence_summary = _divergence_summary
run_evidence_refs = _run_evidence_refs
review_queue = _review_queue
review_evidence = _review_evidence
terminal_order_review_evidence = _terminal_order_review_evidence
review_oms_transition_evidence = _review_oms_transition_evidence
review_oms_transition = _review_oms_transition
constraint_status_counts = _constraint_status_counts
review_cost_evidence = _review_cost_evidence
review_market_context = _review_market_context
fills_by_order = _fills_by_order
review_ref_suffix = _review_ref_suffix
expected_strategy_behavior = _expected_strategy_behavior
execution_comparison = _execution_comparison
realized_market_context = _realized_market_context
cost_summary = _cost_summary
value_counts = _value_counts
fill_count_by_order = _fill_count_by_order
