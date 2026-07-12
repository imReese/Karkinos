from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.db import AppDatabase
from server.services.trading_controls import TradingControlState


def _route(router, path: str, method: str = "POST"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def _add_action(db: AppDatabase) -> None:
    db.save_signal_sync(
        timestamp="2026-07-02T09:30:00",
        strategy_id="dual_ma",
        symbol="510300",
        direction="buy",
        target_weight=0.2,
        price=10.0,
        asset_class="stock",
    )
    db.upsert_action_task_sync(
        source_signal_id=1,
        symbol="510300",
        title="候选买入 510300",
        detail="route batch pre-trade risk test",
        direction="buy",
        urgency="normal",
        target_weight=0.2,
        price=10.0,
        strategy_id="dual_ma",
        timestamp="2026-07-02T09:30:00",
        asset_class="stock",
    )


def test_decision_batch_pre_trade_risk_route_runs_without_creating_orders(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import decision as decision_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(db)
    portfolio = SimpleNamespace(cash=5000, positions={}, instruments={})
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(),
        trading_controls=TradingControlState(db=db),
        scheduler=SimpleNamespace(portfolio=portfolio),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    endpoint = _route(
        decision_routes.create_router(),
        "/api/decision/pre-trade-risk/batch",
        "POST",
    ).endpoint
    result = asyncio.run(endpoint())

    assert result["processed_count"] == 1
    assert result["passed_count"] == 1
    assert result["does_not_create_order"] is True
    assert db.get_action_tasks_sync()[0]["risk_gate_status"] == "passed"
    assert db.list_manual_orders_sync() == []


def test_decision_batch_pre_trade_risk_route_applies_cash_bounded_allocation(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import decision as decision_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(db)
    portfolio = SimpleNamespace(
        cash=5000,
        positions={"159915": SimpleNamespace(market_value=95000)},
        instruments={},
    )
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(),
        trading_controls=TradingControlState(db=db),
        scheduler=SimpleNamespace(portfolio=portfolio),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    endpoint = _route(
        decision_routes.create_router(),
        "/api/decision/pre-trade-risk/batch",
        "POST",
    ).endpoint
    result = asyncio.run(endpoint())

    assert result["processed_count"] == 1
    assert result["passed_count"] == 1
    action = db.get_action_tasks_sync()[0]
    assert action["risk_gate_status"] == "passed"
    assert action["risk_gate_reasons"] == ["approved"]


def test_decision_batch_pre_trade_risk_promotes_ready_trading_plan(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import decision as decision_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(db)
    db.get_account_truth_score_sync = lambda: {
        "gate_status": "pass",
        "score": 98,
        "has_evidence": True,
        "unresolved_mismatch_count": 0,
    }
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="stock",
        price=10.0,
        quote_timestamp="2026-07-02T09:30:00",
        quote_source="fixture",
        quote_status="live",
    )
    portfolio = SimpleNamespace(
        cash=5000,
        positions={},
        instruments={},
    )
    scheduler = SimpleNamespace(
        watchlist=[],
        latest_quotes={
            "510300": {
                "symbol": "510300",
                "asset_type": "stock",
                "price": 10.0,
                "quote_status": "live",
                "quote_timestamp": "2026-07-02T09:30:00",
                "quote_source": "fixture",
            }
        },
        portfolio=portfolio,
    )
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(),
        trading_controls=TradingControlState(db=db),
        scheduler=scheduler,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    router = decision_routes.create_router()

    batch_endpoint = _route(
        router,
        "/api/decision/pre-trade-risk/batch",
        "POST",
    ).endpoint
    trading_plan_endpoint = _route(
        router,
        "/api/decision/trading-plan",
        "GET",
    ).endpoint

    batch_result = asyncio.run(batch_endpoint())
    trading_plan = asyncio.run(trading_plan_endpoint())

    assert batch_result["passed_count"] == 1
    assert trading_plan["conclusion_status"] == "manual_confirmation_ready"
    assert trading_plan["manual_ready_count"] == 1
    assert trading_plan["order_intent_count"] == 1
    assert trading_plan["broker_bridge_status"] == "disabled"
    assert trading_plan["order_intents"][0]["does_not_submit_broker_order"] is True
    assert db.list_manual_orders_sync() == []
