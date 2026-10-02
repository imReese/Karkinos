"""Donchian channel breakout research strategy."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from core.event_bus import EventBus
from core.events import FillEvent, MarketEvent
from core.types import OrderSide, Symbol
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
        self._filled_quantity: dict[Symbol, Decimal] = {}
        self._signal_holding: dict[Symbol, bool] = {}

    def on_init(self, symbols: list[Symbol]) -> None:
        for symbol in symbols:
            self._highs[symbol] = []
            self._lows[symbol] = []
            self._filled_quantity[symbol] = Decimal("0")
            self._signal_holding[symbol] = False

    def on_fill(self, event: FillEvent) -> None:
        change = (
            event.fill_quantity if event.side is OrderSide.BUY else -event.fill_quantity
        )
        self._filled_quantity[event.symbol] += change

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

        # Scans have no executions; their signal regime is not actual holdings.
        holding = (
            self._filled_quantity[symbol] > 0
            if self.fill_tracking_enabled
            else self._signal_holding[symbol]
        )
        if not holding and prior_entry_high is not None and price > prior_entry_high:
            self._signal_holding[symbol] = True
            self.emit_signal(symbol, target_weight=self.target_weight, price=price)
        elif holding and prior_exit_low is not None and price < prior_exit_low:
            self._signal_holding[symbol] = False
            self.emit_signal(symbol, target_weight=0.0, price=price)

        highs.append(float(event.high))
        lows.append(float(event.low))
