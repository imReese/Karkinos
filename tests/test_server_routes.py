from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import BackgroundTasks
from fastapi.routing import APIRoute


def test_market_quote_prefers_persisted_snapshot_and_refreshes_async(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    quote_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote/{symbol}"
    )
    endpoint = quote_route.endpoint

    async def fake_get_latest_quote(symbol: str):
        return {
            "symbol": "600519",
            "asset_class": "stock",
            "price": 111.11,
            "volume": 2222.0,
            "timestamp": "2026-04-18T09:40:00",
        }

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "600519", "asset_class": "stock"}],
        ),
        scheduler=SimpleNamespace(is_running=False, latest_quotes={}),
        db=SimpleNamespace(get_latest_quote=fake_get_latest_quote),
    )

    class FakeSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 123.46,
                "volume": 6789.0,
                "timestamp": "2026-04-18T09:41:00",
            }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(
        "data.manager.build_sources", lambda **kwargs: {"akshare": FakeSource()}
    )

    background_tasks = BackgroundTasks()
    response = asyncio.run(endpoint("600519", background_tasks))

    assert response.price == 111.11
    assert response.asset_class == "stock"
    assert len(background_tasks.tasks) == 1


def test_market_quote_refresh_is_throttled(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    quote_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote/{symbol}"
    )
    endpoint = quote_route.endpoint

    async def fake_get_latest_quote(symbol: str):
        return {
            "symbol": "600519",
            "asset_class": "stock",
            "price": 111.11,
            "volume": 2222.0,
            "timestamp": "2026-04-18T09:40:00",
        }

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(is_running=False, latest_quotes={}),
        db=SimpleNamespace(get_latest_quote=fake_get_latest_quote),
    )

    market_routes._QUOTE_REFRESH_ATTEMPTS.clear()
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)

    first_tasks = BackgroundTasks()
    second_tasks = BackgroundTasks()
    asyncio.run(endpoint("600519", first_tasks))
    asyncio.run(endpoint("600519", second_tasks))

    assert len(first_tasks.tasks) == 1
    assert len(second_tasks.tasks) == 0


def test_market_quote_prefers_persisted_snapshot_without_refresh_when_closed(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    quote_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote/{symbol}"
    )
    endpoint = quote_route.endpoint

    async def fake_get_latest_quote(symbol: str):
        return {
            "symbol": "600519",
            "asset_class": "stock",
            "price": 111.11,
            "volume": 2222.0,
            "timestamp": "2026-04-18T09:40:00",
        }

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "600519", "asset_class": "stock"}],
        ),
        scheduler=SimpleNamespace(is_running=False, latest_quotes={}),
        db=SimpleNamespace(get_latest_quote=fake_get_latest_quote),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)

    background_tasks = BackgroundTasks()
    response = asyncio.run(endpoint("600519", background_tasks))

    assert response.price == 111.11
    assert response.asset_class == "stock"
    assert len(background_tasks.tasks) == 0


def test_market_data_health_uses_watchlist_and_latest_snapshots(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    health_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/data-health"
    )
    endpoint = health_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
        ),
        scheduler=SimpleNamespace(
            watchlist=[("600519", "stock")],
            latest_quotes={
                "600519": {
                    "timestamp": "2026-04-18T09:30:00",
                    "price": 123.45,
                }
            },
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)

    response = asyncio.run(endpoint())

    assert response["quotes"][0]["symbol"] == "600519"
    assert response["quotes"][0]["price"] == 123.45
    assert response["bars"][0]["rows"] == 0
    assert response["market_open"] is False
    assert response["refresh_policy"] == "cache_only"


def test_market_quote_falls_back_to_persisted_snapshot(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    quote_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote/{symbol}"
    )
    endpoint = quote_route.endpoint

    async def fake_get_latest_quote(symbol: str):
        return {
            "symbol": "600519",
            "asset_class": "stock",
            "price": 111.11,
            "volume": 2222.0,
            "timestamp": "2026-04-18T09:40:00",
        }

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "600519", "asset_class": "stock"}],
        ),
        scheduler=SimpleNamespace(is_running=False, latest_quotes={}),
        db=SimpleNamespace(get_latest_quote=fake_get_latest_quote),
    )

    class BrokenSource:
        def fetch_latest(self, symbol, asset_class):
            raise RuntimeError("provider down")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources", lambda **kwargs: {"akshare": BrokenSource()}
    )

    response = asyncio.run(endpoint("600519", BackgroundTasks()))

    assert response.price == 111.11
    assert response.asset_class == "stock"


