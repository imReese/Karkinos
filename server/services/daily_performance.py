"""Canonical deterministic daily performance attribution primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class DailyTradeLot:
    timestamp: datetime
    quantity: float
    price: float
    total_cost: float


@dataclass(frozen=True, slots=True)
class PositionDailyContext:
    quantity: float
    overnight_quantity: float
    previous_close: float | None
    lots: tuple[DailyTradeLot, ...]
    baseline_value: float | None
    baseline_price: float | None
    status: str
    source: str


@dataclass(frozen=True, slots=True)
class PositionDailyMark:
    active_quantity: float
    baseline_value: float | None
    current_value: float | None
    today_change: float | None
    today_change_pct: float | None
    status: str
    source: str


@dataclass(frozen=True, slots=True)
class AccountDailyPerformance:
    starting_equity: float | None
    ending_equity: float
    equity_delta: float
    external_flow: float
    market_move: float
    status: str


def _coerce_lot(raw: DailyTradeLot | Mapping[str, Any]) -> DailyTradeLot:
    if isinstance(raw, DailyTradeLot):
        return raw
    timestamp = raw.get("timestamp")
    if not isinstance(timestamp, datetime):
        raise ValueError("daily trade lot timestamp must be a datetime")
    return DailyTradeLot(
        timestamp=timestamp,
        quantity=float(raw["quantity"]),
        price=float(raw["price"]),
        total_cost=float(raw["total_cost"]),
    )


def _matched_lots(
    quantity: float,
    lots: Iterable[DailyTradeLot | Mapping[str, Any]],
) -> tuple[DailyTradeLot, ...]:
    remaining = max(float(quantity), 0.0)
    matched: list[DailyTradeLot] = []
    for raw in sorted(
        (_coerce_lot(item) for item in lots), key=lambda item: item.timestamp
    ):
        if remaining <= 0:
            break
        lot_quantity = max(float(raw.quantity), 0.0)
        if lot_quantity <= 0:
            continue
        matched_quantity = min(lot_quantity, remaining)
        ratio = matched_quantity / lot_quantity
        matched.append(
            DailyTradeLot(
                timestamp=raw.timestamp,
                quantity=matched_quantity,
                price=raw.price,
                total_cost=raw.total_cost * ratio,
            )
        )
        remaining -= matched_quantity
    return tuple(matched)


def build_position_daily_context(
    *,
    quantity: float,
    previous_close: float | None,
    same_day_buy_lots: Iterable[DailyTradeLot | Mapping[str, Any]],
    has_same_day_sell: bool = False,
) -> PositionDailyContext:
    """Freeze the only supported baseline for one current position."""
    position_quantity = max(float(quantity), 0.0)
    lots = _matched_lots(position_quantity, same_day_buy_lots)
    same_day_quantity = sum(lot.quantity for lot in lots)
    overnight_quantity = max(position_quantity - same_day_quantity, 0.0)

    if has_same_day_sell:
        return PositionDailyContext(
            quantity=position_quantity,
            overnight_quantity=overnight_quantity,
            previous_close=previous_close,
            lots=lots,
            baseline_value=None,
            baseline_price=None,
            status="unavailable",
            source="same_day_sell_requires_daily_attribution",
        )
    if overnight_quantity > 0 and previous_close in {None, 0}:
        return PositionDailyContext(
            quantity=position_quantity,
            overnight_quantity=overnight_quantity,
            previous_close=previous_close,
            lots=lots,
            baseline_value=None,
            baseline_price=None,
            status="unavailable",
            source="overnight_baseline_unavailable",
        )

    baseline_value = overnight_quantity * float(previous_close or 0.0) + sum(
        lot.total_cost for lot in lots
    )
    if lots and overnight_quantity > 0:
        source = "mixed_previous_close_intraday_trade_cost"
    elif lots:
        source = "intraday_trade_cost"
    else:
        source = "previous_close"
    return PositionDailyContext(
        quantity=position_quantity,
        overnight_quantity=overnight_quantity,
        previous_close=previous_close,
        lots=lots,
        baseline_value=baseline_value,
        baseline_price=(
            baseline_value / position_quantity if position_quantity > 0 else None
        ),
        status="complete",
        source=source,
    )


def mark_position_daily(
    context: PositionDailyContext,
    *,
    price: float | None,
    at: datetime | None = None,
) -> PositionDailyMark:
    """Mark one position at a price and optional intraday cutoff."""
    if context.status != "complete" or price is None:
        return PositionDailyMark(
            active_quantity=context.quantity,
            baseline_value=None,
            current_value=None,
            today_change=None,
            today_change_pct=None,
            status="unavailable",
            source=context.source if price is not None else "latest_price_unavailable",
        )

    active_lots = (
        context.lots
        if at is None
        else tuple(lot for lot in context.lots if lot.timestamp <= at)
    )
    active_quantity = context.overnight_quantity + sum(
        lot.quantity for lot in active_lots
    )
    baseline_value = context.overnight_quantity * float(
        context.previous_close or 0.0
    ) + sum(lot.total_cost for lot in active_lots)
    current_value = active_quantity * float(price)
    today_change = current_value - baseline_value
    return PositionDailyMark(
        active_quantity=active_quantity,
        baseline_value=baseline_value,
        current_value=current_value,
        today_change=today_change,
        today_change_pct=(
            current_value / baseline_value - 1 if baseline_value else None
        ),
        status="complete",
        source=context.source,
    )


def price_at_tick(
    context: PositionDailyContext,
    *,
    tick: datetime,
    quote_points: Iterable[tuple[datetime, float]],
) -> float | None:
    """Choose the newest persisted quote or executed trade price at a tick."""
    observations = list(quote_points)
    observations.extend((lot.timestamp, lot.price) for lot in context.lots)
    baseline_price = context.previous_close
    if baseline_price is None and context.lots:
        baseline_price = context.lots[0].price
    selected = baseline_price
    for timestamp, price in sorted(observations, key=lambda item: item[0]):
        if timestamp > tick:
            break
        selected = float(price)
    return selected


def calculate_account_daily_performance(
    *,
    starting_equity: float | None,
    ending_equity: float,
    external_flow: float,
) -> AccountDailyPerformance:
    """Apply the canonical daily account equation for one valuation interval."""
    if starting_equity is None:
        return AccountDailyPerformance(
            starting_equity=None,
            ending_equity=float(ending_equity),
            equity_delta=0.0,
            external_flow=float(external_flow),
            market_move=0.0,
            status="opening_point",
        )
    equity_delta = float(ending_equity) - float(starting_equity)
    return AccountDailyPerformance(
        starting_equity=float(starting_equity),
        ending_equity=float(ending_equity),
        equity_delta=equity_delta,
        external_flow=float(external_flow),
        market_move=equity_delta - float(external_flow),
        status="complete",
    )
