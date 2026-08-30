"""Deterministic portfolio reconstruction from ledger entries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.portfolio_accounting import (
    moving_average_cost_after_buy,
    realized_pnl_after_sell,
)
from server.ledger.models import LedgerEntry
from server.projections.legacy_fund_trade_duplicate_contract import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
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
_PROJECTION_CORRECTION_CONTRACTS = {
    "controlled_projection_correction": (
        "controlled_submission_ledger_correction",
        "karkinos.controlled_submission_ledger_correction_plan.v1",
        "Controlled ledger correction",
    ),
    "manual_trade_projection_correction": (
        "manual_trade_correction",
        "karkinos.manual_trade_correction_plan.v1",
        "Manual trade correction",
    ),
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE: (
        LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
        LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION,
        "Legacy fund trade duplicate correction",
    ),
}


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

    if entry_type in _PROJECTION_CORRECTION_CONTRACTS:
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


def _apply_projection_correction(
    projection: PortfolioProjection,
    entry: LedgerEntry,
    *,
    entry_type: str,
) -> None:
    """Apply a protected, canonical-replay-derived compensating event."""

    expected_source, expected_schema, label = _PROJECTION_CORRECTION_CONTRACTS[
        entry_type
    ]
    if entry.source != expected_source:
        raise ValueError(f"{label} source is invalid")
    payload = entry.correction_payload
    if not isinstance(payload, dict):
        raise ValueError(f"{label} payload is missing")
    if payload.get("schema_version") != expected_schema:
        raise ValueError(f"{label} schema is invalid")
    if payload.get("arbitrary_financial_input_used") is not False:
        raise ValueError(f"{label} derivation is invalid")

    symbol = _require_text(str(payload.get("symbol") or ""), "symbol")
    if (entry.symbol or "") != symbol:
        raise ValueError(f"{label} symbol is invalid")
    before = payload.get("position_before")
    after = payload.get("position_after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise ValueError(f"{label} position state is invalid")

    position = projection.positions.get(symbol)
    if position is None:
        position = ProjectedPosition(symbol=symbol)
    if _projected_position_accounting_state(position) != _normalized_position_state(
        before
    ):
        raise ValueError(f"{label} position evidence drifted for {symbol}")

    cash_delta = _as_decimal(payload.get("cash_delta", "0"))
    if entry_type == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE:
        cash_before = _as_decimal(payload.get("cash_before"))
        cash_after = _as_decimal(payload.get("cash_after"))
        if payload.get("cash_allocation") != "ordered_batch_absolute_cash_state_v1":
            raise ValueError(f"{label} cash allocation is invalid")
        if projection.cash != cash_before:
            raise ValueError(f"{label} cash evidence drifted")
        if cash_after - cash_before != cash_delta:
            raise ValueError(f"{label} cash delta is invalid")
        projection.cash = cash_after
    else:
        projection.cash += cash_delta
    deposits_delta = _as_decimal(payload.get("total_deposits_delta", "0"))
    if deposits_delta != ZERO:
        raise ValueError(f"{label} cannot change deposits")
    projection.total_deposits += deposits_delta

    normalized_after = _normalized_position_state(after)
    previous_quantity = position.quantity
    position.quantity = normalized_after["quantity"]
    position.available_qty = normalized_after["available_qty"]
    position.frozen_qty = normalized_after["frozen_qty"]
    position.avg_cost = normalized_after["avg_cost"]
    position.realized_pnl = normalized_after["realized_pnl"]
    position.commission_paid = normalized_after["commission_paid"]
    position.broker_displayed_cost_basis = normalized_after[
        "broker_displayed_cost_basis"
    ]
    position.broker_displayed_unit_cost = normalized_after["broker_displayed_unit_cost"]
    position.broker_cost_basis_difference = normalized_after[
        "broker_cost_basis_difference"
    ]
    position.broker_cost_basis_method = normalized_after["broker_cost_basis_method"]
    position.broker_cost_basis_status = normalized_after["broker_cost_basis_status"]
    if position.quantity == ZERO and previous_quantity != ZERO:
        position.closed_at = entry.timestamp
    elif position.quantity != ZERO and previous_quantity == ZERO:
        position.closed_at = None
    if position.available_qty != position.quantity - position.frozen_qty:
        raise ValueError(f"{label} availability is invalid")
    projection.positions[symbol] = position


def _projected_position_accounting_state(
    position: ProjectedPosition,
) -> dict[str, Decimal | str | None]:
    return {
        "quantity": position.quantity,
        "available_qty": position.available_qty,
        "frozen_qty": position.frozen_qty,
        "avg_cost": position.avg_cost,
        "realized_pnl": position.realized_pnl,
        "commission_paid": position.commission_paid,
        "broker_displayed_cost_basis": position.broker_displayed_cost_basis,
        "broker_displayed_unit_cost": position.broker_displayed_unit_cost,
        "broker_cost_basis_difference": position.broker_cost_basis_difference,
        "broker_cost_basis_method": position.broker_cost_basis_method,
        "broker_cost_basis_status": position.broker_cost_basis_status,
    }


def _normalized_position_state(
    raw: Mapping[str, Any],
) -> dict[str, Decimal | str | None]:
    decimal_fields = (
        "quantity",
        "available_qty",
        "frozen_qty",
        "avg_cost",
        "realized_pnl",
        "commission_paid",
        "broker_displayed_cost_basis",
        "broker_displayed_unit_cost",
        "broker_cost_basis_difference",
    )
    required = {*decimal_fields, "broker_cost_basis_method", "broker_cost_basis_status"}
    if set(raw) != required:
        raise ValueError("Ledger correction position fields are invalid")
    return {
        **{field: _as_decimal(raw[field]) for field in decimal_fields},
        "broker_cost_basis_method": (
            None
            if raw["broker_cost_basis_method"] is None
            else str(raw["broker_cost_basis_method"])
        ),
        "broker_cost_basis_status": (
            None
            if raw["broker_cost_basis_status"] is None
            else str(raw["broker_cost_basis_status"])
        ),
    }
