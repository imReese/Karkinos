"""Manual-review queue projection for paper-shadow order outcomes."""

from __future__ import annotations

from typing import Any

from server.services.paper_shadow_review import (
    fills_by_order,
    review_evidence,
    review_ref_suffix,
    terminal_order_review_evidence,
)
from server.services.paper_shadow_values import (
    dict_value,
    order_intent_ref,
)


def build_paper_shadow_review_queue(
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
        order_intent_ref(intent, index): intent
        for index, intent in enumerate(order_intents, start=1)
    }
    grouped_fills = fills_by_order(fill_summaries)
    for order in order_summaries:
        intent = dict_value(order.get("order_intent"))
        intent_ref = str(intent.get("action_ref") or "").strip()
        source_intent = intents_by_ref.get(intent_ref, intent)
        order_fills = grouped_fills.get(str(order.get("order_id") or ""), [])
        if intent_ref:
            simulated_refs.add(intent_ref)
        status = str(order.get("status") or "").strip()
        divergence_status = str(order.get("divergence_status") or "").strip()
        if status == "filled" and divergence_status == "within_expectations":
            continue
        item = _review_item(
            run_id=run_id,
            trading_plan=trading_plan,
            intent_ref=intent_ref,
            intent=source_intent,
            order=order,
            fills=order_fills,
            status=status,
            divergence_status=divergence_status,
        )
        queue.append(item)

    for index, intent in enumerate(order_intents, start=1):
        intent_ref = order_intent_ref(intent, index)
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
                "review_id": f"{run_id}:{review_ref_suffix(intent_ref)}",
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
                **review_evidence(
                    trading_plan=trading_plan,
                    intent_ref=intent_ref,
                    intent=intent,
                    order={},
                    fills=[],
                ),
            }
        )
    return queue


def _review_item(
    *,
    run_id: str,
    trading_plan: dict[str, Any],
    intent_ref: str,
    intent: dict[str, Any],
    order: dict[str, Any],
    fills: list[dict[str, Any]],
    status: str,
    divergence_status: str,
) -> dict[str, Any]:
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
        "review_id": f"{run_id}:{review_ref_suffix(intent_ref)}",
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
        review_evidence(
            trading_plan=trading_plan,
            intent_ref=intent_ref,
            intent=intent,
            order=order,
            fills=fills,
        )
    )
    item.update(terminal_order_review_evidence(order))
    for key in ("filled_quantity", "remaining_quantity"):
        if order.get(key) is not None:
            item[key] = order.get(key)
    return item


__all__ = ["build_paper_shadow_review_queue"]