def test_market_watchlist_includes_holding_fields(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    watchlist_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/watchlist"
    )
    endpoint = watchlist_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        avg_cost=10.5,
        market_value=1234.5,
        unrealized_pnl=184.5,
        realized_pnl=20.0,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
        ),
        scheduler=SimpleNamespace(
            is_running=True,
            latest_quotes={"600519": {"timestamp": "2026-04-18T10:00:00"}},
            portfolio=SimpleNamespace(positions={"600519": fake_position}),
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response[0].symbol == "600519"
    assert response[0].is_holding is True
    assert response[0].quantity == 100
    assert response[0].unrealized_pnl == 184.5
    assert response[0].last_snapshot_at == "2026-04-18T10:00:00"


def test_market_watchlist_auto_includes_ledger_holdings(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    watchlist_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/watchlist"
    )
    endpoint = watchlist_route.endpoint

    fake_position = SimpleNamespace(
        quantity=1000,
        avg_cost=1.0,
        market_value=1015.0,
        unrealized_pnl=15.0,
        realized_pnl=0.0,
    )

    class FakeDb:
        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "永赢先进制造智选混合C",
                    "asset_class": "fund",
                    "price": 1.015,
                    "volume": None,
                    "timestamp": "2026-04-18T15:00:00",
                }
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(assets=[]),
        scheduler=SimpleNamespace(
            is_running=False,
            latest_quotes={},
            portfolio=SimpleNamespace(positions={"永赢先进制造智选混合C": fake_position}),
            instruments={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert len(response) == 1
    assert response[0].symbol == "永赢先进制造智选混合C"
    assert response[0].asset_class == "fund"
    assert response[0].is_holding is True
    assert response[0].quantity == 1000
    assert response[0].last_snapshot_at == "2026-04-18T15:00:00"


def test_market_kline_uses_cache_only_when_closed(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    kline_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/kline/{symbol}"
    )
    endpoint = kline_route.endpoint

    observed: dict[str, object] = {}

    class FakeManager:
        def __init__(self, *args, **kwargs):
            pass

        def get_bars(self, symbol, start, end, frequency, asset_class, **kwargs):
            observed.update(kwargs)
            return []

    class FakeStore:
        def __init__(self, *args, **kwargs):
            pass

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            live_poll_interval=60,
        ),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)
    monkeypatch.setattr("data.manager.DataManager", FakeManager)
    monkeypatch.setattr("data.store.DataStore", FakeStore)

    response = asyncio.run(endpoint("600519"))

    assert response == []
    assert observed["allow_remote_refresh"] is False
    assert observed["degrade_to_cache"] is True
    assert observed["refresh_ttl_seconds"] == 60


def test_market_quote_resolves_asset_class_from_auto_added_holdings(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    quote_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote/{symbol}"
    )
    endpoint = quote_route.endpoint

    async def fake_get_latest_quote(symbol: str):
        return {
            "symbol": symbol,
            "asset_class": "fund",
            "price": 1.023,
            "volume": None,
            "timestamp": "2026-04-18T15:00:00",
        }

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[],
        ),
        scheduler=SimpleNamespace(
            is_running=False,
            latest_quotes={},
            portfolio=SimpleNamespace(
                positions={
                    "永赢先进制造智选混合C": SimpleNamespace(
                        quantity=1000,
                        avg_cost=1.0,
                        market_value=1023.0,
                        unrealized_pnl=23.0,
                        realized_pnl=0.0,
                    )
                }
            ),
            instruments={},
        ),
        db=SimpleNamespace(
            get_latest_quote=fake_get_latest_quote,
            get_latest_quotes_sync=lambda: [],
        ),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)

    response = asyncio.run(endpoint("永赢先进制造智选混合C", BackgroundTasks()))

    assert response.asset_class == "fund"
    assert response.price == 1.023


