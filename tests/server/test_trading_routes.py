"""Trading control route tests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from core.events import OrderIntentEvent, RiskDecisionEvent
from core.types import OrderSide, Symbol
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


def _seed_action_task_with_risk(
    db: AppDatabase,
    *,
    passed: bool | None,
    signal_id: int = 1,
    symbol: str = "510300",
    price: float = 4.56,
) -> int:
    db.save_signal_sync(
        timestamp="2026-04-18T09:30:00",
        strategy_id="dual_ma",
        symbol=symbol,
        direction="buy",
        target_weight=0.2,
        price=price,
        asset_class="fund",
    )
    db.upsert_action_task_sync(
        source_signal_id=signal_id,
        symbol=symbol,
        title=f"建议增持 {symbol}",
        detail="dual_ma 触发，目标仓位 20%",
        direction="buy",
        urgency="high",
        target_weight=0.2,
        price=price,
        strategy_id="dual_ma",
        timestamp="2026-04-18T09:30:00",
        asset_class="fund",
    )
    if passed is not None:
        intent = OrderIntentEvent(
            timestamp=datetime(2026, 4, 18, 14, 50),
            intent_id=f"INTENT-{'PASSED' if passed else 'BLOCKED'}",
            strategy_id="dual_ma",
            symbol=Symbol(symbol),
            side=OrderSide.BUY,
            target_weight=Decimal("0.20"),
            quantity=Decimal("1000"),
            reference_price=Decimal(str(price)),
            source_signal_id=str(signal_id),
            reason="manual order route test",
        )
        db.save_risk_decision_sync(
            intent=intent,
            decision=RiskDecisionEvent(
                timestamp=intent.timestamp,
                decision_id=f"RISK-{'PASSED' if passed else 'BLOCKED'}",
                intent_id=intent.intent_id,
                passed=passed,
                symbol=intent.symbol,
                side=intent.side,
                reasons=[] if passed else ["max position weight exceeded"],
                severity="info" if passed else "warning",
            ),
        )
    return db.get_action_tasks_sync()[0]["id"]


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


def test_create_manual_order_from_risk_passed_action(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    action_id = _seed_action_task_with_risk(db, passed=True)
    broadcasts: list[dict] = []
    fake_state = SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(),
        hub=SimpleNamespace(broadcast=lambda data: broadcasts.append(data)),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    endpoint = _endpoint(
        "/api/trading/actions/{action_id}/manual-order",
        method="POST",
    )

    created = asyncio.run(
        endpoint(
            action_id,
            trading_routes.ActionManualOrderRequest(quantity=1000),
        )
    )

    order_id = f"ACTION-{action_id}-MANUAL"
    manual_order = db.get_manual_order_sync(order_id)
    order_fact = db.get_order_sync(order_id)
    action = db.get_action_tasks_sync(statuses=["pending_manual_confirmation"])[0]

    assert created["order_id"] == order_id
    assert created["status"] == "pending_confirm"
    assert manual_order["execution_mode"] == "manual"
    assert manual_order["risk_decision_id"] == "RISK-PASSED"
    assert order_fact["status"] == "pending_confirm"
    assert order_fact["source"] == "manual_action"
    assert order_fact["risk_decision_id"] == "RISK-PASSED"
    assert action["id"] == action_id
    assert action["manual_confirmation_status"] == "ready_for_manual_confirmation"
    assert broadcasts[-1]["event_type"] == "ManualOrderPrepared"


@pytest.mark.parametrize(
    ("passed", "expected_status"),
    [
        (False, "blocked_by_risk_gate"),
        (None, "awaiting_risk_gate"),
    ],
)
def test_create_manual_order_rejects_actions_not_ready_for_manual_confirmation(
    monkeypatch,
    tmp_path,
    passed,
    expected_status,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    action_id = _seed_action_task_with_risk(db, passed=passed)
    fake_state = SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    endpoint = _endpoint(
        "/api/trading/actions/{action_id}/manual-order",
        method="POST",
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            endpoint(
                action_id,
                trading_routes.ActionManualOrderRequest(quantity=1000),
            )
        )

    assert exc.value.status_code == 409
    assert expected_status in exc.value.detail
    assert db.list_manual_orders_sync() == []
    assert db.list_orders_sync() == []


@pytest.mark.parametrize(
    (
        "method_path",
        "method",
        "payload",
        "expected_action_status",
        "expected_order_status",
    ),
    [
        (
            "/api/trading/orders/{order_id}/confirm",
            "POST",
            None,
            "acted",
            "confirmed",
        ),
        (
            "/api/trading/orders/{order_id}/reject",
            "POST",
            trading_routes.OrderRejectRequest(reason="operator skipped"),
            "ignored",
            "rejected",
        ),
    ],
)
def test_manual_order_decisions_update_action_status_and_signal_journal(
    monkeypatch,
    tmp_path,
    method_path,
    method,
    payload,
    expected_action_status,
    expected_order_status,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    action_id = _seed_action_task_with_risk(db, passed=True)
    fake_state = SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    create_endpoint = _endpoint(
        "/api/trading/actions/{action_id}/manual-order",
        method="POST",
    )
    asyncio.run(
        create_endpoint(
            action_id,
            trading_routes.ActionManualOrderRequest(quantity=1000),
        )
    )
    order_id = f"ACTION-{action_id}-MANUAL"
    decision_endpoint = _endpoint(method_path, method=method)

    if payload is None:
        updated = asyncio.run(decision_endpoint(order_id))
    else:
        updated = asyncio.run(decision_endpoint(order_id, payload))
    journal_entry = db.list_signal_journal_sync()[0]

    assert updated["status"] == expected_order_status
    assert journal_entry["action_task"]["status"] == expected_action_status
    assert journal_entry["latest_event"]["event_type"] == "order.status_changed"
    assert journal_entry["latest_event"]["source"] == "manual_orders"
    assert journal_entry["latest_event"]["payload"]["status"] == expected_order_status
    assert journal_entry["latest_event"]["payload"]["payload"]["action_id"] == action_id
    assert (
        journal_entry["latest_event"]["payload"]["payload"]["source_signal_id"]
        == journal_entry["signal"]["id"]
    )


def test_daily_shadow_run_records_only_risk_passed_actions_without_manual_orders(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    passed_action_id = _seed_action_task_with_risk(db, passed=True)
    blocked_action_id = _seed_action_task_with_risk(
        db,
        passed=False,
        signal_id=2,
        symbol="600519",
        price=12.5,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=100000),
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
        scheduler=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    endpoint = _endpoint("/api/trading/shadow-runs/daily", method="POST")

    response = asyncio.run(
        endpoint(trading_routes.ShadowRunRequest(run_date="2026-04-19"))
    )
    orders = db.list_orders_sync()
    actions_by_id = {task["id"]: task for task in db.get_action_tasks_sync()}

    assert response["run_id"] == "shadow:2026-04-19"
    assert response["processed_count"] == 1
    assert response["skipped_count"] == 1
    assert response["orders"][0]["source_action_id"] == passed_action_id
    assert response["orders"][0]["order_id"] == f"SHADOW-2026-04-19-{passed_action_id}"
    assert orders[0]["order_id"] == f"SHADOW-2026-04-19-{passed_action_id}"
    assert orders[0]["execution_mode"] == "paper_shadow"
    assert orders[0]["source"] == "paper_shadow_daily"
    assert orders[0]["status"] == "shadow_recorded"
    assert orders[0]["quantity"] == pytest.approx(4385.0)
    assert db.list_manual_orders_sync() == []
    assert actions_by_id[passed_action_id]["status"] == "pending"
    assert actions_by_id[blocked_action_id]["risk_gate_status"] == "blocked"


def test_shadow_order_divergence_review_updates_order_payload_without_execution(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    passed_action_id = _seed_action_task_with_risk(db, passed=True)
    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=100000),
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
        scheduler=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    run_endpoint = _endpoint("/api/trading/shadow-runs/daily", method="POST")
    review_endpoint = _endpoint(
        "/api/trading/order-facts/{order_id}/shadow-divergence-review",
        method="POST",
    )
    asyncio.run(run_endpoint(trading_routes.ShadowRunRequest(run_date="2026-04-19")))
    order_id = f"SHADOW-2026-04-19-{passed_action_id}"

    reviewed = asyncio.run(
        review_endpoint(
            order_id,
            trading_routes.ShadowDivergenceReviewRequest(
                reviewed_at="2026-04-20T16:00:00",
                divergence_status="within_expectations",
                review_notes="Shadow quantity and target weight matched backtest expectations.",
                reviewer="operator",
            ),
        )
    )
    order = db.get_order_sync(order_id)
    orders = db.list_orders_sync()
    fills = db.list_fills_sync(order_id=order_id)

    payload = json.loads(order["payload_json"])
    assert reviewed["order_id"] == order_id
    assert reviewed["execution_mode"] == "paper_shadow"
    assert reviewed["status"] == "shadow_recorded"
    assert payload["divergence_status"] == "within_expectations"
    assert payload["divergence_reviewed_at"] == "2026-04-20T16:00:00"
    assert payload["divergence_review_notes"].startswith("Shadow quantity")
    assert payload["divergence_reviewer"] == "operator"
    assert payload["strategy_id"] == "dual_ma"
    assert orders[0]["status"] == "shadow_recorded"
    assert fills == []


def test_shadow_order_divergence_review_rejects_non_shadow_order(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.record_order_sync(
        order_id="ORD-MANUAL-1",
        timestamp="2026-04-18T14:50:00",
        symbol="510300",
        side="buy",
        order_type="market",
        quantity=100.0,
        price=4.56,
        execution_mode="manual",
        status="pending_confirm",
        source="manual_action",
        source_ref="1",
        payload={"strategy_id": "dual_ma"},
    )
    fake_state = SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    endpoint = _endpoint(
        "/api/trading/order-facts/{order_id}/shadow-divergence-review",
        method="POST",
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            endpoint(
                "ORD-MANUAL-1",
                trading_routes.ShadowDivergenceReviewRequest(
                    reviewed_at="2026-04-20T16:00:00",
                    divergence_status="within_expectations",
                    review_notes="Should not attach shadow review to manual order.",
                ),
            )
        )

    order = db.get_order_sync("ORD-MANUAL-1")
    payload = json.loads(order["payload_json"])
    assert exc.value.status_code == 409
    assert "divergence_status" not in payload


def test_trading_routes_list_shared_order_and_fill_facts(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.record_order_sync(
        order_id="ORD-PAPER-1",
        timestamp="2026-04-18T14:50:00",
        symbol="600519",
        side="buy",
        order_type="market",
        quantity=100.0,
        price=123.45,
        execution_mode="paper",
        status="filled",
        source="paper_execution",
        source_ref="ORD-PAPER-1",
        payload={"order_id": "ORD-PAPER-1"},
    )
    db.record_fill_sync(
        fill_id="FILL-PAPER-1",
        order_id="ORD-PAPER-1",
        timestamp="2026-04-18T14:50:03",
        symbol="600519",
        side="buy",
        fill_price=123.45,
        fill_quantity=100.0,
        execution_mode="paper",
        provider_name="simulated",
        source="paper_execution",
        source_ref="FILL-PAPER-1",
    )
    fake_state = SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    orders_endpoint = _endpoint("/api/trading/order-facts")
    fills_endpoint = _endpoint("/api/trading/fills")

    orders = asyncio.run(orders_endpoint(status="filled", symbol=None))
    fills = asyncio.run(fills_endpoint(order_id="ORD-PAPER-1", symbol=None))

    assert len(orders) == 1
    assert orders[0]["order_id"] == "ORD-PAPER-1"
    assert orders[0]["source"] == "paper_execution"
    assert len(fills) == 1
    assert fills[0]["fill_id"] == "FILL-PAPER-1"
    assert fills[0]["provider_name"] == "simulated"
