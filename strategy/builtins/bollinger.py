"""布林带均值回归策略。"""

from __future__ import annotations

from collections import defaultdict

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("bollinger")
class BollingerStrategy(Strategy):
    """布林带均值回归策略。

    价格跌破下轨 → 买入（均值回归），
    价格回升至中轨 → 卖出。
    """

    def __init__(
        self,
        event_bus: EventBus,
        bb_period: int = 20,
        num_std: float = 2.0,
        strategy_id: str = "bollinger",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.bb_period = bb_period
        self.num_std = num_std
        self._prices: dict[Symbol, list[float]] = defaultdict(list)
        self._holding: dict[Symbol, bool] = {}

    def on_init(self, symbols: list[Symbol]) -> None:
        for symbol in symbols:
            self._prices[symbol] = []
            self._holding[symbol] = False

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        symbol = event.symbol
        price = float(event.close)
        self._prices[symbol].append(price)

        if len(self._prices[symbol]) < self.bb_period:
            return

        prices = self._prices[symbol]
        window = prices[-self.bb_period :]
        ma = sum(window) / self.bb_period
        variance = sum((p - ma) ** 2 for p in window) / self.bb_period
        std = variance**0.5
        upper = ma + self.num_std * std
        lower = ma - self.num_std * std

        holding = self._holding[symbol]

        # 跌破下轨 → 买入
        if price <= lower and not holding:
            self.emit_signal(symbol, target_weight=1.0, price=price)
            self._holding[symbol] = True
        # 回升到中轨 → 卖出
        elif price >= ma and holding:
            self.emit_signal(symbol, target_weight=0.0, price=price)
            self._holding[symbol] = False