def test_market_watchlist_add_and_remove(monkeypatch, tmp_path):
    from server.routes import market as market_routes

    market_routes._CONFIG_PATH = tmp_path / "config.json"
    router = market_routes.create_router()
    add_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/watchlist"
        and "POST" in route.methods
    )
    remove_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/watchlist/{symbol}"
        and "DELETE" in route.methods
    )

    config = SimpleNamespace(
        host="0.0.0.0",
        port=8000,
        live_auto_start=True,
        initial_cash=Decimal("100000"),
        start_date="2025-01-02",
        end_date="",
        assets=[{"symbol": "600519", "asset_class": "stock"}],
        strategy="dual_ma",
        short_period=5,
        long_period=20,
        data_source="akshare",
        tushare_token="",
        notification={"type": "console"},
        live_poll_interval=60,
    )
    fake_state = SimpleNamespace(
        config=config,
        scheduler=SimpleNamespace(is_running=False, latest_quotes={}, portfolio=None),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    add_response = asyncio.run(
        add_route.endpoint(market_routes.WatchlistCreateRequest(symbol="510300", asset_class="etf"))
    )
    assert any(item.symbol == "510300" for item in add_response)

    remove_response = asyncio.run(remove_route.endpoint("510300"))
    assert all(item.symbol != "510300" for item in remove_response)


def test_update_data_source_settings_does_not_overwrite_account_baseline(monkeypatch):
    from server.routes import settings as settings_routes

    router = settings_routes.create_router()
    update_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/settings/data-source"
        and "PUT" in route.methods
    )

    config = SimpleNamespace(
        host="0.0.0.0",
        port=8000,
        live_auto_start=False,
        initial_cash=Decimal("4000"),
        start_date="2025-01-02",
        end_date="2026-04-18",
        assets=[
            {"symbol": "永赢先进制造智选混合C", "asset_class": "fund"},
            {"symbol": "融通科技臻选混合C", "asset_class": "fund"},
        ],
        strategy="dual_ma",
        short_period=5,
        long_period=20,
        data_source="akshare",
        tushare_token="",
        notification={"type": "console"},
        live_poll_interval=60,
    )
    fake_state = SimpleNamespace(config=config)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(
        update_route.endpoint(
            settings_routes.DataSourceSettingsUpdate(
                data_source="tushare",
                tushare_token="token-1234",
                live_poll_interval=120,
            )
        )
    )

    assert response.data_source == "tushare"
    assert response.live_poll_interval == 120
    assert response.initial_cash == 4000.0
    assert response.assets == [
        {"symbol": "永赢先进制造智选混合C", "asset_class": "fund"},
        {"symbol": "融通科技臻选混合C", "asset_class": "fund"},
    ]


def test_portfolio_overview_summarizes_account_state(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    overview_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/overview"
    )
    endpoint = overview_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=1500,
        unrealized_pnl=500,
        realized_pnl=120,
        commission_paid=8,
    )
    fake_portfolio = SimpleNamespace(
        cash=500,
        positions={"600519": fake_position},
        equity_curve=[],
    )

    async def fake_get_total_deposits():
        return 2000.0

    fake_db = SimpleNamespace(get_total_deposits=fake_get_total_deposits)
    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=fake_db,
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            watchlist=[],
            instruments={},
        ),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.total_equity == 2000
    assert response.available_cash == 500
    assert response.positions_count == 1
    assert response.unrealized_pnl == 500
    assert response.realized_pnl == 120
    assert response.cash_ratio == 0.25


