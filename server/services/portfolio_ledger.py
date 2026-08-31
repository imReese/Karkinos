"""Rebuild runtime portfolio state from the canonical persisted ledger."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from core.event_bus import EventBus
from core.types import AssetClass, Symbol
from data.manager import DataManager
from domain.portfolio import Portfolio
from domain.position import Position
from server.ledger.models import LedgerEntry
from server.projections.service import build_portfolio_projection

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}


def rebuild_portfolio_from_ledger(
    config: Any,
    db: Any,
    latest_quotes: dict[str, dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Recreate runtime state exclusively from canonical ledger facts."""

    ledger_entries = _load_ledger_entries(db)
    projection = build_portfolio_projection(
        ledger_entries,
        initial_cash=Decimal("0"),
    )

    portfolio = Portfolio(
        EventBus(),
        initial_cash=Decimal("0"),
    )
    portfolio.cash = projection.cash
    portfolio.total_deposits = projection.total_deposits
    instruments: dict[Symbol, object] = {}

    def ensure_instrument(symbol: str, asset_class: str) -> object:
        symbol_value = Symbol(symbol)
        if symbol_value not in instruments:
            mapped = _ASSET_CLASS_MAP.get(asset_class, AssetClass.STOCK)
            instrument = DataManager.get_instrument(symbol_value, mapped)
            instruments[symbol_value] = instrument
            portfolio.add_instrument(instrument)
        return instruments[symbol_value]

    for asset in getattr(config, "assets", []):
        ensure_instrument(asset["symbol"], asset["asset_class"])

    asset_class_by_symbol = _asset_class_by_symbol(ledger_entries)
    for symbol, projected in projection.positions.items():
        ensure_instrument(symbol, asset_class_by_symbol.get(symbol, "stock"))
        position = Position(Symbol(symbol))
        position.quantity = projected.quantity
        position.frozen_qty = projected.frozen_qty
        position.avg_cost = projected.avg_cost
        position.realized_pnl = projected.realized_pnl
        position.commission_paid = projected.commission_paid
        position.market_value = projected.market_value
        position.unrealized_pnl = projected.unrealized_pnl
        position.closed_at = projected.closed_at
        position.broker_displayed_cost_basis = projected.broker_displayed_cost_basis
        position.broker_displayed_unit_cost = projected.broker_displayed_unit_cost
        position.broker_cost_basis_difference = projected.broker_cost_basis_difference
        position.broker_cost_basis_method = projected.broker_cost_basis_method
        position.broker_cost_basis_status = projected.broker_cost_basis_status
        portfolio.positions[Symbol(symbol)] = position

    latest_quotes = latest_quotes or {}
    prices = {
        symbol: (
            Decimal(str(quote_price))
            if (quote_price := latest_quotes.get(str(symbol), {}).get("price"))
            not in {None, 0}
            else position.avg_cost
        )
        for symbol, position in portfolio.positions.items()
    }
    if prices:
        portfolio.mark_to_market(prices)
    return SimpleNamespace(portfolio=portfolio, instruments=instruments)


def _load_ledger_entries(db: Any, *, batch_size: int = 500) -> list[LedgerEntry]:
    reader = getattr(db, "get_ledger_entries_sync", None)
    if not callable(reader):
        raise RuntimeError("canonical ledger reader is unavailable")
    entries: list[LedgerEntry] = []
    offset = 0
    while True:
        rows = reader(limit=batch_size, offset=offset) or []
        entries.extend(LedgerEntry.from_row(dict(row)) for row in rows)
        if len(rows) < batch_size:
            return entries
        offset += batch_size


def _asset_class_by_symbol(entries: list[LedgerEntry]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in entries:
        symbol = str(entry.symbol or "").strip()
        if symbol:
            result[symbol] = str(entry.asset_class or "stock")
    return result


__all__ = ["rebuild_portfolio_from_ledger"]
