"""双均线交叉策略。"""

from __future__ import annotations

from collections import defaultdict

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("dual_ma")
class DualMAStrategy(Strategy):
    """双均线交叉策略。

    短期均线上穿长期均线 → 目标权重 1（全仓）
    短期均线下穿长期均线 → 目标权重 0（清仓）
    """

    def __init__(
        self,
        event_bus: EventBus,
        short_period: int = 5,
        long_period: int = 20,
        strategy_id: str = "dual_ma",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.short_period = short_period
        self.long_period = long_period
        self._prices: dict[Symbol, list[float]] = defaultdict(list)
        self._prev_short_above_long: dict[Symbol, bool | None] = {}

    def on_init(self, symbols: list[Symbol]) -> None:
        for symbol in symbols:
            self._prices[symbol] = []
            self._prev_short_above_long[symbol] = None

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        symbol = event.symbol
        price = float(event.close)

        self._prices[symbol].append(price)

        # 需要至少 long_period 根 K 线
        if len(self._prices[symbol]) < self.long_period:
            return

        prices = self._prices[symbol]
        short_ma = sum(prices[-self.short_period :]) / self.short_period
        long_ma = sum(prices[-self.long_period :]) / self.long_period

        short_above_long = short_ma > long_ma
        prev = self._prev_short_above_long[symbol]

        if prev is not None and short_above_long != prev:
            if short_above_long:
                # 金叉：买入信号
                self.emit_signal(symbol, target_weight=1.0, price=price)
            else:
                # 死叉：卖出信号
                self.emit_signal(symbol, target_weight=0.0, price=price)

        self._prev_short_above_long[symbol] = short_above_long
