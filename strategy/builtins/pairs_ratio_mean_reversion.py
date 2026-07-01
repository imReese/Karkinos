"""Long-only pairs ratio mean-reversion research strategy."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("pairs_ratio_mean_reversion")
class PairsRatioMeanReversionStrategy(Strategy):
    """Long-only pair ratio mean-reversion strategy.

    A low A/B ratio rotates to leg A; a high A/B ratio rotates to leg B. When
    the spread normalizes, both legs return to the configured neutral weight.
    """

    def __init__(
        self,
        event_bus: EventBus,
        symbol_a: str = "",
        symbol_b: str = "",
        lookback_period: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        pair_weight: float = 1.0,
        neutral_weight: float = 0.5,
        strategy_id: str = "pairs_ratio_mean_reversion",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self.symbol_a = Symbol(symbol_a) if symbol_a else None
        self.symbol_b = Symbol(symbol_b) if symbol_b else None
        self.lookback_period = lookback_period
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.pair_weight = pair_weight
        self.neutral_weight = neutral_weight
        self._latest_close: dict[Symbol, float] = {}
        self._seen_by_date: dict[date, set[Symbol]] = defaultdict(set)
        self._last_ratio_date: date | None = None
        self._ratios: list[float] = []
        self._current_targets: dict[Symbol, float | None] = defaultdict(lambda: None)
        self._mode = "neutral"

    def on_init(self, symbols: list[Symbol]) -> None:
        if self.symbol_a is None and len(symbols) >= 1:
            self.symbol_a = symbols[0]
        if self.symbol_b is None and len(symbols) >= 2:
            self.symbol_b = symbols[1]
        for symbol in symbols:
            self._current_targets[symbol] = None

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        if self.symbol_a is None or self.symbol_b is None:
            return
        if event.symbol not in {self.symbol_a, self.symbol_b}:
            return

        current_date = event.timestamp.date()
        self._latest_close[event.symbol] = float(event.close)
        self._seen_by_date[current_date].add(event.symbol)

        if (
            self.symbol_a not in self._seen_by_date[current_date]
            or self.symbol_b not in self._seen_by_date[current_date]
            or self._last_ratio_date == current_date
        ):
            return

        price_a = self._latest_close.get(self.symbol_a)
        price_b = self._latest_close.get(self.symbol_b)
        if price_a is None or price_b is None or price_b <= 0:
            return

        self._last_ratio_date = current_date
        ratio = price_a / price_b
        self._ratios.append(ratio)
        if len(self._ratios) < self.lookback_period:
            return

        window = self._ratios[-self.lookback_period :]
        mean_ratio = sum(window) / len(window)
        variance = sum((value - mean_ratio) ** 2 for value in window) / len(window)
        std = variance**0.5
        if std <= 0:
            return

        z_score = (ratio - mean_ratio) / std
        if z_score <= -self.entry_z and self._mode != "long_a":
            self._mode = "long_a"
            self._emit_pair_targets(self.pair_weight, 0.0)
        elif z_score >= self.entry_z and self._mode != "long_b":
            self._mode = "long_b"
            self._emit_pair_targets(0.0, self.pair_weight)
        elif abs(z_score) <= self.exit_z and self._mode != "neutral":
            self._mode = "neutral"
            self._emit_pair_targets(self.neutral_weight, self.neutral_weight)

    def _emit_pair_targets(self, target_a: float, target_b: float) -> None:
        assert self.symbol_a is not None
        assert self.symbol_b is not None
        for symbol, target in (
            (self.symbol_a, target_a),
            (self.symbol_b, target_b),
        ):
            if self._current_targets[symbol] == target:
                continue
            self._current_targets[symbol] = target
            self.emit_signal(
                symbol,
                target_weight=target,
                price=self._latest_close.get(symbol),
            )
