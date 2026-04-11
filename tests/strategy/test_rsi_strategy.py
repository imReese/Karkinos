"""RSI 策略测试。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import Symbol
from strategy.examples.rsi import RSIStrategy


def _make_event(symbol: Symbol, price: float, day: int) -> MarketEvent:
    return MarketEvent(
        timestamp=datetime(2024, 1, day + 1),
        symbol=symbol,
        open=Decimal(str(price)),
        high=Decimal(str(price + 1)),
        low=Decimal(str(price - 1)),
        close=Decimal(str(price)),
        volume=Decimal("10000"),
    )


class TestRSIStrategy:
    def test_no_signal_before_enough_data(self):
        bus = EventBus()
        strategy = RSIStrategy(bus, rsi_period=5)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # rsi_period=5，需要 6 根 K 线才能算出 RSI，再加 1 根才能判断穿越
        for i in range(6):
            strategy.on_data(_make_event(Symbol("600519"), 100.0 + i, i))
            bus.drain()

        assert len(signals) == 0

    def test_oversold_buy_signal(self):
        """RSI 从超卖区回升应发出买入信号。"""
        bus = EventBus()
        strategy = RSIStrategy(bus, rsi_period=5, oversold=30, overbought=70)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # 先大幅下跌制造超卖，再回升
        prices = [100, 95, 90, 85, 80, 75, 70, 72, 78]
        for i, price in enumerate(prices):
            strategy.on_data(_make_event(Symbol("600519"), float(price), i))

        bus.drain()
        buy_signals = [s for s in signals if s.target_weight == Decimal("1")]
        assert len(buy_signals) >= 1

    def test_overbought_sell_signal(self):
        """RSI 从超买区回落应发出卖出信号。"""
        bus = EventBus()
        strategy = RSIStrategy(bus, rsi_period=5, oversold=30, overbought=70)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # 先大幅上涨制造超买，再回落
        prices = [100, 105, 110, 115, 120, 125, 130, 128, 122]
        for i, price in enumerate(prices):
            strategy.on_data(_make_event(Symbol("600519"), float(price), i))

        bus.drain()
        sell_signals = [s for s in signals if s.target_weight == Decimal("0")]
        assert len(sell_signals) >= 1

    def test_registry(self):
        """RSI 策略应已注册到注册表。"""
        from strategy.registry import StrategyRegistry

        assert "rsi" in StrategyRegistry.list_strategies()
