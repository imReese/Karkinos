"""Batch pre-trade risk runner for decision action tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from core.events import OrderIntentEvent, RiskDecisionEvent
from core.types import AssetClass, OrderSide, Symbol
from risk.pre_trade import (
    ContextProvider,
    PreTradePolicy,
    preview_pre_trade_risk,
)

_BOARD_LOT_ASSET_CLASSES = {"stock", "etf"}
_CHECKED_RISK_STATUSES = {"passed", "blocked"}
_DEFAULT_MIN_CASH_BUFFER_RATIO = Decimal("0.03")
_DEFAULT_MAX_SINGLE_SYMBOL_WEIGHT = Decimal("0.35")


def run_pre_trade_risk_batch(
    *,
    db: Any,
    context_provider: ContextProvider,
    policy: PreTradePolicy | None = None,
    config: Any = None,
    statuses: list[str] | None = None,
    limit: int = 50,
    tasks: list[dict[str, Any]] | None = None,
    evidence_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run mandatory pre-trade risk checks for unchecked action tasks.

    The runner only persists risk decisions. It does not create broker orders,
    manual orders, fills, or ledger entries.
    """
    selected_tasks = (
        list(tasks)
        if tasks is not None
        else list(
            db.get_action_tasks_sync(
                statuses=statuses or ["pending", "deferred"],
                limit=limit,
                offset=0,
            )
        )
    )
    context = context_provider.snapshot()
    resolved_policy = policy or default_pre_trade_batch_policy(context, config=config)
    bound_evidence = dict(evidence_binding or {})
    results: list[dict[str, Any]] = []
    skipped_count = 0

    for task in selected_tasks:
        if str(task.get("risk_gate_status") or "not_checked") in _CHECKED_RISK_STATUSES:
            skipped_count += 1
            results.append(_skipped_result(task, "already_checked"))
            continue

        intent_result = _intent_from_action_task(task, context)
        if intent_result["status"] != "ready":
            skipped_count += 1
            results.append(
                {
                    "action_id": task.get("id"),
                    "symbol": task.get("symbol"),
                    "status": "skipped",
                    "passed": None,
                    "decision_id": None,
                    "reasons": [intent_result["reason"]],
                }
            )
            continue

        intent = intent_result["intent"]
        preview = preview_pre_trade_risk(
            intent=intent,
            context=context,
            policy=resolved_policy,
        )
        decision_id = f"RISK-BATCH-{uuid.uuid4().hex[:10]}"
        decision = RiskDecisionEvent(
            timestamp=intent.timestamp,
            decision_id=decision_id,
            intent_id=intent.intent_id,
            passed=bool(preview["passed"]),
            symbol=intent.symbol,
            side=intent.side,
            reasons=list(preview["reasons"]),
            resulting_order_id=None,
            severity=str(preview["severity"]),
            metadata={
                **dict(preview["metadata"]),
                "batch_runner": "decision_pre_trade_batch",
                "does_not_create_order": True,
                "default_execution_mode": "manual_confirmation",
                "evidence_binding": bound_evidence,
            },
        )
        db.save_risk_decision_sync(intent=intent, decision=decision)
        results.append(
            {
                "action_id": task.get("id"),
                "symbol": task.get("symbol"),
                "status": "passed" if decision.passed else "blocked",
                "passed": decision.passed,
                "decision_id": decision.decision_id,
                "reasons": decision.reasons,
            }
        )

    passed_count = sum(1 for item in results if item.get("status") == "passed")
    blocked_count = sum(1 for item in results if item.get("status") == "blocked")
    processed_count = passed_count + blocked_count
    return {
        "schema_version": "karkinos.pre_trade_risk_batch.v1",
        "status": "completed",
        "processed_count": processed_count,
        "passed_count": passed_count,
        "blocked_count": blocked_count,
        "skipped_count": skipped_count,
        "candidate_count": len(selected_tasks),
        "does_not_create_order": True,
        "does_not_submit_broker_order": True,
        "does_not_write_ledger": True,
        "risk_decision_writes_performed": processed_count > 0,
        "default_execution_mode": "manual_confirmation",
        "evidence_binding": bound_evidence,
        "results": results,
    }


def default_pre_trade_batch_policy(
    context,
    *,
    config: Any = None,
    min_cash_buffer_ratio: Decimal | float | str | None = None,
    max_single_symbol_weight: Decimal | float | str | None = None,
) -> PreTradePolicy:
    """Build the default manual-confirmation policy used by batch risk checks."""
    cash_buffer_ratio = _bounded_ratio(
        _first_value(
            min_cash_buffer_ratio,
            getattr(config, "trading_plan_min_cash_buffer_ratio", None),
            getattr(config, "min_cash_buffer_ratio", None),
        ),
        fallback=_DEFAULT_MIN_CASH_BUFFER_RATIO,
    )
    position_weight = _bounded_ratio(
        _first_value(
            max_single_symbol_weight,
            getattr(config, "max_single_symbol_weight", None),
        ),
        fallback=_DEFAULT_MAX_SINGLE_SYMBOL_WEIGHT,
    )
    return PreTradePolicy(
        execution_mode="manual",
        min_cash_reserve=context.total_equity * cash_buffer_ratio,
        max_position_weight=position_weight,
    )


