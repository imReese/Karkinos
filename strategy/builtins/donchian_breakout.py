"""Donchian channel breakout research strategy."""

from __future__ import annotations

from collections import defaultdict

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("donchian_breakout")
class DonchianBreakoutStrategy(Strategy):
    """Donchian channel breakout strategy.

    Close above the prior entry channel emits a target-weight entry. Close below
    the prior exit channel exits to cash.
    """

    def __init__(
        self,
        event_bus: EventBus,
        entry_window: int = 55,
        exit_window: int = 20,
        target_weight: float = 1.0,
        strategy_id: str = "donchian_breakout",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.target_weight = target_weight
        self._highs: dict[Symbol, list[float]] = defaultdict(list)
        self._lows: dict[Symbol, list[float]] = defaultdict(list)
        self._holding: dict[Symbol, bool] = defaultdict(bool)

    def on_init(self, symbols: list[Symbol]) -> None:
        for symbol in symbols:
            self._highs[symbol] = []
            self._lows[symbol] = []
            self._holding[symbol] = False

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        symbol = event.symbol
        price = float(event.close)
        highs = self._highs[symbol]
        lows = self._lows[symbol]

        prior_entry_high = (
            max(highs[-self.entry_window :])
            if len(highs) >= self.entry_window
            else None
        )
        prior_exit_low = (
            min(lows[-self.exit_window :]) if len(lows) >= self.exit_window else None
        )

        if (
            not self._holding[symbol]
            and prior_entry_high is not None
            and price > prior_entry_high
        ):
            self._holding[symbol] = True
            self.emit_signal(symbol, target_weight=self.target_weight, price=price)
        elif (
            self._holding[symbol]
            and prior_exit_low is not None
            and price < prior_exit_low
        ):
            self._holding[symbol] = False
            self.emit_signal(symbol, target_weight=0.0, price=price)

        highs.append(float(event.high))
        lows.append(float(event.low))
