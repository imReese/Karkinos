"""Live pre-trade context provider tests."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from core.types import Symbol
from domain.position import Position
from server.services.live_context import LiveContextProvider
from server.services.trading_controls import TradingControlState


def test_live_context_provider_uses_portfolio_and_trading_controls() -> None:
    symbol = Symbol("600519")
    position = Position(symbol)
    position.quantity = Decimal("100")
    position.market_value = Decimal("12000")
    portfolio = SimpleNamespace(
        cash=Decimal("88000"),
        positions={symbol: position},
        instruments={},
    )
    controls = TradingControlState()
    controls.set_kill_switch(True, "operator stop")

    provider = LiveContextProvider(
        portfolio_getter=lambda: portfolio,
        controls=controls,
        blacklist_getter=lambda: {"000001"},
        st_symbols_getter=lambda: {"600000"},
    )

    snapshot = provider.snapshot()

    assert snapshot.cash == Decimal("88000")
    assert snapshot.total_equity == Decimal("100000")
    assert snapshot.peak_equity == Decimal("100000")
    assert snapshot.positions[symbol] is position
    assert snapshot.kill_switch_enabled is True
    assert snapshot.blacklist == {"000001"}
    assert snapshot.st_symbols == {"600000"}
