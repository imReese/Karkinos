"""Value conversion and valuation helpers for canonical ledger projections."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from domain.portfolio_accounting import total_trade_fee
from server.ledger.models import LedgerEntry
from server.projections.models import PortfolioProjection
from server.valuation.service import value_position


def apply_valuations(
    projection: PortfolioProjection,
    latest_quotes: Mapping[str, Any],
) -> None:
    for symbol, position in projection.positions.items():
        market_price = quote_price(symbol, position.avg_cost, latest_quotes)
        valuation = value_position(position.quantity, position.avg_cost, market_price)
        position.market_value = valuation.market_value
        position.unrealized_pnl = valuation.unrealized_pnl


def quote_price(
    symbol: str,
    fallback: Decimal,
    latest_quotes: Mapping[str, Any],
) -> Decimal:
    quote = latest_quotes.get(symbol)
    price = quote.get("price") if isinstance(quote, Mapping) else quote
    if price in {None, "", 0, 0.0}:
        return fallback
    return as_decimal(price)


def trade_side(entry: LedgerEntry) -> str:
    direction = (entry.direction or "").strip().lower()
    if direction in {"buy", "sell"}:
        return direction

    entry_type = (entry.entry_type or "").strip().lower()
    if entry_type.endswith("_buy") or entry_type == "buy":
        return "buy"
    if entry_type.endswith("_sell") or entry_type == "sell":
        return "sell"
    return ""


def trade_total_fee(entry: LedgerEntry) -> Decimal:
    return total_trade_fee(
        commission=as_decimal(entry.commission),
        fee_breakdown=entry.fee_breakdown,
    )


def require_decimal(value: float | Decimal | None, field_name: str) -> Decimal:
    if value is None:
        raise ValueError(f"Missing {field_name} on ledger entry")
    return as_decimal(value)


def require_text(value: str | None, field_name: str) -> str:
    if not value:
        raise ValueError(f"Missing {field_name} on ledger entry")
    return value


def as_decimal(value: float | Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


__all__ = (
    "apply_valuations",
    "as_decimal",
    "quote_price",
    "require_decimal",
    "require_text",
    "trade_side",
    "trade_total_fee",
)
