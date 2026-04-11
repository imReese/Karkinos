"""月度目标权重再平衡策略。"""

from __future__ import annotations

from collections import defaultdict

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy


class MonthlyRebalanceStrategy(Strategy):
    """月度目标权重再平衡策略。

    每月第一个交易日按预设的目标权重发送信号。
    """

    def __init__(
        self,
        event_bus: EventBus,
        target_weights: dict[Symbol, float] | None = None,
        strategy_id: str = "monthly_rebalance",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.target_weights = target_weights or {}
        self._last_month: dict[Symbol, int] = defaultdict(lambda: -1)

    def on_init(self, symbols: list[Symbol]) -> None:
        for symbol in symbols:
            self._last_month[symbol] = -1

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        symbol = event.symbol
        current_month = event.timestamp.month

        # 检查是否跨月
        if current_month != self._last_month[symbol]:
            self._last_month[symbol] = current_month

            weight = self.target_weights.get(symbol, 0.0)
            price = float(event.close)
            self.emit_signal(symbol, target_weight=weight, price=price)
