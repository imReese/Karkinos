"""Canonical strategy-to-signal/order/fill evidence linkage helpers."""

from __future__ import annotations

import json
from typing import Any

from server.models import AccountStrategyAssignment


def json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def source_signal_id(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def same_symbol(left: Any, right: str) -> bool:
    return str(left or "").strip().lower() == right.strip().lower()


def assignment_matches_signal(
    assignment: AccountStrategyAssignment,
    signal: dict[str, Any],
) -> bool:
    if signal.get("strategy_id") != assignment.strategy_id:
        return False
    if assignment.scope == "asset_class" and assignment.asset_class:
        return signal.get("asset_class") == assignment.asset_class
    if assignment.scope == "symbol" and assignment.symbol:
        return signal.get("symbol") == assignment.symbol
    return True


def order_source_signal_id(order: dict[str, Any]) -> int | None:
    payload = json_dict(order.get("payload_json"))
    return source_signal_id(
        payload.get("source_signal_id")
        or payload.get("signal_id")
        or payload.get("intent", {}).get("source_signal_id")
    )


def fill_metadata(fill: dict[str, Any]) -> dict[str, Any]:
    return json_dict(fill.get("metadata_json"))


def is_simulation_order(order: dict[str, Any]) -> bool:
    payload = json_dict(order.get("payload_json"))
    execution_mode = str(
        order.get("execution_mode") or payload.get("execution_mode") or ""
    ).lower()
    return execution_mode in {"paper", "paper_shadow", "shadow", "backtest"}


def linked_strategy_evidence(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> dict[str, Any]:
    """Resolve persisted strategy evidence without simulation contamination."""
    journal_reader = getattr(db, "list_signal_journal_sync", None)
    order_reader = getattr(db, "list_orders_sync", None)
    fill_reader = getattr(db, "list_fills_sync", None)

    journal_entries = (
        journal_reader(limit=500, offset=0) if callable(journal_reader) else []
    )
    strategy_entries = [
        entry
        for entry in journal_entries
        if assignment_matches_signal(assignment, entry.get("signal") or {})
    ]
    signal_ids = {
        int(entry["signal"]["id"])
        for entry in strategy_entries
        if (entry.get("signal") or {}).get("id") is not None
    }
    risk_decisions = [
        entry.get("risk_decision")
        for entry in strategy_entries
        if entry.get("risk_decision") is not None
    ]
    risk_decision_ids = {
        str(risk["decision_id"])
        for risk in risk_decisions
        if risk and risk.get("decision_id")
    }
    intent_ids = {
        str(risk["intent_id"])
        for risk in risk_decisions
        if risk and risk.get("intent_id")
    }

    all_orders = order_reader(limit=1000, offset=0) if callable(order_reader) else []
    excluded_simulation_order_ids = {
        str(order.get("order_id")) for order in all_orders if is_simulation_order(order)
    }
    orders = [order for order in all_orders if not is_simulation_order(order)]
    linked_orders = []
    for order in orders:
        linked_signal_id = order_source_signal_id(order)
        if (
            linked_signal_id in signal_ids
            or order.get("risk_decision_id") in risk_decision_ids
            or order.get("intent_id") in intent_ids
        ):
            linked_orders.append(order)
    linked_order_ids = {str(order["order_id"]) for order in linked_orders}

    fills = fill_reader(limit=1000, offset=0) if callable(fill_reader) else []
    linked_fills = []
    unattributed_fills = []
    unattributed_fill_count = 0
    for fill in fills:
        metadata = fill_metadata(fill)
        if str(fill.get("order_id")) in excluded_simulation_order_ids or str(
            metadata.get("execution_mode") or ""
        ).lower() in {"paper", "paper_shadow", "shadow", "backtest"}:
            continue
        metadata_signal_id = source_signal_id(
            metadata.get("source_signal_id") or metadata.get("signal_id")
        )
        metadata_strategy_id = metadata.get("strategy_id")
        order_linked = str(fill.get("order_id")) in linked_order_ids
        if order_linked or metadata_signal_id in signal_ids:
            linked_fills.append(fill)
        elif metadata_strategy_id == assignment.strategy_id:
            unattributed_fills.append(fill)
            unattributed_fill_count += 1

    return {
        "strategy_entries": strategy_entries,
        "signal_ids": signal_ids,
        "risk_decisions": risk_decisions,
        "linked_orders": linked_orders,
        "linked_fills": linked_fills,
        "unattributed_fills": unattributed_fills,
        "unattributed_fill_count": unattributed_fill_count,
    }