def test_portfolio_rebuild_uses_persisted_quotes_for_fund_pnl(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    portfolio_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )
    endpoint = portfolio_route.endpoint

    class FakeDb:
        async def get_total_deposits(self):
            return 0.0

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "永赢先进制造智选混合C",
                    "asset_class": "fund",
                    "price": 1.023,
                    "volume": None,
                    "timestamp": "2026-04-18",
                }
            ]

        def get_cash_flows_sync(self, limit=1000, offset=0):
            return []

        def get_trades_sync(self, limit=1000, offset=0):
            return [
                {
                    "id": 1,
                    "timestamp": "2026-04-13T13:33:00",
                    "symbol": "永赢先进制造智选混合C",
                    "direction": "buy",
                    "quantity": 1000.0,
                    "price": 1.0,
                    "commission": 0.0,
                    "asset_class": "fund",
                }
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=4000,
            assets=[{"symbol": "永赢先进制造智选混合C", "asset_class": "fund"}],
        ),
        db=FakeDb(),
        scheduler=SimpleNamespace(
            portfolio=None,
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.cash == 3000.0
    assert response.total_equity == 4023.0
    assert response.positions[0].market_value == 1023.0
    assert response.positions[0].unrealized_pnl == 23.0


def test_portfolio_state_projection_exposes_totals_and_next_step(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    state_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/state"
    )
    endpoint = state_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=1500,
        unrealized_pnl=500,
        realized_pnl=120,
        commission_paid=8,
    )
    fake_portfolio = SimpleNamespace(
        cash=500,
        positions={"600519": fake_position},
        equity_curve=[],
    )

    async def fake_get_total_deposits():
        return 2000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=SimpleNamespace(get_total_deposits=fake_get_total_deposits),
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            watchlist=[],
            instruments={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.summary.total_equity == 2000
    assert response.summary.available_cash == 500
    assert response.summary.positions_count == 1
    assert response.snapshot.total_equity == 2000
    assert response.next_step == "确认待执行建议"


def test_portfolio_risk_summary_flags_concentration_and_low_cash(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    risk_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/risk-summary"
    )
    endpoint = risk_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=1800,
        unrealized_pnl=500,
        realized_pnl=120,
        commission_paid=8,
    )

    async def fake_get_total_deposits():
        return 2000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=SimpleNamespace(get_total_deposits=fake_get_total_deposits),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=Decimal("200"),
                positions={"600519": fake_position},
                equity_curve=[],
            ),
            watchlist=[],
            instruments={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert len(response) == 2
    assert response[0].kind == "risk"
    assert response[0].level == "high"
    assert "仓位集中" in response[0].title
    assert response[1].level == "medium"


def test_portfolio_risk_summary_flags_stale_quote_data(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    risk_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/risk-summary"
    )
    endpoint = risk_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=500,
        unrealized_pnl=20,
        realized_pnl=0,
        commission_paid=1,
    )

    async def fake_get_total_deposits():
        return 1000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=SimpleNamespace(
            get_total_deposits=fake_get_total_deposits,
            get_latest_quotes_sync=lambda: [
                {
                    "symbol": "600519",
                    "timestamp": "2026-04-15T09:30:00",
                }
            ],
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=Decimal("500"),
                positions={"600519": fake_position},
                equity_curve=[],
            ),
            watchlist=[],
            instruments={},
            latest_quotes={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert any(item.kind == "data" for item in response)


def test_portfolio_activity_merges_trades_and_cash_flows(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    activity_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/activity"
    )
    endpoint = activity_route.endpoint

    async def fake_get_cash_flows(limit=10, offset=0):
        return [
            {
                "id": 3,
                "timestamp": "2026-04-18T09:00:00",
                "amount": 5000.0,
                "flow_type": "deposit",
                "note": "补充仓位",
                "created_at": "2026-04-18T09:00:01",
            }
        ]

    async def fake_get_trades(limit=10, offset=0):
        return [
            {
                "id": 8,
                "timestamp": "2026-04-18T10:00:00",
                "symbol": "600519",
                "direction": "buy",
                "quantity": 100.0,
                "price": 123.45,
                "commission": 5.0,
                "asset_class": "stock",
                "note": "执行首页任务",
                "created_at": "2026-04-18T10:00:01",
            }
        ]

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            get_cash_flows=fake_get_cash_flows,
            get_trades=fake_get_trades,
        )
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert len(response) == 2
    assert response[0].kind == "trade"
    assert response[0].title == "买入 600519"
    assert response[1].kind == "cash_flow"
    assert response[1].title == "入金"


