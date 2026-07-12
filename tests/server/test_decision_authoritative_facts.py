from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.db import AppDatabase


def _endpoint(path: str):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path and "GET" in route.methods
    )


def _add_action(
    db: AppDatabase,
    *,
    source_signal_id: int,
    symbol: str,
    timestamp: str,
    price: float,
) -> None:
    db.save_signal_sync(
        timestamp=timestamp,
        strategy_id="dual_ma",
        symbol=symbol,
        direction="buy",
        target_weight=0.1,
        price=price,
        asset_class="stock",
    )
    db.upsert_action_task_sync(
        source_signal_id=source_signal_id,
        symbol=symbol,
        title=f"候选买入 {symbol}",
        detail="authoritative decision facts fixture",
        direction="buy",
        urgency="normal",
        target_weight=0.1,
        price=price,
        strategy_id="dual_ma",
        timestamp=timestamp,
        asset_class="stock",
    )


def test_decision_uses_persisted_portfolio_and_current_deduplicated_batch(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-01T09:00:00+08:00",
        amount=10000.0,
        created_at="2026-07-01T09:00:01+08:00",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-07-10T09:35:00+08:00",
        symbol="603659",
        direction="buy",
        quantity=100,
        price=20.0,
        gross_amount=2000.0,
        net_cash_impact=-2000.0,
        created_at="2026-07-10T09:35:01+08:00",
    )
    db.upsert_latest_quote_sync(
        symbol="603659",
        asset_type="stock",
        price=25.0,
        quote_timestamp="2026-07-10T15:00:00+08:00",
        quote_source="deterministic_fixture",
        quote_status="confirmed",
    )
    _add_action(
        db,
        source_signal_id=1,
        symbol="600000",
        timestamp="2026-07-09T09:30:00+08:00",
        price=9.0,
    )
    _add_action(
        db,
        source_signal_id=2,
        symbol="603659",
        timestamp="2026-07-10T09:30:00+08:00",
        price=24.0,
    )
    _add_action(
        db,
        source_signal_id=3,
        symbol="603659",
        timestamp="2026-07-10T10:30:00+08:00",
        price=25.0,
    )
    db.publish_current_valuation_snapshot_sync()
    stale_runtime_portfolio = SimpleNamespace(
        cash=-999.0,
        positions={
            "603659": SimpleNamespace(
                quantity=999,
                market_value=-123.0,
            )
        },
        instruments={},
    )
    state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(initial_cash=0.0, assets=[]),
        scheduler=SimpleNamespace(
            portfolio=stale_runtime_portfolio,
            instruments={},
            watchlist=[],
            latest_quotes={"603659": {"price": 1.0}},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: state)

    response = asyncio.run(_endpoint("/api/decision/today")())

    assert response["decision_date"] == "2026-07-10"
    assert response["summary"]["candidate_count"] == 1
    assert response["candidates"][0]["action_id"] == 3
    portfolio = response["summary"]["portfolio"]
    assert portfolio["fact_authority"] == "persisted_valuation_snapshot"
    assert portfolio["cash"] == 8000.0
    assert portfolio["total_market_value"] == 2500.0
    assert portfolio["total_equity"] == 10500.0
    assert portfolio["valuation_trade_date"] == "2026-07-10"
    assert portfolio["valuation_snapshot_id"].startswith("valuation-")
    assert response["summary"]["market_data"]["latest_quote_timestamp"] == (
        "2026-07-10T15:00:00+08:00"
    )
