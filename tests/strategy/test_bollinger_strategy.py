"""布林带策略测试。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import Symbol
from strategy.examples.bollinger import BollingerStrategy


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


class TestBollingerStrategy:
    def test_no_signal_before_enough_data(self):
        bus = EventBus()
        strategy = BollingerStrategy(bus, bb_period=5)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        for i in range(4):
            strategy.on_data(_make_event(Symbol("600519"), 100.0, i))
            bus.drain()

        assert len(signals) == 0

    def test_lower_band_buy_signal(self):
        """价格跌破下轨应发出买入信号。"""
        bus = EventBus()
        strategy = BollingerStrategy(bus, bb_period=5, num_std=2.0)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # 先横盘 5 天建立带宽，然后突然大幅下跌突破下轨
        prices = [100, 100, 100, 100, 100, 85]  # 第6天大幅下跌
        for i, price in enumerate(prices):
            strategy.on_data(_make_event(Symbol("600519"), float(price), i))

        bus.drain()
        buy_signals = [s for s in signals if s.target_weight == Decimal("1")]
        assert len(buy_signals) == 1

    def test_middle_band_sell_signal(self):
        """持有时价格回升至中轨应发出卖出信号。"""
        bus = EventBus()
        strategy = BollingerStrategy(bus, bb_period=5, num_std=2.0)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # 先横盘，再跌破下轨买入，再回升至中轨卖出
        prices = [100, 100, 100, 100, 100, 85, 100]
        for i, price in enumerate(prices):
            strategy.on_data(_make_event(Symbol("600519"), float(price), i))

        bus.drain()
        buy_signals = [s for s in signals if s.target_weight == Decimal("1")]
        sell_signals = [s for s in signals if s.target_weight == Decimal("0")]
        assert len(buy_signals) >= 1
        assert len(sell_signals) >= 1

    def test_registry(self):
        """布林带策略应已注册到注册表。"""
        from strategy.registry import StrategyRegistry

        assert "bollinger" in StrategyRegistry.list_strategies()