def test_portfolio_rebuilds_from_ledger_when_scheduler_not_running(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    portfolio_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )
    endpoint = portfolio_route.endpoint

    def fake_get_cash_flows_sync(limit=1000, offset=0):
        return []

    def fake_get_trades_sync(limit=1000, offset=0):
        return [
            {
                "id": 1,
                "timestamp": "2026-04-13T13:33:00",
                "symbol": "永赢先进制造智选混合C",
                "direction": "buy",
                "quantity": 1000.0,
                "price": 1.0,
                "commission": 0.0,
                "asset_class": "fund",
                "note": "",
                "created_at": "2026-04-13T13:33:01",
            },
            {
                "id": 2,
                "timestamp": "2026-04-13T14:27:00",
                "symbol": "融通科技臻选混合C",
                "direction": "buy",
                "quantity": 500.0,
                "price": 1.0,
                "commission": 0.0,
                "asset_class": "fund",
                "note": "",
                "created_at": "2026-04-13T14:27:01",
            },
        ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=4000),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}, watchlist=[], instruments={}),
        db=SimpleNamespace(
            get_total_deposits=AsyncMock(return_value=0.0),
            get_cash_flows_sync=fake_get_cash_flows_sync,
            get_trades_sync=fake_get_trades_sync,
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.cash == 2500.0
    assert response.total_equity == 4000.0
    assert len(response.positions) == 2
    assert {item.asset_class for item in response.allocation if item.symbol != "CASH"} == {"fund"}


def test_signal_actions_convert_latest_signals_into_action_cards(monkeypatch):
    from server.routes import signals as signal_routes

    router = signal_routes.create_router()
    actions_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/signals/actions"
    )
    endpoint = actions_route.endpoint

    async def fake_get_latest_signals(limit=10):
        return [
            {
                "id": 1,
                "timestamp": "2026-04-18T09:35:00",
                "strategy_id": "dual_ma",
                "symbol": "600519",
                "direction": "buy",
                "target_weight": 0.2,
                "price": 123.45,
                "asset_class": "stock",
            },
            {
                "id": 2,
                "timestamp": "2026-04-18T09:40:00",
                "strategy_id": "dual_ma",
                "symbol": "510300",
                "direction": "sell",
                "target_weight": 0.0,
                "price": 4.56,
                "asset_class": "fund",
            },
        ]

    synced_rows: list[int] = []

    def fake_upsert_action_task_sync(**kwargs):
        synced_rows.append(kwargs["source_signal_id"])

    async def fake_get_action_tasks(statuses=None, limit=10):
        return [
            {
                "id": 1,
                "source_signal_id": 1,
                "timestamp": "2026-04-18T09:35:00",
                "strategy_id": "dual_ma",
                "symbol": "600519",
                "direction": "buy",
                "target_weight": 0.2,
                "price": 123.45,
                "asset_class": "stock",
                "title": "建议增持 600519",
                "detail": "dual_ma 触发，目标仓位 20%",
                "urgency": "high",
                "status": "pending",
            },
            {
                "id": 2,
                "source_signal_id": 2,
                "timestamp": "2026-04-18T09:40:00",
                "strategy_id": "dual_ma",
                "symbol": "510300",
                "direction": "sell",
                "target_weight": 0.0,
                "price": 4.56,
                "asset_class": "fund",
                "title": "建议减仓 510300",
                "detail": "dual_ma 触发，目标仓位 0%",
                "urgency": "medium",
                "status": "pending",
            },
        ]

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            get_latest_signals=fake_get_latest_signals,
            upsert_action_task_sync=fake_upsert_action_task_sync,
            get_action_tasks=fake_get_action_tasks,
        )
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert len(response) == 2
    assert response[0].title == "建议增持 600519"
    assert response[0].urgency == "high"
    assert response[1].title == "建议减仓 510300"
    assert response[1].urgency == "medium"
    assert synced_rows == [1, 2]


