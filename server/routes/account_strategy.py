"""Account strategy assignment routes — /api/account-strategy."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter

from server.models import (
    AccountStrategyAssignment,
    AccountStrategyAssignmentUpdate,
    AccountStrategyAttributionSummary,
    AccountStrategyContributionReport,
)

_CONTROL_KEY = "account_strategy_assignment"
_ASSIGNMENT_LIMITATION = (
    "Strategy assignment is research evidence only until signals, reviews, and "
    "fills are attributed."
)
_PNL_PENDING_LIMITATION = (
    "P/L contribution is not calculated until fills are reconciled with position "
    "and valuation history."
)
_CONTRIBUTION_LIMITATION = (
    "Contribution is estimated only from linked strategy fills and latest local "
    "quotes; manual trades and cash flows are excluded."
)


def _default_assignment(config: Any) -> AccountStrategyAssignment:
    strategy_id = str(getattr(config, "strategy", "dual_ma") or "dual_ma")
    return AccountStrategyAssignment(
        strategy_id=strategy_id,
        strategy_name=strategy_id,
        status="research_only",
        scope="account",
        auto_trade_enabled=False,
        attribution_status="not_started",
        limitations=[_ASSIGNMENT_LIMITATION],
    )


def _assignment_from_payload(
    payload: dict[str, Any],
    *,
    fallback_config: Any,
) -> AccountStrategyAssignment:
    fallback = _default_assignment(fallback_config).model_dump()
    merged = {**fallback, **payload}
    merged["auto_trade_enabled"] = False
    merged.setdefault("limitations", [_ASSIGNMENT_LIMITATION])
    if not merged.get("limitations"):
        merged["limitations"] = [_ASSIGNMENT_LIMITATION]
    return AccountStrategyAssignment(**merged)


def _assignment_update_payload(
    update: AccountStrategyAssignmentUpdate,
) -> dict[str, Any]:
    now = datetime.now().isoformat()
    strategy_id = update.strategy_id.strip() or "dual_ma"
    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_id,
        "status": update.status,
        "scope": update.scope,
        "asset_class": update.asset_class,
        "symbol": update.symbol,
        "effective_from": update.effective_from,
        "auto_trade_enabled": False,
        "attribution_status": "assignment_only",
        "attributed_pnl": None,
        "realized_pnl": None,
        "unrealized_pnl": None,
        "total_fees": None,
        "notes": update.notes,
        "updated_at": now,
        "limitations": [_ASSIGNMENT_LIMITATION],
    }


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_signal_id(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _assignment_matches_signal(
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


def _order_source_signal_id(order: dict[str, Any]) -> int | None:
    payload = _json_dict(order.get("payload_json"))
    return _source_signal_id(
        payload.get("source_signal_id")
        or payload.get("signal_id")
        or payload.get("intent", {}).get("source_signal_id")
    )


def _fill_metadata(fill: dict[str, Any]) -> dict[str, Any]:
    return _json_dict(fill.get("metadata_json"))


def _linked_strategy_evidence(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> dict[str, Any]:
    journal_reader = getattr(db, "list_signal_journal_sync", None)
    order_reader = getattr(db, "list_orders_sync", None)
    fill_reader = getattr(db, "list_fills_sync", None)

    journal_entries = (
        journal_reader(limit=500, offset=0) if callable(journal_reader) else []
    )
    strategy_entries = [
        entry
        for entry in journal_entries
        if _assignment_matches_signal(assignment, entry.get("signal") or {})
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
        str(risk["intent_id"]) for risk in risk_decisions if risk and risk.get("intent_id")
    }

    orders = order_reader(limit=1000, offset=0) if callable(order_reader) else []
    linked_orders = []
    for order in orders:
        source_signal_id = _order_source_signal_id(order)
        if (
            source_signal_id in signal_ids
            or order.get("risk_decision_id") in risk_decision_ids
            or order.get("intent_id") in intent_ids
        ):
            linked_orders.append(order)
    linked_order_ids = {str(order["order_id"]) for order in linked_orders}

    fills = fill_reader(limit=1000, offset=0) if callable(fill_reader) else []
    linked_fills = []
    unattributed_fill_count = 0
    for fill in fills:
        metadata = _fill_metadata(fill)
        metadata_signal_id = _source_signal_id(
            metadata.get("source_signal_id") or metadata.get("signal_id")
        )
        metadata_strategy_id = metadata.get("strategy_id")
        order_linked = str(fill.get("order_id")) in linked_order_ids
        if order_linked or metadata_signal_id in signal_ids:
            linked_fills.append(fill)
        elif metadata_strategy_id == assignment.strategy_id:
            linked_fills.append(fill)
            unattributed_fill_count += 1

    return {
        "strategy_entries": strategy_entries,
        "signal_ids": signal_ids,
        "risk_decisions": risk_decisions,
        "linked_orders": linked_orders,
        "linked_fills": linked_fills,
        "unattributed_fill_count": unattributed_fill_count,
    }


def _build_attribution_summary(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyAttributionSummary:
    evidence = _linked_strategy_evidence(db, assignment)
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
        limitations = [_ASSIGNMENT_LIMITATION]

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


def _fill_sort_key(fill: dict[str, Any]) -> tuple[str, str]:
    return (str(fill.get("timestamp") or ""), str(fill.get("fill_id") or ""))


def _build_contribution_report(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyContributionReport:
    evidence = _linked_strategy_evidence(db, assignment)
    linked_fills = sorted(evidence["linked_fills"], key=_fill_sort_key)
    quote_reader = getattr(db, "get_latest_quote_sync", None)
    positions: dict[tuple[str, str], dict[str, float]] = {}
    gross_realized_pnl = 0.0
    total_commission = 0.0
    total_slippage = 0.0
    total_tax = 0.0

    for fill in linked_fills:
        symbol = str(fill.get("symbol") or "")
        asset_class = str(fill.get("asset_class") or "")
        if not symbol:
            continue
        side = str(fill.get("side") or "").lower()
        quantity = float(fill.get("fill_quantity") or 0.0)
        price = float(fill.get("fill_price") or 0.0)
        total_commission += float(fill.get("commission") or 0.0)
        total_slippage += float(fill.get("slippage") or 0.0)
        position = positions.setdefault(
            (symbol, asset_class),
            {"quantity": 0.0, "cost": 0.0},
        )
        if side == "sell":
            current_quantity = position["quantity"]
            average_cost = (
                position["cost"] / current_quantity if current_quantity > 0 else 0.0
            )
            closed_quantity = min(quantity, current_quantity)
            gross_realized_pnl += (price - average_cost) * closed_quantity
            position["quantity"] = max(current_quantity - closed_quantity, 0.0)
            position["cost"] = max(
                position["cost"] - average_cost * closed_quantity,
                0.0,
            )
        else:
            position["quantity"] += quantity
            position["cost"] += price * quantity

    gross_unrealized_pnl = 0.0
    missing_valuation_symbols: list[str] = []
    for (symbol, asset_class), position in positions.items():
        quantity = position["quantity"]
        if quantity <= 0:
            continue
        if not callable(quote_reader):
            missing_valuation_symbols.append(symbol)
            continue
        quote = quote_reader(symbol, asset_class or None)
        if not quote or quote.get("price") is None:
            missing_valuation_symbols.append(symbol)
            continue
        average_cost = position["cost"] / quantity
        gross_unrealized_pnl += (float(quote["price"]) - average_cost) * quantity

    if not linked_fills:
        status = "no_linked_fills"
    elif missing_valuation_symbols:
        status = "valuation_missing"
    else:
        status = "estimated_from_linked_fills"
    net_contribution = (
        gross_realized_pnl
        + gross_unrealized_pnl
        - total_commission
        - total_slippage
    )
    return AccountStrategyContributionReport(
        strategy_id=assignment.strategy_id,
        contribution_status=status,
        linked_fill_count=len(linked_fills),
        gross_realized_pnl=round(gross_realized_pnl, 6),
        gross_unrealized_pnl=round(gross_unrealized_pnl, 6),
        total_commission=round(total_commission, 6),
        total_slippage=round(total_slippage, 6),
        total_tax=round(total_tax, 6),
        net_contribution=round(net_contribution, 6),
        unattributed_account_pnl=None,
        manual_unattributed_pnl=None,
        cash_flow_pnl=None,
        missing_valuation_symbols=sorted(set(missing_valuation_symbols)),
        evidence_refs=[f"fill:{fill['fill_id']}" for fill in linked_fills],
        limitations=[_CONTRIBUTION_LIMITATION],
    )


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/account-strategy", tags=["account-strategy"])

    @r.get("", response_model=AccountStrategyAssignment)
    async def get_account_strategy() -> AccountStrategyAssignment:
        """Read the current research-only account strategy assignment."""
        from server.app import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        payload = reader(_CONTROL_KEY) if callable(reader) else None
        if not isinstance(payload, dict):
            return _default_assignment(state.config)
        return _assignment_from_payload(payload, fallback_config=state.config)

    @r.get("/attribution", response_model=AccountStrategyAttributionSummary)
    async def get_account_strategy_attribution() -> AccountStrategyAttributionSummary:
        """Summarize attribution evidence without mutating account facts."""
        from server.app import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        payload = reader(_CONTROL_KEY) if callable(reader) else None
        assignment = (
            _assignment_from_payload(payload, fallback_config=state.config)
            if isinstance(payload, dict)
            else _default_assignment(state.config)
        )
        return _build_attribution_summary(db, assignment)

    @r.get("/contribution", response_model=AccountStrategyContributionReport)
    async def get_account_strategy_contribution() -> AccountStrategyContributionReport:
        """Estimate strategy contribution from linked fills without mutating facts."""
        from server.app import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        payload = reader(_CONTROL_KEY) if callable(reader) else None
        assignment = (
            _assignment_from_payload(payload, fallback_config=state.config)
            if isinstance(payload, dict)
            else _default_assignment(state.config)
        )
        return _build_contribution_report(db, assignment)

    @r.put("", response_model=AccountStrategyAssignment)
    async def update_account_strategy(
        update: AccountStrategyAssignmentUpdate,
    ) -> AccountStrategyAssignment:
        """Persist a research-only account strategy assignment."""
        from server.app import get_app_state

        state = get_app_state()
        payload = _assignment_update_payload(update)
        db = getattr(state, "db", None)
        writer = getattr(db, "set_runtime_control_sync", None)
        if callable(writer):
            writer(_CONTROL_KEY, payload)
        return _assignment_from_payload(payload, fallback_config=state.config)

    return r
