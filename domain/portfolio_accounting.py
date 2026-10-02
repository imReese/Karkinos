"""Canonical portfolio cost-basis calculations.

These pure functions are shared by simulation and persisted-ledger projections so
that a fill has one financial interpretation across product surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, DecimalException, Inexact, localcontext
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


def share_distribution_quantity(
    *, eligible_quantity: Decimal, shares_per_share: Decimal
) -> Decimal:
    """Calculate only awards which need no account-specific fractional allocation."""
    for value in (eligible_quantity, shares_per_share):
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise ValueError("portfolio_share_distribution_quantity_invalid")
    if eligible_quantity != eligible_quantity.to_integral_value():
        raise ValueError("portfolio_share_distribution_fractional_unsupported")
    try:
        with localcontext() as context:
            context.prec = max(
                context.prec,
                len(eligible_quantity.as_tuple().digits)
                + len(shares_per_share.as_tuple().digits),
            )
            context.traps[Inexact] = True
            quantity = eligible_quantity * shares_per_share
    except DecimalException as exc:
        raise ValueError("portfolio_share_distribution_quantity_invalid") from exc
    if not quantity.is_finite():
        raise ValueError("portfolio_share_distribution_quantity_invalid")
    if quantity != quantity.to_integral_value():
        raise ValueError("portfolio_share_distribution_fractional_unsupported")
    return quantity


def average_cost_after_share_distribution(
    *,
    current_quantity: Decimal,
    current_average_cost: Decimal,
    distribution_quantity: Decimal,
) -> Decimal:
    """Spread the existing book cost over an integer award, without adding income.

    Extra division precision keeps a subsequent quantity-times-average operation
    from changing the existing cost at the caller's Decimal working precision.
    This is moving-average research book cost, not an investor's tax basis.
    """
    for value in (current_quantity, distribution_quantity):
        share_distribution_quantity(
            eligible_quantity=value, shares_per_share=Decimal(1)
        )
    if (
        not isinstance(current_average_cost, Decimal)
        or not current_average_cost.is_finite()
        or current_average_cost < 0
    ):
        raise ValueError("portfolio_share_distribution_cost_invalid")
    try:
        with localcontext() as context:
            context.traps[Inexact] = True
            new_quantity = current_quantity + distribution_quantity
        if new_quantity == 0:
            return Decimal(0)
        existing_cost = current_quantity * current_average_cost
        with localcontext() as context:
            context.prec += len(new_quantity.as_tuple().digits) + 2
            average_cost = existing_cost / new_quantity
        if not average_cost.is_finite():
            raise ValueError("portfolio_share_distribution_cost_invalid")
        return average_cost
    except DecimalException as exc:
        raise ValueError("portfolio_share_distribution_cost_invalid") from exc
