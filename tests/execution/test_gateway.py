"""Manual confirmation gateway tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import OrderEvent, OrderIntentEvent, RiskDecisionEvent
from core.types import AssetClass, OrderSide, OrderType, Symbol
from execution.gateway import ManualConfirmGateway
from server.db import AppDatabase
from server.services.manual_order_tickets import RuntimeManualOrderTicketAdapter


def _gateway(bus: EventBus, db: AppDatabase) -> ManualConfirmGateway:
    return ManualConfirmGateway(
        bus,
        ticket_port=RuntimeManualOrderTicketAdapter(persistence=db),
    )


def _persist_approved_risk_decision(db: AppDatabase, order: OrderEvent) -> None:
    intent = OrderIntentEvent(
        timestamp=order.timestamp,
        intent_id=str(order.intent_id),
        strategy_id="gateway-test",
        symbol=order.symbol,
        side=order.side,
        target_weight=Decimal("0.10"),
        quantity=order.quantity,
        reference_price=order.price or Decimal("1"),
        asset_class=order.asset_class,
    )
    decision = RiskDecisionEvent(
        timestamp=order.timestamp,
        decision_id=str(order.risk_decision_id),
        intent_id=str(order.intent_id),
        passed=True,
        symbol=order.symbol,
        side=order.side,
        reasons=["approved"],
        resulting_order_id=order.order_id,
    )
    db.save_risk_decision_sync(intent=intent, decision=decision)


def test_manual_confirm_gateway_persists_pending_manual_order(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    gateway = _gateway(bus, db)

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
        asset_class=AssetClass.STOCK,
    )
    _persist_approved_risk_decision(db, order)

    bus.publish_and_process(order)
    bus.publish_and_process(order)

    pending = db.get_manual_order_sync("ORD-1")
    recorded = db.get_order_sync("ORD-1")
    assert pending is not None
    assert pending["status"] == gateway.PENDING_CONFIRM
    assert pending["symbol"] == "600519"
    assert recorded is not None
    assert recorded["status"] == gateway.PENDING_CONFIRM
    assert recorded["source"] == "risk_gate"
    assert recorded["source_ref"] == "RISK-1"

    assert gateway.confirm_order("ORD-1") is None

    assert db.get_manual_order_sync("ORD-1")["status"] == "pending_confirm"
    assert db.get_order_sync("ORD-1")["status"] == "pending_confirm"


def test_manual_confirm_gateway_reject_updates_shared_order_status(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    gateway = _gateway(bus, db)

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
        asset_class=AssetClass.STOCK,
    )
    _persist_approved_risk_decision(db, order)

    bus.publish_and_process(order)
    gateway.reject_order("ORD-REJECT", "operator rejected")

    assert db.get_manual_order_sync("ORD-REJECT")["status"] == "rejected"
    assert db.get_order_sync("ORD-REJECT")["status"] == "rejected"


def test_manual_confirm_gateway_fault_rolls_back_both_order_projections(
    tmp_path,
) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    gateway = _gateway(bus, db)
    order = OrderEvent(
        timestamp=datetime(2026, 4, 18, 14, 52),
        order_id="ORD-FAULT",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        price=Decimal("123.45"),
        intent_id="INTENT-FAULT",
        risk_decision_id="RISK-FAULT",
        execution_mode="manual",
        asset_class=AssetClass.STOCK,
    )
    _persist_approved_risk_decision(db, order)
    with sqlite3.connect(db.path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_runtime_manual_order_event
            BEFORE INSERT ON event_log
            WHEN NEW.event_type = 'order.recorded'
            BEGIN
                SELECT RAISE(ABORT, 'injected runtime manual order failure');
            END
            """)
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        gateway.on_order(order)

    assert db.get_manual_order_sync(order.order_id) is None
    assert db.get_order_sync(order.order_id) is None
    with sqlite3.connect(db.path) as conn:
        claim_count = conn.execute(
            "SELECT COUNT(*) FROM order_state_command_claims"
        ).fetchone()[0]
    assert claim_count == 0


def test_manual_confirm_gateway_rejects_unpersisted_risk_binding(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    gateway = _gateway(bus, db)
    order = OrderEvent(
        timestamp=datetime(2026, 4, 18, 14, 53),
        order_id="ORD-NO-RISK",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
        price=Decimal("123.45"),
        intent_id="INTENT-NO-RISK",
        risk_decision_id="RISK-NO-RISK",
        execution_mode="manual",
        asset_class=AssetClass.STOCK,
    )

    with pytest.raises(KeyError, match="risk decision not found"):
        gateway.on_order(order)

    assert db.get_manual_order_sync(order.order_id) is None
    assert db.get_order_sync(order.order_id) is None


def test_manual_confirm_gateway_ignores_non_manual_order(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _gateway(bus, db)

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
