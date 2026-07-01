"""Time-series momentum research strategy."""

from __future__ import annotations

from collections import defaultdict

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("time_series_momentum")
class TimeSeriesMomentumStrategy(Strategy):
    """Time-series momentum strategy.

    If the lookback return is above the entry threshold, target the configured
    weight. If it falls to or below the exit threshold, exit to cash.
    """

    def __init__(
        self,
        event_bus: EventBus,
        lookback_period: int = 126,
        min_return: float = 0.0,
        exit_return: float = 0.0,
        target_weight: float = 1.0,
        strategy_id: str = "time_series_momentum",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.lookback_period = lookback_period
        self.min_return = min_return
        self.exit_return = exit_return
        self.target_weight = target_weight
        self._prices: dict[Symbol, list[float]] = defaultdict(list)
        self._current_target: dict[Symbol, float] = defaultdict(float)

    def on_init(self, symbols: list[Symbol]) -> None:
        for symbol in symbols:
            self._prices[symbol] = []
            self._current_target[symbol] = 0.0

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        symbol = event.symbol
        price = float(event.close)
        self._prices[symbol].append(price)

        prices = self._prices[symbol]
        if len(prices) <= self.lookback_period:
            return

        reference_price = prices[-self.lookback_period - 1]
        if reference_price <= 0:
            return

        lookback_return = price / reference_price - 1.0
        current_target = self._current_target[symbol]
        next_target = current_target
        if lookback_return > self.min_return:
            next_target = self.target_weight
        elif lookback_return <= self.exit_return:
            next_target = 0.0

        if next_target != current_target:
            self._current_target[symbol] = next_target
            self.emit_signal(symbol, target_weight=next_target, price=price)
