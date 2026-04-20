"""Rebuild portfolio state from persisted cash flows and manual trades."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from core.event_bus import EventBus
from core.events import FillEvent
from core.types import AssetClass, OrderSide, Symbol
from data.manager import DataManager
from domain.portfolio import Portfolio

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}


def _sorted_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row.get("timestamp") or "", row.get("id") or 0))


def rebuild_portfolio_from_ledger(
    config,
    db,
    latest_quotes: dict[str, dict] | None = None,
):
    """Recreate the current portfolio state from config + persisted ledger rows."""
    portfolio = Portfolio(EventBus(), initial_cash=Decimal(str(config.initial_cash)))
    instruments: dict[Symbol, object] = {}

    def ensure_instrument(symbol: str, asset_class: str):
        sym = Symbol(symbol)
        if sym not in instruments:
            ac = _ASSET_CLASS_MAP.get(asset_class, AssetClass.STOCK)
            inst = DataManager.get_instrument(sym, ac)
            instruments[sym] = inst
            portfolio.add_instrument(inst)
        return instruments[sym]

    for asset in getattr(config, "assets", []):
        ensure_instrument(asset["symbol"], asset["asset_class"])

    cash_flows = _sorted_rows(db.get_cash_flows_sync(limit=1000, offset=0))
    for flow in cash_flows:
        amount = Decimal(str(flow["amount"]))
        if flow["flow_type"] == "deposit":
            portfolio.deposit(amount)
        else:
            portfolio.withdraw(amount)

    trades = _sorted_rows(db.get_trades_sync(limit=1000, offset=0))
    for trade in trades:
        ensure_instrument(trade["symbol"], trade["asset_class"])
        fill = FillEvent(
            timestamp=datetime.fromisoformat(trade["timestamp"]),
            fill_id=f"LEDGER-{uuid4().hex[:8]}",
            order_id=f"LEDGER-ORD-{uuid4().hex[:8]}",
            symbol=Symbol(trade["symbol"]),
            side=OrderSide.BUY if trade["direction"] == "buy" else OrderSide.SELL,
            fill_price=Decimal(str(trade["price"])),
            fill_quantity=Decimal(str(trade["quantity"])),
            commission=Decimal(str(trade["commission"])),
            slippage=Decimal("0"),
        )
        portfolio.on_fill(fill)

    prices = {}
    latest_quotes = latest_quotes or {}
    for sym, position in portfolio.positions.items():
        quote_price = latest_quotes.get(str(sym), {}).get("price")
        prices[sym] = (
            Decimal(str(quote_price))
            if quote_price not in {None, 0}
            else position.avg_cost
        )
    if prices:
        portfolio.mark_to_market(prices)

    return SimpleNamespace(portfolio=portfolio, instruments=instruments)
