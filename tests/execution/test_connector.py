"""Execution connector tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import FillEvent, OrderEvent
from core.types import OrderSide, OrderType, Symbol
from execution.connector import PaperExecutionConnector
from server.db import AppDatabase


def test_paper_execution_connector_records_order_fill_and_publishes_fill(
    tmp_path,
) -> None:
    bus = EventBus()
    received: list[FillEvent] = []
    bus.subscribe(FillEvent, received.append)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    PaperExecutionConnector(event_bus=bus, db=db)

    order = OrderEvent(
        timestamp=datetime(2026, 4, 18, 14, 50),
        order_id="ORD-PAPER-1",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        price=Decimal("123.45"),
        intent_id="INTENT-1",
        risk_decision_id="RISK-1",
        execution_mode="paper",
    )

    bus.publish_and_process(order)
    bus.drain()

    saved_order = db.get_order_sync("ORD-PAPER-1")
    fills = db.list_fills_sync(order_id="ORD-PAPER-1")
    order_events = db.list_events_sync(entity_type="order", entity_id="ORD-PAPER-1")

    assert saved_order is not None
    assert saved_order["status"] == "filled"
    assert saved_order["execution_mode"] == "paper"
    assert saved_order["source"] == "paper_execution"
    assert saved_order["source_ref"] == "ORD-PAPER-1"
    assert len(fills) == 1
    assert fills[0]["source"] == "paper_execution"
    assert fills[0]["provider_name"] == "simulated"
    assert fills[0]["order_id"] == "ORD-PAPER-1"
    assert fills[0]["fill_quantity"] == 100.0
    assert fills[0]["fill_price"] == 123.45
    assert len(received) == 1
    assert received[0].order_id == "ORD-PAPER-1"
    assert received[0].fill_id == fills[0]["fill_id"]
    assert [event["event_type"] for event in order_events] == [
        "order.status_changed",
        "order.recorded",
    ]
