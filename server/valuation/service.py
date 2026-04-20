"""Minimal valuation helpers for reconstructed positions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")


@dataclass(slots=True)
class PositionValuation:
    """Value and unrealized PnL for a single position."""

    market_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal


def value_position(
    quantity: Decimal, avg_cost: Decimal, market_price: Decimal
) -> PositionValuation:
    """Compute a position's market value and unrealized PnL."""
    market_value = quantity * market_price
    unrealized_pnl = market_value - (quantity * avg_cost)
    return PositionValuation(
        market_price=market_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
    )

