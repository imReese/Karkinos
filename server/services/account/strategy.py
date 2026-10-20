"""Canonical account-strategy assignment, evidence linkage, and attribution projections."""

from __future__ import annotations

import json
from typing import Any

from server.models import (
    AccountStrategyAssignment,
    AccountStrategyAttributionSummary,
    AccountStrategyContributionReport,
)
from server.services.research.strategy_contribution import (
    build_strategy_contribution_report,
)

ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY = "account_strategy_assignment"
ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION = (
    "Strategy assignment is research context; contribution is shown only when "
    "current signals, reviews, orders, and fills have traceable references."
)

_PNL_PENDING_LIMITATION = (
    "P/L contribution is not calculated until fills are reconciled with position "
    "and valuation history."
)


def default_account_strategy_assignment(config: Any) -> AccountStrategyAssignment:
    strategy_id = str(getattr(config, "strategy", "dual_ma") or "dual_ma")
    return AccountStrategyAssignment(
        strategy_id=strategy_id,
        strategy_name=strategy_id,
        status="research_only",
        scope="account",
        auto_trade_enabled=False,
        attribution_status="not_started",
        limitations=[ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION],
    )


def account_strategy_assignment_from_payload(
    payload: dict[str, Any],
    *,
    fallback_config: Any,
) -> AccountStrategyAssignment:
    fallback = default_account_strategy_assignment(fallback_config).model_dump()
    merged = {**fallback, **payload}
    merged["auto_trade_enabled"] = False
    merged.setdefault("limitations", [ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION])
    if not merged.get("limitations"):
        merged["limitations"] = [ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION]
    return AccountStrategyAssignment(**merged)


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


def _all_pages(reader: Any, **filters: Any) -> list[dict[str, Any]]:
    if not callable(reader):
        return []
    rows: list[dict[str, Any]] = []
    page_size = 500
    while True:
        page = list(reader(limit=page_size, offset=len(rows), **filters) or [])
        rows.extend(page)
        if len(page) < page_size:
            return rows


def linked_strategy_evidence(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> dict[str, Any]:
    """Resolve persisted strategy evidence without simulation contamination."""
    journal_reader = getattr(db, "list_signal_journal_sync", None)
    order_reader = getattr(db, "list_orders_sync", None)
    fill_reader = getattr(db, "list_fills_sync", None)

    filters: dict[str, Any] = {"strategy_id": assignment.strategy_id}
    if assignment.scope == "symbol" and assignment.symbol:
        filters["symbol"] = assignment.symbol
    if assignment.scope == "asset_class" and assignment.asset_class:
        filters["asset_class"] = assignment.asset_class
    journal_entries = _all_pages(journal_reader, **filters)
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

    all_orders = _all_pages(
        order_reader,
        source_signal_ids=sorted(signal_ids),
        risk_decision_ids=sorted(risk_decision_ids),
        intent_ids=sorted(intent_ids),
    )
    known_order_ids = {str(order["order_id"]) for order in all_orders}
    fills = _all_pages(
        fill_reader,
        source_signal_ids=sorted(signal_ids),
        order_ids=sorted(known_order_ids),
        strategy_id=assignment.strategy_id,
    )
    fill_order_ids = {
        str(fill["order_id"]) for fill in fills if fill.get("order_id") is not None
    }
    if missing_order_ids := fill_order_ids - known_order_ids:
        all_orders.extend(_all_pages(order_reader, order_ids=sorted(missing_order_ids)))
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


def build_attribution_summary(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyAttributionSummary:
    """Project persisted signal, risk, order, and fill linkage for one strategy."""
    evidence = linked_strategy_evidence(db, assignment)
    strategy_entries = evidence["strategy_entries"]
    signal_ids = evidence["signal_ids"]
    risk_decisions = evidence["risk_decisions"]
    linked_orders = evidence["linked_orders"]
    linked_fills = evidence["linked_fills"]
    unattributed_fill_count = evidence["unattributed_fill_count"]

    total_fees = sum(
        float(fill.get("commission") or 0.0) + float(fill.get("slippage") or 0.0)
        for fill in linked_fills
    )
    action_refs = sorted(
        {
            f"action:{entry['action_task']['id']}"
            for entry in strategy_entries
            if entry.get("action_task") and entry["action_task"].get("id") is not None
        }
    )
    risk_refs = sorted(
        {
            f"risk:{risk['decision_id']}"
            for risk in risk_decisions
            if risk and risk.get("decision_id")
        }
    )
    review_refs = sorted(
        {
            f"review:{entry['review']['signal_id']}"
            for entry in strategy_entries
            if entry.get("review") and entry["review"].get("signal_id") is not None
        }
    )
    if linked_fills:
        status = "evidence_linked_pnl_pending"
        limitations = [_PNL_PENDING_LIMITATION]
    elif linked_orders:
        status = "orders_linked_no_fills"
        limitations = ["Orders are linked, but no fills are available for attribution."]
    elif strategy_entries:
        status = "signal_chain_pending"
        limitations = ["Signals exist, but order/fill evidence is not linked yet."]
    else:
        status = "not_started"
        limitations = [ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION]

    evidence_refs = [
        *(f"signal:{signal_id}" for signal_id in sorted(signal_ids)),
        *action_refs,
        *risk_refs,
        *review_refs,
        *(f"order:{order['order_id']}" for order in linked_orders),
        *(f"fill:{fill['fill_id']}" for fill in linked_fills),
    ]
    return AccountStrategyAttributionSummary(
        strategy_id=assignment.strategy_id,
        attribution_status=status,
        signal_count=len(strategy_entries),
        action_count=sum(1 for entry in strategy_entries if entry.get("action_task")),
        risk_decision_count=len(risk_decisions),
        order_count=len(linked_orders),
        fill_count=len(linked_fills),
        unattributed_fill_count=unattributed_fill_count,
        total_fees=round(total_fees, 6),
        attributed_pnl=None,
        realized_pnl=None,
        unrealized_pnl=None,
        evidence_refs=evidence_refs,
        limitations=limitations,
    )


def build_contribution_report(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyContributionReport:
    """Build the canonical persisted, evidence-bound strategy contribution."""
    evidence = linked_strategy_evidence(db, assignment)
    return build_strategy_contribution_report(
        db=db,
        assignment=assignment,
        evidence=evidence,
    )


__all__ = [
    "ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY",
    "ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION",
    "assignment_matches_signal",
    "build_attribution_summary",
    "build_contribution_report",
    "default_account_strategy_assignment",
    "fill_metadata",
    "is_simulation_order",
    "json_dict",
    "linked_strategy_evidence",
    "order_source_signal_id",
    "same_symbol",
    "source_signal_id",
    "account_strategy_assignment_from_payload",
]
