"""Trading control route tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.routes import trading as trading_routes
from server.db import AppDatabase
from server.services.trading_controls import TradingControlState


def _endpoint(path: str, method: str = "GET"):
    router = trading_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_kill_switch_routes_read_and_update_state(monkeypatch) -> None:
    controls = TradingControlState()
    hub = SimpleNamespace(broadcast=lambda data: None)
    fake_state = SimpleNamespace(trading_controls=controls, hub=hub)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    get_endpoint = _endpoint("/api/trading/kill-switch")
    put_endpoint = _endpoint("/api/trading/kill-switch", method="PUT")

    initial = asyncio.run(get_endpoint())
    assert initial.kill_switch_enabled is False

    updated = asyncio.run(
        put_endpoint(
            trading_routes.KillSwitchRequest(
                enabled=True,
                reason="operator stop",
            )
        )
    )

    assert updated.kill_switch_enabled is True
    assert updated.reason == "operator stop"


def test_manual_order_routes_confirm_and_reject(monkeypatch, tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.record_order_sync(
        order_id="ORD-CONFIRM",
        timestamp="2026-04-18T14:50:00",
        symbol="600519",
        side="buy",
        order_type="market",
        quantity=100.0,
        price=123.45,
        intent_id="INTENT-1",
        risk_decision_id="RISK-1",
        execution_mode="manual",
        status="pending_confirm",
        source="manual_orders",
        source_ref="ORD-CONFIRM",
        payload={"order_id": "ORD-CONFIRM"},
    )
    db.save_manual_order_sync(
        order_id="ORD-CONFIRM",
        timestamp="2026-04-18T14:50:00",
        symbol="600519",
        side="buy",
        order_type="market",
        quantity=100.0,
        price=123.45,
        intent_id="INTENT-1",
        risk_decision_id="RISK-1",
        execution_mode="manual",
        status="pending_confirm",
        payload={"order_id": "ORD-CONFIRM"},
    )
    db.record_order_sync(
        order_id="ORD-REJECT",
        timestamp="2026-04-18T14:51:00",
        symbol="600519",
        side="buy",
        order_type="market",
        quantity=100.0,
        price=123.45,
        intent_id="INTENT-2",
        risk_decision_id="RISK-2",
        execution_mode="manual",
        status="pending_confirm",
        source="manual_orders",
        source_ref="ORD-REJECT",
        payload={"order_id": "ORD-REJECT"},
    )
    db.save_manual_order_sync(
        order_id="ORD-REJECT",
        timestamp="2026-04-18T14:51:00",
        symbol="600519",
        side="buy",
        order_type="market",
        quantity=100.0,
        price=123.45,
        intent_id="INTENT-2",
        risk_decision_id="RISK-2",
        execution_mode="manual",
        status="pending_confirm",
        payload={"order_id": "ORD-REJECT"},
    )
    fake_state = SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(),
        hub=SimpleNamespace(broadcast=lambda data: None),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    confirm_endpoint = _endpoint(
        "/api/trading/orders/{order_id}/confirm",
        method="POST",
    )
    reject_endpoint = _endpoint(
        "/api/trading/orders/{order_id}/reject",
        method="POST",
    )

    confirmed = asyncio.run(confirm_endpoint("ORD-CONFIRM"))
    rejected = asyncio.run(
        reject_endpoint(
            "ORD-REJECT",
            trading_routes.OrderRejectRequest(reason="operator rejected"),
        )
    )

    assert confirmed["status"] == "confirmed"
    assert rejected["status"] == "rejected"
    assert db.get_manual_order_sync("ORD-CONFIRM")["status"] == "confirmed"
    assert db.get_manual_order_sync("ORD-REJECT")["status"] == "rejected"
    assert db.get_order_sync("ORD-CONFIRM")["status"] == "confirmed"
    assert db.get_order_sync("ORD-REJECT")["status"] == "rejected"
