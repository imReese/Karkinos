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
from server.db import AppDatabase
from server.routes import trading as trading_routes
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


def _current_account_truth_fixture() -> dict:
    return {
        "gate_status": "pass",
        "data_freshness_status": "fresh",
        "unresolved_mismatch_count": 0,
        "import_run_id": "import-7",
        "source_fingerprint": "c" * 64,
        "captured_at": "2026-08-13T09:20:00+08:00",
        "ledger_coverage": {"status": "covered"},
        "blocking_reasons": [],
    }


def _current_market_fixture(*, status: str = "live", price: float = 4.56) -> dict:
    return {
        "status": status,
        "price": price,
        "quote_timestamp": "2026-08-13T09:25:00+08:00",
        "quote_source": "fixture",
    }


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


def _seed_live_quote(
    db: AppDatabase,
    *,
    symbol: str = "510300",
    asset_type: str = "fund",
    price: float = 4.56,
) -> None:
    db.upsert_latest_quote_sync(
        symbol=symbol,
        asset_type=asset_type,
        price=price,
        volume=1000.0,
        quote_timestamp="2026-04-19T14:50:00+08:00",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="ok",
        quote_status="live",
        captured_at="2026-04-19T14:50:01+08:00",
        captured_reason="shadow_quality_fixture",
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


def test_manual_order_confirmation_blocks_unlinked_legacy_order_but_rejects_safely(
    monkeypatch,
    tmp_path,
) -> None:
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

    with pytest.raises(HTTPException) as exc:
        asyncio.run(confirm_endpoint("ORD-CONFIRM"))
    rejected = asyncio.run(
        reject_endpoint(
            "ORD-REJECT",
            trading_routes.OrderRejectRequest(reason="operator rejected"),
        )
    )

    assert exc.value.status_code == 409
    assert "canonical decision action evidence is missing" in exc.value.detail
    assert rejected["status"] == "rejected"
    assert db.get_manual_order_sync("ORD-CONFIRM")["status"] == "pending_confirm"
    assert db.get_manual_order_sync("ORD-REJECT")["status"] == "rejected"
    assert db.get_order_sync("ORD-CONFIRM")["status"] == "pending_confirm"
    assert db.get_order_sync("ORD-REJECT")["status"] == "rejected"


def test_create_manual_order_blocks_risk_passed_action_without_promotion_evidence(
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

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            endpoint(
                action_id,
                trading_routes.ActionManualOrderRequest(quantity=1000),
            )
        )

    assert exc.value.status_code == 409
    assert "strategy_promotion_evidence_missing" in exc.value.detail
    assert db.list_manual_orders_sync() == []
    assert db.list_orders_sync() == []
    assert broadcasts == []


def test_create_manual_order_writes_only_after_current_gate_passes(
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
    monkeypatch.setattr(
        trading_routes,
        "_current_action_manual_ticket_gate",
        lambda state, action, **kwargs: {
            "status": "pass",
            "does_not_authorize_execution": True,
            "broker_submission_enabled": False,
        },
    )
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
    order_payload = json.loads(order_fact["payload_json"])

    assert created["order_id"] == order_id
    assert created["status"] == "pending_confirm"
    assert manual_order["execution_mode"] == "manual"
    assert manual_order["risk_decision_id"] == "RISK-PASSED"
    assert order_fact["source"] == "manual_action"
    assert order_payload["current_action_manual_ticket_gate"]["status"] == "pass"
    assert action["id"] == action_id
    assert broadcasts[-1]["event_type"] == "ManualOrderPrepared"


@pytest.mark.parametrize(
    ("market_status", "kill_switch_enabled", "expected_blocker"),
    [
        ("stale", False, "current_market_data_not_trusted"),
        ("live", True, "current_kill_switch_enabled"),
    ],
)
def test_current_manual_ticket_gate_rechecks_market_data_and_kill_switch(
    monkeypatch,
    market_status,
    kill_switch_enabled,
    expected_blocker,
) -> None:
    controls = TradingControlState()
    if kill_switch_enabled:
        controls.set_kill_switch(True, "operator stop")
    state = SimpleNamespace(db=object(), trading_controls=controls)
    action = {
        "id": 7,
        "strategy_id": "ai_formula_shadow:fixture",
        "timestamp": "2026-08-13T09:30:00+08:00",
        "risk_gate_status": "passed",
        "manual_confirmation_status": "ready_for_manual_confirmation",
    }
    monkeypatch.setattr(
        "server.routes.decision._account_truth_gate_evidence",
        lambda state: _current_account_truth_fixture(),
    )
    monkeypatch.setattr(
        "server.routes.decision._data_freshness_evidence",
        lambda action, db, *, quotes, allow_direct_quote_fallback: {
            **_current_market_fixture(status=market_status),
            "reason": "fixture_market_status",
        },
    )
    monkeypatch.setattr(
        "server.routes.decision._paper_shadow_evidence",
        lambda action, manual_status, *, db: {
            "status": "pass",
            "has_evidence": True,
            "run_id": "shadow:fixture",
            "input_fingerprint": "fixture-fingerprint",
            "order_id": "SHADOW-FIXTURE",
            "divergence_status": "within_expectations",
            "blocking_reasons": [],
        },
    )
    monkeypatch.setattr(
        "server.services.strategy_promotion_pipeline."
        "resolve_strategy_order_generation_gate",
        lambda db, strategy_id, *, as_of_date=None: (
            {"status": "pass", "strategy_id": strategy_id},
            [],
        ),
    )

    with pytest.raises(ValueError) as exc:
        trading_routes._current_action_manual_ticket_gate(state, action)

    assert expected_blocker in str(exc.value)


def test_current_manual_ticket_gate_requires_trading_control_state(monkeypatch) -> None:
    state = SimpleNamespace(db=object(), trading_controls=None)
    action = {
        "id": 7,
        "strategy_id": "ai_formula_shadow:fixture",
        "timestamp": "2026-08-13T09:30:00+08:00",
        "risk_gate_status": "passed",
        "manual_confirmation_status": "ready_for_manual_confirmation",
    }
    monkeypatch.setattr(
        "server.routes.decision._account_truth_gate_evidence",
        lambda state: _current_account_truth_fixture(),
    )
    monkeypatch.setattr(
        "server.routes.decision._data_freshness_evidence",
        lambda action, db, *, quotes, allow_direct_quote_fallback: (
            _current_market_fixture()
        ),
    )
    monkeypatch.setattr(
        "server.routes.decision._paper_shadow_evidence",
        lambda action, manual_status, *, db: {
            "status": "pass",
            "has_evidence": True,
            "run_id": "shadow:fixture",
            "input_fingerprint": "fixture-fingerprint",
            "order_id": "SHADOW-FIXTURE",
            "divergence_status": "within_expectations",
            "blocking_reasons": [],
        },
    )
    monkeypatch.setattr(
        "server.services.strategy_promotion_pipeline."
        "resolve_strategy_order_generation_gate",
        lambda db, strategy_id, *, as_of_date=None: (
            {"status": "pass", "strategy_id": strategy_id},
            [],
        ),
    )

    with pytest.raises(ValueError) as exc:
        trading_routes._current_action_manual_ticket_gate(state, action)

    assert "current_trading_controls_unavailable" in str(exc.value)


def test_current_manual_ticket_gate_binds_exact_simulated_order_terms(
    monkeypatch,
) -> None:
    strategy_id = "ai_formula_shadow:fixture"
    action = {
        "id": 7,
        "strategy_id": strategy_id,
        "timestamp": "2026-08-13T09:30:00+08:00",
        "risk_gate_status": "passed",
        "risk_decision_id": "RISK-7",
        "manual_confirmation_status": "ready_for_manual_confirmation",
    }
    state = SimpleNamespace(db=object(), trading_controls=TradingControlState())
    monkeypatch.setattr(
        "server.routes.decision._account_truth_gate_evidence",
        lambda state: _current_account_truth_fixture(),
    )
    monkeypatch.setattr(
        "server.routes.decision._data_freshness_evidence",
        lambda action, db, *, quotes, allow_direct_quote_fallback: (
            _current_market_fixture()
        ),
    )
    monkeypatch.setattr(
        "server.routes.decision._paper_shadow_evidence",
        lambda action, manual_status, *, db: {
            "status": "pass",
            "has_evidence": True,
            "run_id": "shadow:fixture",
            "input_fingerprint": "fixture-fingerprint",
            "order_id": "SHADOW-FIXTURE",
            "divergence_status": "within_expectations",
            "order_divergence_status": "within_expectations",
            "order_intent": {
                "action_ref": "action:7",
                "symbol": "510300",
                "side": "buy",
                "estimated_quantity": 1000,
                "estimated_price": 4.56,
                "strategy_refs": [f"strategy:{strategy_id}"],
                "strategy_advancement_refs": ["strategy_advancement:gate-7"],
                "risk_refs": ["risk:RISK-7"],
                "account_truth_refs": ["account_truth:import-7"],
            },
            "blocking_reasons": [],
        },
    )
    monkeypatch.setattr(
        "server.services.strategy_promotion_pipeline."
        "resolve_strategy_order_generation_gate",
        lambda db, strategy_id, *, as_of_date=None: (
            {
                "status": "pass",
                "strategy_id": strategy_id,
                "promotion": {
                    "strategy_advancement_gate_fingerprint": "gate-7",
                },
            },
            [],
        ),
    )

    gate = trading_routes._current_action_manual_ticket_gate(
        state,
        action,
        proposed_order={
            "symbol": "510300",
            "side": "buy",
            "quantity": 1000,
            "price": 4.56,
        },
    )

    assert gate["status"] == "pass"
    assert gate["does_not_authorize_execution"] is True

    with pytest.raises(ValueError) as exc:
        trading_routes._current_action_manual_ticket_gate(
            state,
            action,
            proposed_order={
                "symbol": "510300",
                "side": "buy",
                "quantity": 900,
                "price": 4.56,
            },
        )

    assert "paper_shadow_ticket_quantity_mismatch" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        trading_routes._current_action_manual_ticket_gate(
            state,
            action,
            proposed_order={
                "symbol": "510300",
                "side": "buy",
                "quantity": 1000,
                "price": 4.55,
            },
        )

    assert "proposed_order_price_not_bound_to_current_quote" in str(exc.value)

    monkeypatch.setattr(
        "server.services.strategy_promotion_pipeline."
        "resolve_strategy_order_generation_gate",
        lambda db, strategy_id, *, as_of_date=None: (
            {"status": "blocked", "strategy_id": strategy_id},
            [],
        ),
    )
    with pytest.raises(ValueError) as exc:
        trading_routes._current_action_manual_ticket_gate(
            state,
            action,
            proposed_order={
                "symbol": "510300",
                "side": "buy",
                "quantity": 1000,
                "price": 4.56,
            },
        )

    assert "current_strategy_order_generation_not_passing" in str(exc.value)


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
    monkeypatch.setattr(
        trading_routes,
        "_current_action_manual_ticket_gate",
        lambda state, action, **kwargs: {
            "status": "pass",
            "does_not_authorize_execution": True,
            "broker_submission_enabled": False,
        },
    )
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


def test_daily_shadow_route_delegates_to_canonical_decision_plan_and_service(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    calls: dict[str, object] = {}
    decision_payload = {
        "decision_date": "2026-04-19",
        "generated_at": "2026-04-19T14:50:00+08:00",
        "decision": "review_required",
    }
    trading_plan = {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-04-19",
        "generated_at": "2026-04-19T14:50:00+08:00",
        "order_intents": [],
    }
    canonical_result = {
        "run_id": "shadow:2026-04-19:canonical",
        "status": "no_action",
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }

    async def fake_today_decision(state, *, portfolio_context):
        calls["decision_context"] = portfolio_context
        return decision_payload

    def fake_build_plan(*, decision_payload, config, positions):
        calls["plan_inputs"] = (decision_payload, config, positions)
        return trading_plan

    def fake_run(*, db, trading_plan, generated_at):
        calls["paper_inputs"] = (db, trading_plan, generated_at)
        return canonical_result

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=100000),
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.decision._decision_portfolio_context",
        lambda state: {"source": "persisted_account_truth"},
    )
    monkeypatch.setattr(
        "server.routes.decision._today_decision_payload",
        fake_today_decision,
    )
    monkeypatch.setattr(
        "server.routes.decision._trading_plan_positions",
        lambda state, *, portfolio_context: {"600519": {"quantity": 100}},
    )
    monkeypatch.setattr(
        "server.services.daily_trading_plan.build_daily_trading_plan",
        fake_build_plan,
    )
    monkeypatch.setattr(
        "server.services.paper_shadow_run.run_paper_shadow_from_trading_plan",
        fake_run,
    )
    endpoint = _endpoint("/api/trading/shadow-runs/daily", method="POST")

    response = asyncio.run(
        endpoint(trading_routes.ShadowRunRequest(run_date="2026-04-19"))
    )

    assert response == canonical_result
    assert calls["decision_context"] == {"source": "persisted_account_truth"}
    assert calls["plan_inputs"][0] is decision_payload
    assert calls["paper_inputs"] == (
        db,
        trading_plan,
        "2026-04-19T14:50:00+08:00",
    )
    assert db.list_manual_orders_sync() == []
    assert db.list_orders_sync() == []


def test_daily_shadow_route_rejects_caller_supplied_equity(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(db=db, hub=None)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    endpoint = _endpoint("/api/trading/shadow-runs/daily", method="POST")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            endpoint(
                trading_routes.ShadowRunRequest(
                    run_date="2026-04-19",
                    base_equity=100000,
                )
            )
        )

    assert exc.value.status_code == 409
    assert "persisted Account Truth" in exc.value.detail
    assert db.list_orders_sync() == []


def test_shadow_order_divergence_review_updates_paper_fact_without_execution(
    monkeypatch,
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    order_id = "SHADOW-2026-04-19-001-510300-buy-fixture"
    db.record_order_sync(
        order_id=order_id,
        timestamp="2026-04-19T14:50:00+08:00",
        symbol="510300",
        side="buy",
        order_type="limit",
        quantity=1000.0,
        price=4.56,
        execution_mode="paper_shadow",
        status="filled",
        source="paper_shadow_daily",
        source_ref="shadow:2026-04-19:fixture",
        payload={"strategy_id": "dual_ma", "divergence_status": "review_required"},
    )
    fake_state = SimpleNamespace(
        db=db,
        trading_controls=TradingControlState(),
        hub=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    review_endpoint = _endpoint(
        "/api/trading/order-facts/{order_id}/shadow-divergence-review",
        method="POST",
    )

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
    payload = json.loads(order["payload_json"])

    assert reviewed["order_id"] == order_id
    assert reviewed["execution_mode"] == "paper_shadow"
    assert reviewed["status"] == "filled"
    assert payload["divergence_status"] == "within_expectations"
    assert payload["divergence_reviewed_at"] == "2026-04-20T16:00:00"
    assert payload["divergence_review_notes"].startswith("Shadow quantity")
    assert payload["divergence_reviewer"] == "operator"
    assert payload["strategy_id"] == "dual_ma"
    assert db.list_fills_sync(order_id=order_id) == []


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
