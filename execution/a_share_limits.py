"""A-share daily price-limit and suspension constraints.

These are deterministic, provider-free trading constraints used by the
canonical backtest execution path.  They never contact a broker, grant
authority, or change capital; they only decide whether a simulated fill is
tradable on a given bar.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MAIN_BOARD_RATE = Decimal("0.10")
GROWTH_BOARD_RATE = Decimal("0.20")
ST_RATE = Decimal("0.05")
_PRICE_TICK = Decimal("0.01")

_GROWTH_BOARD_PREFIXES = ("30", "68")  # ChiNext 300xxx, STAR 688xxx


def normalize_code(symbol: str) -> str:
    """Strip any exchange suffix and return the bare six-digit code."""

    return str(symbol).strip().split(".")[0]


def limit_rate_for_symbol(symbol: str) -> Decimal:
    """Return the daily price-limit rate for an A-share symbol.

    ST treatment requires the point-in-time security master and is therefore
    not inferred here; ST symbols are a documented limitation.
    """

    code = normalize_code(symbol)
    if code.startswith(_GROWTH_BOARD_PREFIXES):
        return GROWTH_BOARD_RATE
    return MAIN_BOARD_RATE


def limit_up_price(prev_close: Decimal, rate: Decimal) -> Decimal:
    """Round the limit-up price to the exchange tick."""

    return _round_tick(prev_close * (Decimal("1") + rate))


def limit_down_price(prev_close: Decimal, rate: Decimal) -> Decimal:
    """Round the limit-down price to the exchange tick."""

    return _round_tick(prev_close * (Decimal("1") - rate))


def is_limit_up(close: Decimal, prev_close: Decimal, rate: Decimal) -> bool:
    return close >= limit_up_price(prev_close, rate)


def is_limit_down(close: Decimal, prev_close: Decimal, rate: Decimal) -> bool:
    return close <= limit_down_price(prev_close, rate)


def is_suspended(volume: Decimal) -> bool:
    """A bar with no traded volume is treated as suspended/untradeable."""

    return volume <= Decimal("0")


def _round_tick(value: Decimal) -> Decimal:
    return value.quantize(_PRICE_TICK, rounding=ROUND_HALF_UP)


__all__ = [
    "MAIN_BOARD_RATE",
    "GROWTH_BOARD_RATE",
    "ST_RATE",
    "normalize_code",
    "limit_rate_for_symbol",
    "limit_up_price",
    "limit_down_price",
    "is_limit_up",
    "is_limit_down",
    "is_suspended",
]
