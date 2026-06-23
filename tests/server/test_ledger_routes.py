from __future__ import annotations

import asyncio
import pytest
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.db import AppDatabase


def test_ledger_entries_include_instrument_display_name(tmp_path, monkeypatch):
    from server.routes import ledger as ledger_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_instrument_metadata_sync(
        symbol="600066",
        asset_type="stock",
        display_name="宇通客车",
        provider_symbol="600066.SH",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-06-16T11:04:56+08:00",
        amount=5270.0,
        symbol="600066",
        direction="buy",
        quantity=200,
        price=26.35,
        commission=5,
        asset_class="stock",
        note="手工录入持仓：宇通客车 600066 买入，佣金按万1.5，最低5元计收",
        source="manual",
        source_ref="manual-600066-20260616-110456",
    )
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = ledger_routes.create_router()
    list_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/ledger/entries"
    )

    response = asyncio.run(list_route.endpoint())

    assert response[0].symbol == "600066"
    assert response[0].display_name == "宇通客车"


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


def test_ledger_trade_route_preserves_structured_sell_cost_fields(
    tmp_path, monkeypatch
):
    from server.routes import ledger as ledger_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    router = ledger_routes.create_router()
    create_trade = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/ledger/trades"
    ).endpoint
    list_entries = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/ledger/entries"
    ).endpoint

    asyncio.run(
        create_trade(
            ledger_routes.LedgerTradeCreate(
                symbol="600519",
                asset_class="stock",
                direction="sell",
                quantity=10,
                unit_price=1200,
                fee=8.5,
                occurred_at="2026-04-21T09:30:00",
                source_ref="trade-sell-1",
            )
        )
    )

    saved = asyncio.run(list_entries())[0]

    assert saved.entry_type == "trade_sell"
    assert saved.gross_amount == pytest.approx(12000.0)
    assert saved.net_cash_impact == pytest.approx(11991.5)
    assert saved.fee_breakdown == {
        "commission": "8.5",
        "stamp_tax": "0",
        "transfer_fee": "0",
        "other_fees": "0",
        "total_fee": "8.5",
    }
    assert saved.fee_rule_id == "manual_fee_input"
    assert saved.fee_rule_version == "manual_fee_input"
    assert saved.cost_basis_method == "moving_average_buy_cost"
