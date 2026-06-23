from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.ledger.models import LedgerEntry
from server.projections.models import PortfolioProjection, ProjectedPosition
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
    assert position.avg_cost == Decimal("10.1")
    assert position.realized_pnl == Decimal("12.10")
    assert position.commission_paid == 1.5
    assert position.market_value == 66.0
    assert position.unrealized_pnl == Decimal("5.40")


def test_build_portfolio_projection_treats_cash_interest_as_cash_income():
    projection = build_portfolio_projection(
        [
            LedgerEntry(
                entry_type="cash_interest",
                timestamp="2026-06-22T06:24:15+00:00",
                amount=0.27,
            )
        ]
    )

    assert projection.cash == Decimal("0.27")
    assert projection.total_equity == Decimal("0.27")
    assert projection.positions == {}


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


def test_portfolio_route_prefers_ledger_rows_over_legacy_trade_rows(monkeypatch):
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

    assert response.cash == 999.0
    assert [position.symbol for position in response.positions] == ["999999"]


def test_portfolio_route_prefers_db_ledger_over_stale_scheduler_portfolio(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    portfolio_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )
    endpoint = portfolio_route.endpoint

    stale_portfolio = PortfolioProjection(cash=Decimal("1000"))
    stale_portfolio.positions["601985"] = ProjectedPosition(
        symbol="601985",
        quantity=Decimal("100"),
        avg_cost=Decimal("8.7401"),
        market_value=Decimal("874.01"),
        commission_paid=Decimal("5.01"),
    )

    class FakeDb:
        def get_ledger_entries_sync(self, limit=500, offset=0):
            if offset:
                return []
            return [
                {
                    "id": 1,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-05-29T06:16:00+00:00",
                    "symbol": "603659",
                    "direction": "buy",
                    "quantity": 100.0,
                    "price": 29.98,
                    "commission": 5.03,
                    "asset_class": "stock",
                    "note": "manual buy",
                    "source": "manual",
                    "source_ref": "manual-603659",
                    "created_at": "2026-05-29T06:16:01+00:00",
                }
            ]

        def get_cash_flows_sync(self, limit=1000, offset=0):
            return []

        def get_trades_sync(self, limit=1000, offset=0):
            return []

        async def get_total_deposits(self):
            return 0.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        scheduler=SimpleNamespace(
            portfolio=stale_portfolio,
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert [position.symbol for position in response.positions] == ["603659"]
    assert response.positions[0].avg_cost == 30.0303


def test_live_holdings_groups_ledger_positions_by_metadata_asset_class(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )
    endpoint = live_holdings_route.endpoint

    class FakeDb:
        def get_ledger_entries_sync(self, limit=500, offset=0):
            if offset:
                return []
            return [
                {
                    "id": 1,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-05-29T06:16:00+00:00",
                    "symbol": "603659",
                    "direction": "buy",
                    "quantity": 100.0,
                    "price": 29.98,
                    "commission": 5.03,
                    "asset_class": "stock",
                    "note": "manual buy",
                    "source": "manual",
                    "source_ref": "manual-603659",
                    "created_at": "2026-05-29T06:16:01+00:00",
                }
            ]

        def get_cash_flows_sync(self, limit=1000, offset=0):
            return []

        def get_trades_sync(self, limit=1000, offset=0):
            return []

        def get_instrument_metadata_sync(self, symbol, asset_type=None):
            assert symbol == "603659"
            return {
                "symbol": "603659",
                "asset_type": "stock",
                "display_name": "璞泰来",
            }

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        scheduler=SimpleNamespace(
            portfolio=None,
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert len(response.groups) == 1
    assert response.groups[0].asset_class == "stock"
    assert response.groups[0].label == "A股"
    assert response.groups[0].items[0].display_name == "璞泰来"
    assert response.groups[0].items[0].asset_class == "stock"
