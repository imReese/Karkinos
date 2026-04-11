"""RSI 超买超卖策略。"""

from __future__ import annotations

from collections import defaultdict

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("rsi")
class RSIStrategy(Strategy):
    """RSI 超买超卖策略。

    RSI 从超卖区（<oversold）回升 → 买入，
    RSI 从超买区（>overbought）回落 → 卖出。
    使用 Wilder 平滑法计算 RSI。
    """

    def __init__(
        self,
        event_bus: EventBus,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        strategy_id: str = "rsi",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self._prices: dict[Symbol, list[float]] = defaultdict(list)
        self._avg_gain: dict[Symbol, float | None] = {}
        self._avg_loss: dict[Symbol, float | None] = {}
        self._prev_rsi: dict[Symbol, float | None] = {}

    def on_init(self, symbols: list[Symbol]) -> None:
        for symbol in symbols:
            self._prices[symbol] = []
            self._avg_gain[symbol] = None
            self._avg_loss[symbol] = None
            self._prev_rsi[symbol] = None

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        symbol = event.symbol
        price = float(event.close)
        self._prices[symbol].append(price)

        rsi = self._calculate_rsi(symbol)
        if rsi is None:
            return

        prev_rsi = self._prev_rsi[symbol]
        self._prev_rsi[symbol] = rsi

        if prev_rsi is None:
            return

        # RSI 从超卖区回升 → 买入
        if prev_rsi < self.oversold and rsi >= self.oversold:
            self.emit_signal(symbol, target_weight=1.0, price=price)
        # RSI 从超买区回落 → 卖出
        elif prev_rsi > self.overbought and rsi <= self.overbought:
            self.emit_signal(symbol, target_weight=0.0, price=price)

    def _calculate_rsi(self, symbol: Symbol) -> float | None:
        """使用 Wilder 平滑法计算 RSI。"""
        prices = self._prices[symbol]
        period = self.rsi_period

        # 需要至少 period+1 个价格点才能算出 RSI
        if len(prices) < period + 1:
            return None

        if self._avg_gain[symbol] is None:
            # 初始化：用前 period+1 个价格计算初始 avg_gain/avg_loss
            gains = []
            losses = []
            for i in range(1, period + 1):
                change = prices[i] - prices[i - 1]
                gains.append(max(change, 0))
                losses.append(max(-change, 0))

            self._avg_gain[symbol] = sum(gains) / period
            self._avg_loss[symbol] = sum(losses) / period
        else:
            # Wilder 平滑
            change = prices[-1] - prices[-2]
            gain = max(change, 0)
            loss = max(-change, 0)
            self._avg_gain[symbol] = (
                self._avg_gain[symbol] * (period - 1) + gain
            ) / period
            self._avg_loss[symbol] = (
                self._avg_loss[symbol] * (period - 1) + loss
            ) / period

        avg_loss = self._avg_loss[symbol]
        if avg_loss == 0:
            return 100.0

        rs = self._avg_gain[symbol] / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
