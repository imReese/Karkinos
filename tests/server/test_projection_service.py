from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.ledger.models import LedgerEntry
from server.projections.service import build_portfolio_projection


def test_build_portfolio_projection_handles_deposit_buy_and_sell():
    entries = [
        LedgerEntry(
            entry_type="fee",
            timestamp="2026-04-18T08:30:00+00:00",
            amount=2.0,
        ),
        LedgerEntry(
            entry_type="cash_deposit",
            timestamp="2026-04-18T09:00:00+00:00",
            amount=1000.0,
        ),
        LedgerEntry(
            entry_type="trade_buy",
            timestamp="2026-04-18T10:00:00+00:00",
            symbol="600519",
            direction="buy",
            quantity=10.0,
            price=10.0,
            commission=1.0,
        ),
        LedgerEntry(
            entry_type="dividend",
            timestamp="2026-04-18T10:30:00+00:00",
            symbol="600519",
            amount=5.0,
        ),
        LedgerEntry(
            entry_type="manual_adjustment",
            timestamp="2026-04-18T10:45:00+00:00",
            amount=3.0,
        ),
        LedgerEntry(
            entry_type="cash_withdrawal",
            timestamp="2026-04-18T10:50:00+00:00",
            amount=20.0,
        ),
        LedgerEntry(
            entry_type="trade_sell",
            timestamp="2026-04-18T11:00:00+00:00",
            symbol="600519",
            direction="sell",
            quantity=4.0,
            price=12.0,
            commission=0.5,
        ),
    ]

    projection = build_portfolio_projection(
        entries,
        latest_quotes={"600519": {"price": 11.0}},
    )

    assert projection.cash == 932.5
    assert projection.total_deposits == 980.0
    assert projection.total_equity == 998.5

    position = projection.positions["600519"]
    assert position.quantity == 6.0
    assert position.avg_cost == 10.0
    assert position.realized_pnl == 12.5
    assert position.commission_paid == 1.5
    assert position.market_value == 66.0
    assert position.unrealized_pnl == 6.0


def test_portfolio_route_keeps_legacy_rebuild_when_ledger_is_empty(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    portfolio_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )
    endpoint = portfolio_route.endpoint

    class FakeDb:
        def get_ledger_entries_sync(self, limit=500, offset=0):
            return []

        def get_cash_flows_sync(self, limit=1000, offset=0):
            return []

        def get_trades_sync(self, limit=1000, offset=0):
            return [
                {
                    "id": 1,
                    "timestamp": "2026-04-18T10:00:00",
                    "symbol": "600519",
                    "direction": "buy",
                    "quantity": 10.0,
                    "price": 10.0,
                    "commission": 1.0,
                    "asset_class": "stock",
                    "note": "",
                    "created_at": "2026-04-18T10:00:01",
                }
            ]

        async def get_total_deposits(self):
            return 1000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}, watchlist=[], instruments={}),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.cash == 899.0
    assert response.positions[0].symbol == "600519"
    assert response.positions[0].quantity == 10.0


def test_portfolio_route_ignores_ledger_rows_during_legacy_writes(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    portfolio_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )
    endpoint = portfolio_route.endpoint

    class FakeDb:
        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [
                {
                    "id": 1,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-18T10:00:00+00:00",
                    "symbol": "999999",
                    "direction": "buy",
                    "quantity": 1.0,
                    "price": 1.0,
                    "commission": 0.0,
                    "asset_class": "stock",
                    "note": "should be ignored",
                    "source": "manual",
                    "source_ref": "ledger-1",
                    "created_at": "2026-04-18T10:00:01+00:00",
                }
            ]

        def get_cash_flows_sync(self, limit=1000, offset=0):
            return []

        def get_trades_sync(self, limit=1000, offset=0):
            return [
                {
                    "id": 1,
                    "timestamp": "2026-04-18T10:00:00",
                    "symbol": "600519",
                    "direction": "buy",
                    "quantity": 10.0,
                    "price": 10.0,
                    "commission": 1.0,
                    "asset_class": "stock",
                    "note": "",
                    "created_at": "2026-04-18T10:00:01",
                }
            ]

        async def get_total_deposits(self):
            return 1000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}, watchlist=[], instruments={}),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.cash == 899.0
    assert [position.symbol for position in response.positions] == ["600519"]
