"""Deterministic portfolio reconstruction from ledger entries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from core.types import InstrumentType
from domain.portfolio_accounting import (
    moving_average_cost_after_buy,
    realized_pnl_after_sell,
)
from server.ledger.models import LedgerEntry
from server.projections.ledger_projection_correction import (
    apply_projection_correction as _apply_projection_correction,
)
from server.projections.ledger_projection_correction import (
    is_projection_correction_entry_type as _is_projection_correction_entry_type,
)
from server.projections.models import ZERO, PortfolioProjection, ProjectedPosition
from server.projections.portfolio_projection_values import (
    apply_valuations as _apply_valuations,
)
from server.projections.portfolio_projection_values import as_decimal as _as_decimal
from server.projections.portfolio_projection_values import (
    require_decimal as _require_decimal,
)
from server.projections.portfolio_projection_values import require_text as _require_text
from server.projections.portfolio_projection_values import trade_side as _trade_side
from server.projections.portfolio_projection_values import (
    trade_total_fee as _trade_total_fee,
)
from server.services.position_presence import is_economically_zero_quantity

_CASH_DEPOSIT_TYPES = {"cash_deposit", "deposit"}
_CASH_WITHDRAW_TYPES = {"cash_withdraw", "cash_withdrawal", "withdraw"}
_BUY_TYPES = {"trade_buy", "buy", "trade"}
_SELL_TYPES = {"trade_sell", "sell"}
_DIVIDEND_TYPES = {"dividend"}
_CASH_INTEREST_TYPES = {"cash_interest", "interest_income"}
_FEE_TYPES = {"fee"}
_MANUAL_ADJUSTMENT_TYPES = {"manual_adjustment"}


@dataclass(frozen=True, slots=True)
class PortfolioReplayValuation:
    """Strict point-in-time valuation from an incrementally replayed ledger."""

    cash: Decimal
    total: Decimal | None
    stocks: Decimal | None
    funds: Decimal | None
    others: Decimal | None
    unrealized_pnl: Decimal | None
    missing_price_symbols: tuple[str, ...]


class PortfolioReplayAccumulator:
    """Apply each canonical ledger entry once while emitting daily valuations."""

    def __init__(self, *, initial_cash: float | Decimal = 0) -> None:
        self._projection = PortfolioProjection(cash=_as_decimal(initial_cash))
        self._asset_classes: dict[str, str] = {}
        self._applied_entry_count = 0

    @property
    def applied_entry_count(self) -> int:
        return self._applied_entry_count

    @property
    def active_symbols(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                symbol
                for symbol, position in self._projection.positions.items()
                if not is_economically_zero_quantity(position.quantity)
            )
        )

    def apply(self, entry: LedgerEntry) -> None:
        symbol = str(entry.symbol or "").strip()
        if symbol:
            instrument_type = InstrumentType.from_persisted(entry.asset_class)
            self._asset_classes[symbol] = instrument_type.value
        _apply_ledger_entry(self._projection, entry)
        self._applied_entry_count += 1

    def value(
        self,
        latest_quotes: Mapping[str, Any],
    ) -> PortfolioReplayValuation:
        _apply_valuations(self._projection, latest_quotes)
        missing = tuple(self._projection.missing_price_symbols)
        buckets = _bucket_position_values_with_availability(
            self._projection,
            self._asset_classes,
        )
        if missing:
            self._projection.total_equity = None
            return PortfolioReplayValuation(
                cash=self._projection.cash,
                total=None,
                stocks=buckets["stocks"],
                funds=buckets["funds"],
                others=buckets["others"],
                unrealized_pnl=None,
                missing_price_symbols=missing,
            )

        total = (
            self._projection.cash
            + buckets["stocks"]
            + buckets["funds"]
            + buckets["others"]
        )
        self._projection.total_equity = total
        unrealized_pnl = sum(
            (
                position.unrealized_pnl
                for position in self._projection.positions.values()
                if not is_economically_zero_quantity(position.quantity)
            ),
            ZERO,
        )
        return PortfolioReplayValuation(
            cash=self._projection.cash,
            total=total,
            stocks=buckets["stocks"],
            funds=buckets["funds"],
            others=buckets["others"],
            unrealized_pnl=unrealized_pnl,
            missing_price_symbols=(),
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
    projection.total_equity = (
        None
        if projection.missing_price_symbols
        else projection.cash
        + sum(position.market_value for position in projection.positions.values())
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
        if projection.missing_price_symbols:
            continue
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
) -> list[dict[str, Any]]:
    projection = PortfolioProjection(cash=_as_decimal(initial_cash))
    points: list[dict[str, Any]] = []
    quotes = latest_quotes or {}
    asset_classes: dict[str, str] = {}

    for entry in _sorted_entries(entries):
        _record_asset_class(asset_classes, entry)
        _apply_ledger_entry(projection, entry)
        _apply_valuations(projection, quotes)

        cash = projection.cash
        missing_price_symbols = list(projection.missing_price_symbols)
        buckets = _bucket_position_values_with_availability(
            projection,
            asset_classes,
        )
        if missing_price_symbols:
            total = None
        else:
            total = cash + buckets["stocks"] + buckets["funds"] + buckets["others"]
        points.append(
            {
                "timestamp": datetime.fromisoformat(entry.timestamp),
                "total": total,
                "stocks": buckets["stocks"],
                "funds": buckets["funds"],
                "others": buckets["others"],
                "cash": cash,
                "missing_price_symbols": missing_price_symbols,
            }
        )

    return points


def build_equity_series_from_db(
    db,
    *,
    initial_cash: float | Decimal = 0,
    latest_quotes: Mapping[str, Any] | None = None,
    batch_size: int = 500,
) -> list[dict[str, Any]]:
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


def _bucket_position_values_with_availability(
    projection: PortfolioProjection,
    asset_classes: Mapping[str, str],
) -> dict[str, Decimal | None]:
    buckets: dict[str, Decimal | None] = _bucket_position_values(
        projection,
        asset_classes,
    )
    for symbol in projection.missing_price_symbols:
        bucket = _equity_bucket(asset_classes.get(symbol))
        if bucket is None:
            return {"stocks": None, "funds": None, "others": None}
        buckets[bucket] = None
    return buckets


def _equity_bucket(asset_class: str | None) -> str | None:
    normalized = (asset_class or "stock").strip().lower()
    if normalized == "stock":
        return "stocks"
    if normalized in {"fund", "etf", "open_end_fund"}:
        return "funds"
    if normalized in {"bond", "gold"}:
        return "others"
    return None


def _sorted_entries(entries: Sequence[LedgerEntry]) -> list[LedgerEntry]:
    return sorted(entries, key=_entry_sort_key)


def _entry_sort_key(entry: LedgerEntry) -> tuple[datetime, int]:
    text = str(entry.timestamp or "").strip().replace("Z", "+00:00")
    if not text:
        raise ValueError("Ledger entry timestamp is missing")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("Ledger entry timestamp is invalid") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), entry.id or 0


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

    if _is_projection_correction_entry_type(entry_type):
        _apply_projection_correction(projection, entry, entry_type=entry_type)
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
        _apply_sell(
            projection,
            position,
            quantity,
            price,
            commission,
            closed_at=entry.timestamp,
        )
        return

    raise ValueError(f"Unknown trade direction for entry_type={entry.entry_type!r}")


def _apply_buy(
    projection: PortfolioProjection,
    position: ProjectedPosition,
    quantity: Decimal,
    price: Decimal,
    commission: Decimal,
) -> None:
    if position.quantity == ZERO:
        position.closed_at = None
    added_cost = quantity * price + commission
    projection.cash -= added_cost
    position.avg_cost = moving_average_cost_after_buy(
        current_quantity=position.quantity,
        current_average_cost=position.avg_cost,
        fill_quantity=quantity,
        fill_price=price,
        total_fee=commission,
    )

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
    *,
    closed_at: str,
) -> None:
    if quantity > position.quantity:
        raise ValueError(
            f"Sell quantity {quantity} exceeds position {position.quantity} for {position.symbol}"
        )

    net_proceeds = quantity * price - commission
    projection.cash += net_proceeds
    position.realized_pnl += realized_pnl_after_sell(
        average_cost=position.avg_cost,
        fill_quantity=quantity,
        fill_price=price,
        total_fee=commission,
    )
    position.commission_paid += commission
    position.broker_displayed_cost_basis -= net_proceeds
    position.quantity -= quantity
    if position.quantity == ZERO:
        position.avg_cost = ZERO
        position.broker_displayed_cost_basis = ZERO
        position.closed_at = closed_at
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
        if previous_quantity != ZERO:
            position.closed_at = entry.timestamp
    elif previous_quantity == ZERO:
        position.closed_at = None
    position.sync_available_qty()
