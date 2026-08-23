"""Canonical portfolio cost-basis calculations.

These pure functions are shared by simulation and persisted-ledger projections so
that a fill has one financial interpretation across product surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

_ADDITIONAL_TRADE_FEE_KEYS = (
    ("subscription_fee",),
    ("redemption_fee",),
    ("stamp_tax", "tax"),
    ("transfer_fee",),
    ("other_fees", "other_fee"),
    ("surcharge_fee",),
    ("exchange_clearing_fee",),
)


def total_trade_fee(
    *,
    commission: Decimal,
    fee_breakdown: Mapping[str, Any] | None = None,
) -> Decimal:
    """Resolve one fill's complete recorded cost without double-counting.

    Structured records own the value when they carry ``total_fee``. Older
    records remain compatible by falling back to commission, while partially
    structured legacy records add each non-commission component once.
    """
    breakdown = fee_breakdown or {}
    explicit_total = _breakdown_decimal(breakdown, "total_fee")
    if explicit_total is not None:
        return abs(explicit_total)

    recorded_commission = _breakdown_decimal(breakdown, "commission")
    total = abs(recorded_commission if recorded_commission is not None else commission)
    for aliases in _ADDITIONAL_TRADE_FEE_KEYS:
        component = _breakdown_decimal(breakdown, *aliases)
        if component is not None:
            total += abs(component)
    return total


def _breakdown_decimal(breakdown: Mapping[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = breakdown.get(key)
        if value in {None, ""}:
            continue
        return Decimal(str(value))
    return None


def moving_average_cost_after_buy(
    *,
    current_quantity: Decimal,
    current_average_cost: Decimal,
    fill_quantity: Decimal,
    fill_price: Decimal,
    total_fee: Decimal,
) -> Decimal:
    """Return the fee-inclusive moving-average unit cost after a buy fill."""
    previous_cost = current_quantity * current_average_cost
    added_cost = fill_quantity * fill_price + total_fee
    return (previous_cost + added_cost) / (current_quantity + fill_quantity)


def realized_pnl_after_sell(
    *,
    average_cost: Decimal,
    fill_quantity: Decimal,
    fill_price: Decimal,
    total_fee: Decimal,
) -> Decimal:
    """Return realized P/L for a sell fill after all recorded sell-side fees."""
    return fill_quantity * fill_price - total_fee - average_cost * fill_quantity
