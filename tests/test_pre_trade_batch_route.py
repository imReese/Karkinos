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


def _publish_complete_valuation(
    db: AppDatabase,
    *,
    existing_position_value: float = 0.0,
) -> dict:
    starting_cash = 5000.0 + existing_position_value
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-02T09:00:00+08:00",
        amount=starting_cash,
        created_at="2026-07-02T09:00:01+08:00",
    )
    if existing_position_value:
        db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp="2026-07-02T09:05:00+08:00",
            symbol="159915",
            direction="buy",
            quantity=existing_position_value,
            price=1.0,
            gross_amount=existing_position_value,
            net_cash_impact=-existing_position_value,
            created_at="2026-07-02T09:05:01+08:00",
        )
        db.upsert_latest_quote_sync(
            symbol="159915",
            asset_type="stock",
            price=1.0,
            quote_timestamp="2026-07-02T09:30:00+08:00",
            quote_source="deterministic_fixture",
            quote_status="confirmed",
        )
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="stock",
        price=10.0,
        quote_timestamp="2026-07-02T09:30:00+08:00",
        quote_source="deterministic_fixture",
        quote_status="confirmed",
    )
    return db.publish_current_valuation_snapshot_sync()


def test_decision_batch_pre_trade_risk_route_runs_without_creating_orders(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import decision as decision_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _add_action(db)
    published = _publish_complete_valuation(db)
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(initial_cash=0.0, assets=[]),
        trading_controls=TradingControlState(db=db),
        scheduler=SimpleNamespace(portfolio=None, instruments={}),
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
    assert result["valuation_snapshot_id"] == published["snapshot_id"]
    assert result["ledger_cutoff_id"] == published["ledger_cutoff_id"]
    assert result["persisted_facts_only"] is True
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
    _publish_complete_valuation(db, existing_position_value=95000.0)
    portfolio = SimpleNamespace(
        cash=5000,
        positions={"159915": SimpleNamespace(market_value=95000)},
        instruments={},
    )
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(initial_cash=0.0, assets=[]),
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
    published = _publish_complete_valuation(db)
    db.get_account_truth_score_sync = lambda: {
        "gate_status": "pass",
        "score": 98,
        "has_evidence": True,
        "unresolved_mismatch_count": 0,
    }
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
        config=SimpleNamespace(initial_cash=0.0, assets=[]),
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
    assert batch_result["valuation_snapshot_id"] == published["snapshot_id"]
    assert trading_plan["conclusion_status"] == "manual_confirmation_ready"
    assert trading_plan["manual_ready_count"] == 1
    assert trading_plan["order_intent_count"] == 1
    assert trading_plan["broker_bridge_status"] == "disabled"
    assert trading_plan["order_intents"][0]["does_not_submit_broker_order"] is True
    assert db.list_manual_orders_sync() == []


def test_decision_batch_pre_trade_risk_blocks_unconfirmed_fund_without_writes(
    tmp_path,
    monkeypatch,
) -> None:
    from server.routes import decision as decision_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-02T09:00:00+08:00",
        amount=5000.0,
        created_at="2026-07-02T09:00:01+08:00",
    )
    signal_id = db.save_signal_sync(
        timestamp="2026-07-02T14:30:00+08:00",
        strategy_id="fund_rotation",
        symbol="019999",
        direction="buy",
        target_weight=0.2,
        price=2.2527,
        asset_class="fund",
    )
    db.upsert_action_task_sync(
        source_signal_id=signal_id,
        symbol="019999",
        title="候选买入 019999",
        detail="unconfirmed fund batch-risk fixture",
        direction="buy",
        urgency="normal",
        target_weight=0.2,
        price=2.2527,
        strategy_id="fund_rotation",
        timestamp="2026-07-02T14:30:00+08:00",
        asset_class="fund",
    )
    db.upsert_latest_quote_sync(
        symbol="019999",
        asset_type="fund",
        price=2.2527,
        quote_timestamp="2026-07-02T14:30:00+08:00",
        quote_source="eastmoney_fund_estimate",
        quote_status="live",
    )
    published = db.publish_current_valuation_snapshot_sync()
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(initial_cash=0.0, assets=[]),
        trading_controls=TradingControlState(db=db),
        scheduler=SimpleNamespace(portfolio=None, instruments={}),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    endpoint = _route(
        decision_routes.create_router(),
        "/api/decision/pre-trade-risk/batch",
        "POST",
    ).endpoint

    first = asyncio.run(endpoint())
    second = asyncio.run(endpoint())

    assert published["status"] == "degraded"
    assert first == second
    assert first["status"] == "blocked_by_data_quality"
    assert first["processed_count"] == 0
    assert first["skipped_count"] == 1
    assert first["risk_decision_writes_performed"] is False
    assert first["database_writes_performed"] is False
    assert first["valuation_snapshot_id"] == published["snapshot_id"]
    assert {blocker["code"] for blocker in first["blockers"]} >= {
        "valuation_snapshot_not_complete",
        "candidate_market_data_not_complete",
    }
    assert db.get_risk_decisions_sync() == []
    action = db.get_action_tasks_sync()[0]
    assert action["risk_gate_status"] == "not_checked"
    assert db.list_manual_orders_sync() == []
