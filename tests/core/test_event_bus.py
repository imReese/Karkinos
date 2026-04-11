"""EventBus 单元测试。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import Event, FillEvent, MarketEvent, OrderEvent, SignalEvent
from core.types import BarFrequency, OrderSide, OrderType, Symbol


class TestEventBusSubscribe:
    """订阅相关测试。"""

    def test_subscribe_and_publish(self):
        bus = EventBus()
        received: list[MarketEvent] = []

        bus.subscribe(MarketEvent, received.append)

        event = MarketEvent(
            timestamp=datetime(2024, 1, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        bus.publish(event)
        bus.drain()

        assert len(received) == 1
        assert received[0].symbol == Symbol("600519")
        assert received[0].close == Decimal("1830")

    def test_multiple_subscribers(self):
        bus = EventBus()
        received_a: list[Event] = []
        received_b: list[Event] = []

        bus.subscribe(MarketEvent, received_a.append)
        bus.subscribe(MarketEvent, received_b.append)

        event = MarketEvent(
            timestamp=datetime(2024, 1, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        bus.publish(event)
        bus.drain()

        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_unsubscribe(self):
        bus = EventBus()
        received: list[Event] = []

        bus.subscribe(MarketEvent, received.append)
        bus.unsubscribe(MarketEvent, received.append)

        event = MarketEvent(
            timestamp=datetime(2024, 1, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        bus.publish(event)
        bus.drain()

        assert len(received) == 0


class TestEventBusPriority:
    """优先级排序测试。"""

    def test_priority_order(self):
        """priority 越小越先执行。"""
        bus = EventBus()
        order: list[str] = []

        bus.subscribe(MarketEvent, lambda e: order.append("second"), priority=10)
        bus.subscribe(MarketEvent, lambda e: order.append("first"), priority=-10)
        bus.subscribe(MarketEvent, lambda e: order.append("third"), priority=0)

        event = MarketEvent(
            timestamp=datetime(2024, 1, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        bus.publish(event)
        bus.drain()

        assert order == ["first", "third", "second"]

    def test_risk_manager_intercepts_before_execution(self):
        """风控（priority=-10）在执行（priority=0）之前运行。"""
        bus = EventBus()
        intercepted: list[str] = []

        def risk_check(event: OrderEvent) -> None:
            intercepted.append("risk")

        def execute(event: OrderEvent) -> None:
            intercepted.append("execution")

        bus.subscribe(OrderEvent, risk_check, priority=-10)
        bus.subscribe(OrderEvent, execute, priority=0)

        order = OrderEvent(
            timestamp=datetime(2024, 1, 1),
            order_id="ORD001",
            symbol=Symbol("600519"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
        )
        bus.publish(order)
        bus.drain()

        assert intercepted == ["risk", "execution"]


class TestEventBusDrain:
    """drain 测试。"""

    def test_drain_processes_all_queued(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(MarketEvent, received.append)

        for i in range(5):
            bus.publish(
                MarketEvent(
                    timestamp=datetime(2024, 1, i + 1),
                    symbol=Symbol("600519"),
                    open=Decimal("1800"),
                    high=Decimal("1850"),
                    low=Decimal("1790"),
                    close=Decimal("1830"),
                    volume=Decimal("10000"),
                )
            )

        count = bus.drain()
        assert count == 5
        assert len(received) == 5
        assert bus.queue_size == 0

    def test_drain_handles_cascading_events(self):
        """处理过程中新发布的事件也被处理。"""
        bus = EventBus()
        received: list[Event] = []

        def on_signal(event: SignalEvent) -> None:
            # 策略发信号后，组合发订单
            bus.publish(
                OrderEvent(
                    timestamp=event.timestamp,
                    order_id="ORD001",
                    symbol=event.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                )
            )

        bus.subscribe(SignalEvent, on_signal)
        bus.subscribe(OrderEvent, received.append)

        bus.publish(
            SignalEvent(
                timestamp=datetime(2024, 1, 1),
                strategy_id="dual_ma",
                symbol=Symbol("600519"),
                target_weight=Decimal("0.3"),
            )
        )
        bus.drain()

        assert len(received) == 1
        assert received[0].symbol == Symbol("600519")

    def test_publish_and_process_immediate(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(MarketEvent, received.append)

        event = MarketEvent(
            timestamp=datetime(2024, 1, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        bus.publish_and_process(event)

        assert len(received) == 1
        assert bus.queue_size == 0

    def test_clear(self):
        bus = EventBus()
        bus.subscribe(MarketEvent, lambda e: None)
        bus.publish(
            MarketEvent(
                timestamp=datetime(2024, 1, 1),
                symbol=Symbol("600519"),
                open=Decimal("1800"),
                high=Decimal("1850"),
                low=Decimal("1790"),
                close=Decimal("1830"),
                volume=Decimal("10000"),
            )
        )
        bus.clear()
        assert bus.queue_size == 0


class TestEventBusBaseClassMatching:
    """基类匹配测试：订阅 Event 基类应能接收所有事件。"""

    def test_base_event_catches_all(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(Event, received.append)

        market = MarketEvent(
            timestamp=datetime(2024, 1, 1),
            symbol=Symbol("600519"),
            open=Decimal("1800"),
            high=Decimal("1850"),
            low=Decimal("1790"),
            close=Decimal("1830"),
            volume=Decimal("10000"),
        )
        signal = SignalEvent(
            timestamp=datetime(2024, 1, 1),
            strategy_id="test",
            symbol=Symbol("600519"),
            target_weight=Decimal("0.5"),
        )
        bus.publish(market)
        bus.publish(signal)
        bus.drain()

        assert len(received) == 2
