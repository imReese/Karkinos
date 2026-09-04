"""Value conversion and valuation helpers for canonical ledger projections."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from domain.portfolio_accounting import total_trade_fee
from server.ledger.models import LedgerEntry
from server.projections.models import PortfolioProjection
from server.projections.quote_status import quote_valuation_status
from server.valuation.service import value_position


def apply_valuations(
    projection: PortfolioProjection,
    latest_quotes: Mapping[str, Any],
) -> None:
    missing_symbols: list[str] = []
    for symbol, position in projection.positions.items():
        market_price = quote_price(symbol, position.avg_cost, latest_quotes)
        if market_price is None:
            position.market_value = Decimal("0")
            position.unrealized_pnl = Decimal("0")
            position.valuation_available = position.quantity == 0
            position.valuation_price = None
            if position.quantity != 0:
                missing_symbols.append(symbol)
            continue
        valuation = value_position(position.quantity, position.avg_cost, market_price)
        position.market_value = valuation.market_value
        position.unrealized_pnl = valuation.unrealized_pnl
        position.valuation_available = True
        position.valuation_price = market_price

    projection.missing_price_symbols = sorted(set(missing_symbols))
    projection.valuation_status = "complete" if not missing_symbols else "blocked"


def quote_price(
    symbol: str,
    fallback: Decimal,
    latest_quotes: Mapping[str, Any],
) -> Decimal | None:
    """Return persisted quote evidence; cost basis is never a market-price fallback.

    ``fallback`` remains in the call signature while legacy callers migrate, but
    is intentionally ignored.  Average cost is cost evidence, not market data.
    """

    del fallback
    quote = latest_quotes.get(symbol)
    if isinstance(quote, Mapping) and quote_valuation_status(dict(quote)) != "complete":
        return None
    price = quote.get("price") if isinstance(quote, Mapping) else quote
    if price in {None, "", 0, 0.0}:
        return None
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
