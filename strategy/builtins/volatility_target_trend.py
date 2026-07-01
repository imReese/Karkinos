"""Volatility-targeted trend research strategy."""

from __future__ import annotations

from collections import defaultdict

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("volatility_target_trend")
class VolatilityTargetTrendStrategy(Strategy):
    """Trend-following strategy with realized-volatility position sizing."""

    def __init__(
        self,
        event_bus: EventBus,
        lookback_period: int = 126,
        volatility_window: int = 20,
        target_annual_volatility: float = 0.15,
        max_weight: float = 1.0,
        min_momentum: float = 0.0,
        rebalance_threshold: float = 0.05,
        strategy_id: str = "volatility_target_trend",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.lookback_period = lookback_period
        self.volatility_window = volatility_window
        self.target_annual_volatility = target_annual_volatility
        self.max_weight = max_weight
        self.min_momentum = min_momentum
        self.rebalance_threshold = rebalance_threshold
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

        required = max(self.lookback_period, self.volatility_window) + 1
        if len(prices) < required:
            return

        reference_price = prices[-self.lookback_period - 1]
        if reference_price <= 0:
            return

        momentum = price / reference_price - 1.0
        next_target = 0.0
        if momentum > self.min_momentum:
            realized_vol = _annualized_realized_volatility(
                prices[-self.volatility_window - 1 :]
            )
            if realized_vol <= 0:
                next_target = self.max_weight
            else:
                next_target = min(
                    self.max_weight,
                    self.target_annual_volatility / realized_vol,
                )

        current_target = self._current_target[symbol]
        if abs(next_target - current_target) >= self.rebalance_threshold:
            self._current_target[symbol] = next_target
            self.emit_signal(symbol, target_weight=round(next_target, 6), price=price)


def _annualized_realized_volatility(prices: list[float]) -> float:
    returns = [
        prices[index] / prices[index - 1] - 1.0
        for index in range(1, len(prices))
        if prices[index - 1] > 0
    ]
    if not returns:
        return 0.0

    mean_return = sum(returns) / len(returns)
    variance = sum((ret - mean_return) ** 2 for ret in returns) / len(returns)
    return (variance**0.5) * (252**0.5)
