"""Portfolio order intent behavior."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import OrderEvent, OrderIntentEvent, SignalEvent
from core.types import Symbol
from domain.instrument import make_stock
from domain.portfolio import Portfolio


def test_signal_emits_order_intent_not_order_event() -> None:
    bus = EventBus()
    symbol = Symbol("600519")
    intents: list[OrderIntentEvent] = []
    orders: list[OrderEvent] = []

    portfolio = Portfolio(bus, initial_cash=Decimal("100000"))
    portfolio.add_instrument(make_stock("600519", "贵州茅台"))
    bus.subscribe(OrderIntentEvent, intents.append)
    bus.subscribe(OrderEvent, orders.append)

    bus.publish_and_process(
        SignalEvent(
            timestamp=datetime(2024, 1, 2, 14, 50),
            strategy_id="unit_test",
            symbol=symbol,
            target_weight=Decimal("0.50"),
            price=Decimal("100"),
        )
    )
    bus.drain()

    assert len(intents) == 1
    assert orders == []
    intent = intents[0]
    assert intent.strategy_id == "unit_test"
    assert intent.symbol == symbol
    assert intent.target_weight == Decimal("0.50")
    assert intent.quantity == Decimal("500")
    assert intent.reference_price == Decimal("100")