def test_signal_actions_return_pending_tasks_after_sync(monkeypatch):
    from server.routes import signals as signal_routes

    router = signal_routes.create_router()
    actions_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/signals/actions"
    )
    endpoint = actions_route.endpoint

    calls: list[tuple[str, object]] = []

    async def fake_get_latest_signals(limit=10):
        return [
            {
                "id": 1,
                "timestamp": "2026-04-18T09:35:00",
                "strategy_id": "dual_ma",
                "symbol": "600519",
                "direction": "buy",
                "target_weight": 0.2,
                "price": 123.45,
                "asset_class": "stock",
            }
        ]

    def fake_upsert_action_task_sync(**kwargs):
        calls.append(("upsert", kwargs["source_signal_id"]))

    async def fake_get_action_tasks(statuses=None, limit=10):
        calls.append(("get", tuple(statuses or [])))
        return [
            {
                "id": 9,
                "source_signal_id": 1,
                "symbol": "600519",
                "title": "建议增持 600519",
                "detail": "dual_ma 触发，目标仓位 20%",
                "direction": "buy",
                "urgency": "high",
                "target_weight": 0.2,
                "price": 123.45,
                "strategy_id": "dual_ma",
                "timestamp": "2026-04-18T09:35:00",
                "asset_class": "stock",
                "status": "pending",
            }
        ]

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            get_latest_signals=fake_get_latest_signals,
            upsert_action_task_sync=fake_upsert_action_task_sync,
            get_action_tasks=fake_get_action_tasks,
        )
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert len(response) == 1
    assert response[0].id == 9
    assert response[0].status == "pending"
    assert ("upsert", 1) in calls
    assert ("get", ("pending", "deferred")) in calls


def test_signal_action_status_update_returns_updated_task(monkeypatch):
    from server.routes import signals as signal_routes

    router = signal_routes.create_router()
    update_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/signals/actions/{action_id}"
    )
    endpoint = update_route.endpoint

    async def fake_update_action_task_status(action_id: int, status: str):
        assert action_id == 7
        assert status == "executed"
        return {
            "id": 7,
            "source_signal_id": 2,
            "symbol": "510300",
            "title": "建议减仓 510300",
            "detail": "dual_ma 触发，目标仓位 0%",
            "direction": "sell",
            "urgency": "medium",
            "target_weight": 0.0,
            "price": 4.56,
            "strategy_id": "dual_ma",
            "timestamp": "2026-04-18T09:40:00",
            "asset_class": "fund",
            "status": "executed",
        }

    fake_state = SimpleNamespace(
        db=SimpleNamespace(update_action_task_status=fake_update_action_task_status)
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    body = signal_routes.ActionTaskStatusUpdate(status="executed")
    response = asyncio.run(endpoint(7, body))

    assert response.id == 7
    assert response.status == "executed"


def test_portfolio_equity_curve_uses_ledger_projection_when_scheduler_missing(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    curve_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/equity-curve"
    )
    endpoint = curve_route.endpoint

    class FakeDb:
        def get_cash_flows_sync(self, limit=1, offset=0):
            return []

        def get_trades_sync(self, limit=1, offset=0):
            return []

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [
                {
                    "id": 1,
                    "entry_type": "cash_deposit",
                    "timestamp": "2026-04-18T09:00:00+00:00",
                    "amount": 100000.0,
                    "symbol": None,
                    "direction": None,
                    "quantity": None,
                    "price": None,
                    "commission": 0.0,
                    "asset_class": "stock",
                    "note": "",
                    "source": "manual",
                    "source_ref": "deposit-1",
                    "created_at": "2026-04-18T09:00:01+00:00",
                },
                {
                    "id": 2,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-18T10:00:00+00:00",
                    "amount": 10000.0,
                    "symbol": "600519",
                    "direction": "buy",
                    "quantity": 10.0,
                    "price": 1000.0,
                    "commission": 5.0,
                    "asset_class": "stock",
                    "note": "",
                    "source": "manual",
                    "source_ref": "trade-1",
                    "created_at": "2026-04-18T10:00:01+00:00",
                },
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 1100.0,
                    "volume": 1000.0,
                    "timestamp": "2026-04-18T15:00:00+00:00",
                }
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}, watchlist=[], instruments={}),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    curve = asyncio.run(endpoint())

    assert len(curve) == 2
    assert curve[0].equity == 100000.0
    assert curve[-1].equity > curve[0].equity
