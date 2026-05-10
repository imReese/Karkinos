"""Live pre-trade context assembly."""

from __future__ import annotations

from decimal import Decimal
from typing import Callable

from core.types import ZERO, Symbol
from domain.portfolio import Portfolio
from risk.pre_trade import PreTradeContext
from server.services.trading_controls import TradingControlState


class LiveContextProvider:
    """Build PreTradeContext from live portfolio and runtime controls."""

    def __init__(
        self,
        *,
        portfolio_getter: Callable[[], Portfolio | None],
        controls: TradingControlState,
        blacklist_getter: Callable[[], set[str]] | None = None,
        st_symbols_getter: Callable[[], set[str]] | None = None,
    ) -> None:
        self._portfolio_getter = portfolio_getter
        self._controls = controls
        self._blacklist_getter = blacklist_getter or (lambda: set())
        self._st_symbols_getter = st_symbols_getter or (lambda: set())
        self._peak_equity = ZERO

    def snapshot(self) -> PreTradeContext:
        portfolio = self._portfolio_getter()
        if portfolio is None:
            cash = ZERO
            positions = {}
            instruments = {}
        else:
            cash = Decimal(str(portfolio.cash))
            positions = dict(portfolio.positions)
            instruments = dict(portfolio.instruments)

        positions_value = sum(
            Decimal(str(position.market_value)) for position in positions.values()
        )
        total_equity = cash + positions_value
        if total_equity > self._peak_equity:
            self._peak_equity = total_equity

        controls = self._controls.snapshot()
        return PreTradeContext(
            cash=cash,
            total_equity=total_equity,
            peak_equity=self._peak_equity,
            positions=positions,
            instruments=instruments,
            blacklist=set(self._blacklist_getter()),
            st_symbols=set(self._st_symbols_getter()),
            kill_switch_enabled=controls.kill_switch_enabled,
        )
