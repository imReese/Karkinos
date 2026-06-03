from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.db import AppDatabase


def test_post_trade_and_read_positions_uses_ledger_projection(tmp_path, monkeypatch):
    from server.routes import ledger as ledger_routes
    from server.routes import portfolio as portfolio_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=200000),
        scheduler=None,
        db=db,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    ledger_router = ledger_routes.create_router()
    create_trade_route = next(
        route
        for route in ledger_router.routes
        if isinstance(route, APIRoute) and route.path == "/api/ledger/trades"
    )
    create_trade = create_trade_route.endpoint

    create_response = asyncio.run(
        create_trade(
            ledger_routes.LedgerTradeCreate(
                symbol="600519",
                asset_class="stock",
                direction="buy",
                quantity=100,
                unit_price=1500,
                fee=5,
                occurred_at="2026-04-20T09:30:00",
                source_ref="trade-1",
            )
        )
    )

    portfolio_router = portfolio_routes.create_router()
    positions_route = next(
        route
        for route in portfolio_router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/positions"
    )
    get_positions = positions_route.endpoint

    positions = asyncio.run(get_positions())

    assert create_response.status == "ok"
    assert create_response.entry_type == "trade_buy"
    assert len(positions) == 1
    assert positions[0].symbol == "600519"
    assert positions[0].quantity == 100.0
    assert positions[0].avg_cost == 1500.05