def _intent_from_action_task(
    task: dict[str, Any],
    context,
) -> dict[str, Any]:
    side = _order_side(task)
    if side is None:
        return {"status": "skipped", "reason": "action_not_orderable"}
    source_signal_id = task.get("source_signal_id")
    if source_signal_id is None:
        return {"status": "skipped", "reason": "missing_source_signal_id"}
    price = _decimal(task.get("price"))
    if price <= 0:
        return {"status": "skipped", "reason": "missing_reference_price"}
    target_weight = _decimal(task.get("target_weight"))
    quantity = _estimated_quantity(
        task,
        side=side,
        price=price,
        target_weight=target_weight,
        context=context,
    )
    if quantity <= 0:
        return {"status": "skipped", "reason": "estimated_quantity_not_positive"}

    timestamp = _timestamp(task.get("timestamp"))
    asset_class = _asset_class(task.get("asset_class"))
    intent = OrderIntentEvent(
        timestamp=timestamp,
        intent_id=f"ACTION-{task.get('id')}-BATCH-RISK",
        strategy_id=str(task.get("strategy_id") or "decision_action"),
        symbol=Symbol(str(task.get("symbol"))),
        side=side,
        target_weight=target_weight,
        quantity=quantity,
        reference_price=price,
        asset_class=asset_class,
        source_signal_id=str(source_signal_id),
        reason="batch pre-trade risk gate",
        metadata={
            "action_id": task.get("id"),
            "source": "decision_pre_trade_batch",
            "raw_target_weight": task.get(
                "raw_target_weight",
                task.get("target_weight"),
            ),
            "effective_target_weight": task.get("target_weight"),
            "portfolio_allocation": dict(task.get("allocation_evidence") or {}),
            "does_not_create_order": True,
        },
    )
    return {"status": "ready", "intent": intent}


def _estimated_quantity(
    task: dict[str, Any],
    *,
    side: OrderSide,
    price: Decimal,
    target_weight: Decimal,
    context,
) -> Decimal:
    if "allocation_quantity" in task:
        return _decimal(task.get("allocation_quantity"))
    explicit_quantity = _decimal(
        task.get("quantity") or task.get("estimated_quantity") or task.get("shares")
    )
    if explicit_quantity > 0:
        return explicit_quantity

    if side == OrderSide.SELL:
        position = context.positions.get(Symbol(str(task.get("symbol"))))
        return _position_quantity(position)

    position = context.positions.get(Symbol(str(task.get("symbol"))))
    current_quantity = _position_total_quantity(position)
    target_notional = context.total_equity * target_weight
    if target_notional <= 0:
        return Decimal("0")
    raw_quantity = target_notional / price
    if str(task.get("asset_class") or "").lower() in _BOARD_LOT_ASSET_CLASSES:
        lots = (raw_quantity / Decimal("100")).to_integral_value(rounding=ROUND_FLOOR)
        target_quantity = lots * Decimal("100")
    else:
        target_quantity = raw_quantity.quantize(
            Decimal("0.000001"),
            rounding=ROUND_FLOOR,
        )
    return max(target_quantity - current_quantity, Decimal("0"))


def _order_side(task: dict[str, Any]) -> OrderSide | None:
    direction = str(task.get("direction") or "").strip().lower()
    if direction == "buy":
        return OrderSide.BUY
    if direction == "sell":
        return OrderSide.SELL
    if direction == "rebalance":
        return (
            OrderSide.BUY if _decimal(task.get("target_weight")) > 0 else OrderSide.SELL
        )
    return None


def _asset_class(value: Any) -> AssetClass | None:
    normalized = str(value or "").strip().lower()
    for item in AssetClass:
        if item.value == normalized:
            return item
    return None


def _position_quantity(position: Any) -> Decimal:
    if position is None:
        return Decimal("0")
    for name in (
        "t1_available_quantity",
        "sellable_quantity",
        "available_quantity",
        "quantity",
        "shares",
    ):
        value = getattr(position, name, None)
        quantity = _decimal(value)
        if quantity > 0:
            return quantity
    return Decimal("0")


def _position_total_quantity(position: Any) -> Decimal:
    if position is None:
        return Decimal("0")
    for name in ("quantity", "shares"):
        value = getattr(position, name, None)
        if value is not None:
            return max(_decimal(value), Decimal("0"))
    return Decimal("0")


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _bounded_ratio(
    value: Decimal | float | str | None,
    *,
    fallback: Decimal,
) -> Decimal:
    ratio = _decimal(value)
    if ratio <= 0:
        return fallback
    if ratio > 1:
        return Decimal("1")
    return ratio


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            pass
    return datetime.now()


def _skipped_result(task: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "action_id": task.get("id"),
        "symbol": task.get("symbol"),
        "status": "skipped",
        "passed": task.get("risk_gate_passed"),
        "decision_id": task.get("risk_decision_id"),
        "reasons": [reason],
    }
