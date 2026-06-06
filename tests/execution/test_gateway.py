"""Manual confirmation gateway tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import OrderEvent
from core.types import OrderSide, OrderType, Symbol
from execution.gateway import ManualConfirmGateway
from server.db import AppDatabase


def test_manual_confirm_gateway_persists_pending_manual_order(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    gateway = ManualConfirmGateway(bus, db=db)

    order = OrderEvent(
        timestamp=datetime(2026, 4, 18, 14, 50),
        order_id="ORD-1",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        price=Decimal("123.45"),
        intent_id="INTENT-1",
        risk_decision_id="RISK-1",
        execution_mode="manual",
    )

    bus.publish_and_process(order)

    pending = db.get_manual_order_sync("ORD-1")
    recorded = db.get_order_sync("ORD-1")
    assert pending is not None
    assert pending["status"] == gateway.PENDING_CONFIRM
    assert pending["symbol"] == "600519"
    assert recorded is not None
    assert recorded["status"] == gateway.PENDING_CONFIRM
    assert recorded["source"] == "manual_orders"
    assert recorded["source_ref"] == "ORD-1"

    gateway.confirm_order("ORD-1")

    assert db.get_manual_order_sync("ORD-1")["status"] == "confirmed"
    assert db.get_order_sync("ORD-1")["status"] == "confirmed"


def test_manual_confirm_gateway_reject_updates_shared_order_status(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    gateway = ManualConfirmGateway(bus, db=db)

    order = OrderEvent(
        timestamp=datetime(2026, 4, 18, 14, 51),
        order_id="ORD-REJECT",
        symbol=Symbol("600519"),
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("50"),
        price=Decimal("125.00"),
        intent_id="INTENT-2",
        risk_decision_id="RISK-2",
        execution_mode="manual",
    )

    bus.publish_and_process(order)
    gateway.reject_order("ORD-REJECT", "operator rejected")

    assert db.get_manual_order_sync("ORD-REJECT")["status"] == "rejected"
    assert db.get_order_sync("ORD-REJECT")["status"] == "rejected"


def test_manual_confirm_gateway_ignores_non_manual_order(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    ManualConfirmGateway(bus, db=db)

    order = OrderEvent(
        timestamp=datetime(2026, 4, 18, 14, 50),
        order_id="ORD-1",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        price=Decimal("123.45"),
        execution_mode="paper",
    )

    bus.publish_and_process(order)

    assert db.get_manual_order_sync("ORD-1") is None
    assert db.get_order_sync("ORD-1") is None
