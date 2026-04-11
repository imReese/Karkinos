"""Strategy 基类和示例策略测试。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import BarFrequency, Symbol
from strategy.base import Strategy
from strategy.examples.dual_ma import DualMAStrategy
from strategy.examples.monthly_rebalance import MonthlyRebalanceStrategy


class ConcreteStrategy(Strategy):
    """用于测试的具体策略实现。"""

    def on_init(self, symbols: list[Symbol]) -> None:
        self.symbols = symbols

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        # 简单策略：收盘价 > 1850 就全仓，否则清仓
        if event.close > Decimal("1850"):
            self.emit_signal(event.symbol, target_weight=1.0, price=float(event.close))
        else:
            self.emit_signal(event.symbol, target_weight=0.0, price=float(event.close))


class TestStrategyBase:
    def test_emit_signal(self):
        bus = EventBus()
        strategy = ConcreteStrategy("test", bus)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        event = MarketEvent(
            timestamp=datetime(2024, 1, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1870"),
            low=Decimal("1790"),
            close=Decimal("1860"),
            volume=Decimal("10000"),
        )
        strategy.on_data(event)
        bus.drain()

        assert len(signals) == 1
        assert signals[0].target_weight == Decimal("1")
        assert signals[0].strategy_id == "test"


class TestDualMAStrategy:
    def test_no_signal_before_enough_data(self):
        bus = EventBus()
        strategy = DualMAStrategy(bus, short_period=3, long_period=5)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # 前 4 根不应有信号
        for i in range(4):
            event = MarketEvent(
                timestamp=datetime(2024, 1, i + 1),
                symbol=Symbol("600519"),
                open=Decimal("1800"),
                high=Decimal("1850"),
                low=Decimal("1790"),
                close=Decimal(str(1800 + i)),
                volume=Decimal("10000"),
            )
            strategy.on_data(event)
            bus.drain()

        assert len(signals) == 0

    def test_golden_cross_signal(self):
        """金叉应发出买入信号（target_weight=1）。"""
        bus = EventBus()
        strategy = DualMAStrategy(bus, short_period=3, long_period=5)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # 先下跌，再上涨，制造金叉
        prices = [100, 95, 90, 85, 80, 90, 95, 100]
        for i, price in enumerate(prices):
            event = MarketEvent(
                timestamp=datetime(2024, 1, i + 1),
                symbol=Symbol("600519"),
                open=Decimal(str(price)),
                high=Decimal(str(price + 2)),
                low=Decimal(str(price - 2)),
                close=Decimal(str(price)),
                volume=Decimal("10000"),
            )
            strategy.on_data(event)

        bus.drain()
        # 应有金叉信号
        assert len(signals) >= 1
        buy_signals = [s for s in signals if s.target_weight == Decimal("1")]
        assert len(buy_signals) >= 1


class TestMonthlyRebalanceStrategy:
    def test_monthly_signal(self):
        bus = EventBus()
        target_weights = {Symbol("600519"): 0.6}
        strategy = MonthlyRebalanceStrategy(bus, target_weights=target_weights)
        strategy.on_init([Symbol("600519")])

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # 1 月第一个交易日
        event1 = MarketEvent(
            timestamp=datetime(2024, 1, 2),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        strategy.on_data(event1)
        bus.drain()
        assert len(signals) == 1
        assert signals[0].target_weight == Decimal("0.6")

        # 1 月后续交易日不再触发
        event2 = MarketEvent(
            timestamp=datetime(2024, 1, 3),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        strategy.on_data(event2)
        bus.drain()
        assert len(signals) == 1  # 仍然只有 1 个信号

        # 2 月第一个交易日再触发
        event3 = MarketEvent(
            timestamp=datetime(2024, 2, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        strategy.on_data(event3)
        bus.drain()
        assert len(signals) == 2
