"""Canonical quantity precision and current-position classification."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

# Fund quantities are represented to six decimal places elsewhere in Karkinos.
# Half of that quantum is the largest residual that rounds to zero at the
# canonical precision. Stocks and ETFs use coarser quantities, so this remains
# conservative for them as well.
POSITION_QUANTITY_QUANTUM = Decimal("0.000001")
POSITION_QUANTITY_ZERO_TOLERANCE = POSITION_QUANTITY_QUANTUM / Decimal("2")
POSITION_MONEY_ZERO_TOLERANCE = Decimal("0.005")

PositionPresence = Literal["current", "closed", "review_required"]


def is_economically_zero_quantity(value: Any) -> bool:
    """Return whether a persisted quantity is zero at canonical precision.

    Invalid or non-finite values deliberately return ``False`` so incomplete
    evidence is never silently discarded as a closed position.
    """

    quantity = _finite_decimal(value)
    if quantity is None:
        return False
    return abs(quantity) <= POSITION_QUANTITY_ZERO_TOLERANCE


def classify_position_presence(position: Any) -> tuple[PositionPresence, list[str]]:
    """Partition a projected position without changing the underlying facts."""

    if not is_economically_zero_quantity(getattr(position, "quantity", None)):
        return "current", []

    reasons: list[str] = []
    if not is_economically_zero_quantity(
        getattr(position, "available_qty", Decimal("0"))
    ):
        reasons.append("available_quantity_nonzero")
    if not is_economically_zero_quantity(getattr(position, "frozen_qty", Decimal("0"))):
        reasons.append("frozen_quantity_nonzero")
    if not _is_economically_zero_money(getattr(position, "market_value", None)):
        reasons.append("market_value_nonzero")
    if not _is_economically_zero_money(getattr(position, "unrealized_pnl", None)):
        reasons.append("unrealized_pnl_nonzero")

    if reasons:
        return "review_required", reasons
    return "closed", ["quantity_zero_at_canonical_precision"]


def _is_economically_zero_money(value: Any) -> bool:
    amount = _finite_decimal(value)
    if amount is None:
        return False
    return abs(amount) <= POSITION_MONEY_ZERO_TOLERANCE


def _finite_decimal(value: Any) -> Decimal | None:
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return decimal_value if decimal_value.is_finite() else None
