"""Deterministic portfolio reconstruction from ledger entries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from server.ledger.models import LedgerEntry
from server.projections.models import ZERO, PortfolioProjection, ProjectedPosition
from server.services.position_presence import is_economically_zero_quantity
from server.valuation.service import value_position

_CASH_DEPOSIT_TYPES = {"cash_deposit", "deposit"}
_CASH_WITHDRAW_TYPES = {"cash_withdraw", "cash_withdrawal", "withdraw"}
_BUY_TYPES = {"trade_buy", "buy", "trade"}
_SELL_TYPES = {"trade_sell", "sell"}
_DIVIDEND_TYPES = {"dividend"}
_CASH_INTEREST_TYPES = {"cash_interest", "interest_income"}
_FEE_TYPES = {"fee"}
_MANUAL_ADJUSTMENT_TYPES = {"manual_adjustment"}
_ADDITIONAL_TRADE_FEE_KEYS = (
    ("subscription_fee",),
    ("redemption_fee",),
    ("stamp_tax", "tax"),
    ("transfer_fee",),
    ("other_fees",),
    ("surcharge_fee",),
    ("exchange_clearing_fee",),
)


def build_portfolio_projection(
    entries: Sequence[LedgerEntry],
    *,
    initial_cash: float | Decimal = 0,
    latest_quotes: Mapping[str, Any] | None = None,
) -> PortfolioProjection:
    """Reconstruct portfolio state from a sequence of ledger entries."""
    projection = PortfolioProjection(cash=_as_decimal(initial_cash))

    for entry in _sorted_entries(entries):
        _apply_ledger_entry(projection, entry)

    _apply_valuations(projection, latest_quotes or {})
    projection.total_equity = projection.cash + sum(
        position.market_value for position in projection.positions.values()
    )
    return projection


def build_portfolio_projection_from_db(
    db,
    *,
    initial_cash: float | Decimal = 0,
    latest_quotes: Mapping[str, Any] | None = None,
    batch_size: int = 500,
) -> PortfolioProjection:
    """Load every ledger entry from the DB and reconstruct the projection."""
    entries: list[LedgerEntry] = []
    offset = 0
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        entries.extend(LedgerEntry.from_row(row) for row in rows)
        if len(rows) < batch_size:
            break
        offset += batch_size
    return build_portfolio_projection(
        entries,
        initial_cash=initial_cash,
        latest_quotes=latest_quotes,
    )


def build_equity_curve_from_entries(
    entries: Sequence[LedgerEntry],
    *,
    initial_cash: float | Decimal = 0,
    latest_quotes: Mapping[str, Any] | None = None,
) -> list[tuple[datetime, Decimal]]:
    projection = PortfolioProjection(cash=_as_decimal(initial_cash))
    points: list[tuple[datetime, Decimal]] = []
    quotes = latest_quotes or {}

    for entry in _sorted_entries(entries):
        _apply_ledger_entry(projection, entry)
        _apply_valuations(projection, quotes)
        total_equity = projection.cash + sum(
            position.market_value for position in projection.positions.values()
        )
        points.append((datetime.fromisoformat(entry.timestamp), total_equity))

    return points


def build_equity_series_from_entries(
    entries: Sequence[LedgerEntry],
    *,
    initial_cash: float | Decimal = 0,
    latest_quotes: Mapping[str, Any] | None = None,
) -> list[dict[str, datetime | Decimal]]:
    projection = PortfolioProjection(cash=_as_decimal(initial_cash))
    points: list[dict[str, datetime | Decimal]] = []
    quotes = latest_quotes or {}
    asset_classes: dict[str, str] = {}

    for entry in _sorted_entries(entries):
        _record_asset_class(asset_classes, entry)
        _apply_ledger_entry(projection, entry)
        _apply_valuations(projection, quotes)

        buckets = _bucket_position_values(projection, asset_classes)
        cash = projection.cash
        total = cash + buckets["stocks"] + buckets["funds"] + buckets["others"]
        points.append(
            {
                "timestamp": datetime.fromisoformat(entry.timestamp),
                "total": total,
                "stocks": buckets["stocks"],
                "funds": buckets["funds"],
                "others": buckets["others"],
                "cash": cash,
            }
        )

    return points


def build_equity_series_from_db(
    db,
    *,
    initial_cash: float | Decimal = 0,
    latest_quotes: Mapping[str, Any] | None = None,
    batch_size: int = 500,
) -> list[dict[str, datetime | Decimal]]:
    entries: list[LedgerEntry] = []
    offset = 0
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        entries.extend(LedgerEntry.from_row(row) for row in rows)
        if len(rows) < batch_size:
            break
        offset += batch_size

    return build_equity_series_from_entries(
        entries,
        initial_cash=initial_cash,
        latest_quotes=latest_quotes,
    )


def build_equity_curve_from_db(
    db,
    *,
    initial_cash: float | Decimal = 0,
    latest_quotes: Mapping[str, Any] | None = None,
    batch_size: int = 500,
) -> list[tuple[datetime, Decimal]]:
    entries: list[LedgerEntry] = []
    offset = 0
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        entries.extend(LedgerEntry.from_row(row) for row in rows)
        if len(rows) < batch_size:
            break
        offset += batch_size

    return build_equity_curve_from_entries(
        entries,
        initial_cash=initial_cash,
        latest_quotes=latest_quotes,
    )


def _record_asset_class(asset_classes: dict[str, str], entry: LedgerEntry) -> None:
    symbol = (entry.symbol or "").strip()
    if not symbol:
        return
    asset_classes[symbol] = (entry.asset_class or "stock").strip().lower()


def _bucket_position_values(
    projection: PortfolioProjection,
    asset_classes: Mapping[str, str],
) -> dict[str, Decimal]:
    buckets = {
        "stocks": ZERO,
        "funds": ZERO,
        "others": ZERO,
    }
    for symbol, position in projection.positions.items():
        if is_economically_zero_quantity(position.quantity):
            continue
        bucket = _equity_bucket(asset_classes.get(symbol))
        if bucket is not None:
            buckets[bucket] += position.market_value
    return buckets


def _equity_bucket(asset_class: str | None) -> str | None:
    normalized = (asset_class or "stock").strip().lower()
    if normalized == "stock":
        return "stocks"
    if normalized in {"fund", "etf"}:
        return "funds"
    if normalized in {"bond", "gold"}:
        return "others"
    return None


def _sorted_entries(entries: Sequence[LedgerEntry]) -> list[LedgerEntry]:
    return sorted(entries, key=lambda entry: (entry.timestamp, entry.id or 0))


def _apply_ledger_entry(projection: PortfolioProjection, entry: LedgerEntry) -> None:
    entry_type = (entry.entry_type or "").strip().lower()
    if entry_type in _CASH_DEPOSIT_TYPES:
        amount = _require_decimal(entry.amount, "amount")
        projection.cash += amount
        projection.total_deposits += amount
        return

    if entry_type in _CASH_WITHDRAW_TYPES:
        amount = _require_decimal(entry.amount, "amount")
        projection.cash -= amount
        projection.total_deposits -= amount
        return

    if entry_type in _BUY_TYPES or entry_type in _SELL_TYPES:
        _apply_trade_entry(projection, entry)
        return

    if entry_type in _DIVIDEND_TYPES or entry_type in _CASH_INTEREST_TYPES:
        _apply_cash_income(projection, entry)
        return

    if entry_type in _FEE_TYPES:
        _apply_cash_expense(projection, entry)
        return

    if entry_type in _MANUAL_ADJUSTMENT_TYPES:
        _apply_manual_adjustment(projection, entry)
        return

    raise ValueError(f"Unsupported ledger entry_type: {entry.entry_type!r}")


def _apply_trade_entry(projection: PortfolioProjection, entry: LedgerEntry) -> None:
    symbol = _require_text(entry.symbol, "symbol")
    quantity = _require_decimal(entry.quantity, "quantity")
    price = _require_decimal(entry.price, "price")
    commission = _trade_total_fee(entry)
    side = _trade_side(entry)

    position = projection.positions.get(symbol)
    if position is None:
        position = ProjectedPosition(symbol=symbol)
        projection.positions[symbol] = position

    if side == "buy":
        _apply_buy(projection, position, quantity, price, commission)
        return

    if side == "sell":
        _apply_sell(projection, position, quantity, price, commission)
        return

    raise ValueError(f"Unknown trade direction for entry_type={entry.entry_type!r}")


def _apply_buy(
    projection: PortfolioProjection,
    position: ProjectedPosition,
    quantity: Decimal,
    price: Decimal,
    commission: Decimal,
) -> None:
    added_cost = quantity * price + commission
    projection.cash -= added_cost
    if position.quantity == ZERO:
        position.avg_cost = added_cost / quantity
    else:
        previous_cost = position.quantity * position.avg_cost
        total_quantity = position.quantity + quantity
        position.avg_cost = (previous_cost + added_cost) / total_quantity

    position.broker_displayed_cost_basis += added_cost
    position.quantity += quantity
    position.commission_paid += commission
    _sync_broker_cost_basis(position)
    position.sync_available_qty()


def _apply_sell(
    projection: PortfolioProjection,
    position: ProjectedPosition,
    quantity: Decimal,
    price: Decimal,
    commission: Decimal,
) -> None:
    if quantity > position.quantity:
        raise ValueError(
            f"Sell quantity {quantity} exceeds position {position.quantity} for {position.symbol}"
        )

    net_proceeds = quantity * price - commission
    projection.cash += net_proceeds
    position.realized_pnl += net_proceeds - position.avg_cost * quantity
    position.commission_paid += commission
    position.broker_displayed_cost_basis -= net_proceeds
    position.quantity -= quantity
    if position.quantity == ZERO:
        position.avg_cost = ZERO
        position.broker_displayed_cost_basis = ZERO
    _sync_broker_cost_basis(position)
    position.sync_available_qty()


def _sync_broker_cost_basis(position: ProjectedPosition) -> None:
    if position.quantity == ZERO:
        position.broker_displayed_unit_cost = ZERO
        position.broker_cost_basis_difference = ZERO
        position.broker_cost_basis_method = None
        position.broker_cost_basis_status = None
        return

    position.broker_displayed_unit_cost = (
        position.broker_displayed_cost_basis / position.quantity
    )
    position.broker_cost_basis_difference = position.broker_displayed_cost_basis - (
        position.quantity * position.avg_cost
    )
    position.broker_cost_basis_method = "broker_remaining_cost"
    position.broker_cost_basis_status = "projected_from_ledger"


def _apply_cash_income(projection: PortfolioProjection, entry: LedgerEntry) -> None:
    amount = _require_decimal(entry.amount, "amount")
    projection.cash += amount

    symbol = (entry.symbol or "").strip()
    if symbol:
        position = projection.positions.get(symbol)
        if position is None:
            position = ProjectedPosition(symbol=symbol)
            projection.positions[symbol] = position
        position.realized_pnl += amount


def _apply_cash_expense(projection: PortfolioProjection, entry: LedgerEntry) -> None:
    amount = _require_decimal(entry.amount, "amount")
    projection.cash -= amount

    symbol = (entry.symbol or "").strip()
    if symbol:
        position = projection.positions.get(symbol)
        if position is None:
            position = ProjectedPosition(symbol=symbol)
            projection.positions[symbol] = position
        position.realized_pnl -= amount


def _apply_manual_adjustment(
    projection: PortfolioProjection, entry: LedgerEntry
) -> None:
    amount = entry.amount
    if amount is not None:
        projection.cash += _as_decimal(amount)

    symbol = (entry.symbol or "").strip()
    quantity = entry.quantity
    if not symbol or quantity is None:
        return

    position = projection.positions.get(symbol)
    if position is None:
        position = ProjectedPosition(symbol=symbol)
        projection.positions[symbol] = position

    delta = _as_decimal(quantity)
    if delta < ZERO and abs(delta) > position.quantity:
        raise ValueError(
            f"Manual adjustment quantity {delta} exceeds position {position.quantity} for {symbol}"
        )

    previous_quantity = position.quantity
    price = entry.price
    if delta > ZERO:
        if price is not None and previous_quantity > ZERO:
            previous_cost = previous_quantity * position.avg_cost
            added_cost = delta * _as_decimal(price)
            position.avg_cost = (previous_cost + added_cost) / (
                previous_quantity + delta
            )
        elif price is not None and previous_quantity == ZERO:
            position.avg_cost = _as_decimal(price)
    position.quantity = previous_quantity + delta
    if position.quantity == ZERO:
        position.avg_cost = ZERO
    position.sync_available_qty()


def _apply_valuations(
    projection: PortfolioProjection, latest_quotes: Mapping[str, Any]
) -> None:
    for symbol, position in projection.positions.items():
        market_price = _quote_price(symbol, position.avg_cost, latest_quotes)
        valuation = value_position(position.quantity, position.avg_cost, market_price)
        position.market_value = valuation.market_value
        position.unrealized_pnl = valuation.unrealized_pnl


def _quote_price(
    symbol: str, fallback: Decimal, latest_quotes: Mapping[str, Any]
) -> Decimal:
    quote = latest_quotes.get(symbol)
    if isinstance(quote, Mapping):
        price = quote.get("price")
    else:
        price = quote

    if price in {None, "", 0, 0.0}:
        return fallback
    return _as_decimal(price)


def _trade_side(entry: LedgerEntry) -> str:
    direction = (entry.direction or "").strip().lower()
    if direction in {"buy", "sell"}:
        return direction

    entry_type = (entry.entry_type or "").strip().lower()
    if entry_type.endswith("_buy"):
        return "buy"
    if entry_type.endswith("_sell"):
        return "sell"
    if entry_type == "buy":
        return "buy"
    if entry_type == "sell":
        return "sell"
    return ""


def _trade_total_fee(entry: LedgerEntry) -> Decimal:
    breakdown = entry.fee_breakdown or {}
    total_fee = _breakdown_decimal(breakdown, "total_fee")
    if total_fee is not None:
        return abs(total_fee)

    commission = _breakdown_decimal(breakdown, "commission")
    total = abs(commission if commission is not None else _as_decimal(entry.commission))
    if not breakdown:
        return total

    for aliases in _ADDITIONAL_TRADE_FEE_KEYS:
        value = _breakdown_decimal(breakdown, *aliases)
        if value is not None:
            total += abs(value)
    return total


def _breakdown_decimal(breakdown: Mapping[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        raw = breakdown.get(key)
        if raw in {None, ""}:
            continue
        return _as_decimal(raw)
    return None


def _require_decimal(value: float | Decimal | None, field_name: str) -> Decimal:
    if value is None:
        raise ValueError(f"Missing {field_name} on ledger entry")
    return _as_decimal(value)


def _require_text(value: str | None, field_name: str) -> str:
    if not value:
        raise ValueError(f"Missing {field_name} on ledger entry")
    return value


def _as_decimal(value: float | Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
