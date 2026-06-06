"""Execution order tracker tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import FillEvent
from core.types import AssetClass, OrderSide, Symbol
from execution.tracker import BrokerFillReport, ExecutionOrderTracker
from server.db import AppDatabase


def test_execution_order_tracker_persists_fill_and_publishes_event(tmp_path) -> None:
    bus = EventBus()
    received: list[FillEvent] = []
    bus.subscribe(FillEvent, received.append)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    tracker = ExecutionOrderTracker(event_bus=bus, db=db)

    fill = tracker.record_fill(
        BrokerFillReport(
            fill_id="FILL-1",
            order_id="ORD-1",
            timestamp=datetime(2026, 4, 18, 14, 50, 3),
            symbol=Symbol("600519"),
            side=OrderSide.BUY,
            fill_price=Decimal("123.46"),
            fill_quantity=Decimal("100"),
            commission=Decimal("5.0"),
            slippage=Decimal("1.0"),
            asset_class=AssetClass.STOCK,
            execution_mode="paper",
            provider_name="simulated",
            broker_order_id="SIM-ORD-1",
            source="simulated_execution",
            source_ref="SIM-FILL-1",
            metadata={"latency_ms": 12},
        )
    )

    bus.drain()
    saved = db.get_fill_sync("FILL-1")

    assert fill.fill_id == "FILL-1"
    assert fill.order_id == "ORD-1"
    assert fill.symbol == Symbol("600519")
    assert fill.side == OrderSide.BUY
    assert fill.fill_price == Decimal("123.46")
    assert fill.fill_quantity == Decimal("100")
    assert fill.commission == Decimal("5.0")
    assert fill.slippage == Decimal("1.0")
    assert received == [fill]
    assert saved is not None
    assert saved["fill_id"] == "FILL-1"
    assert saved["provider_name"] == "simulated"
    assert saved["broker_order_id"] == "SIM-ORD-1"
