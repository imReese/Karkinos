from __future__ import annotations

import asyncio
import time
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from fastapi.routing import APIRoute

from core.types import Symbol


def _backtest_route(router, path: str, method: str = "GET"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_backtest_run_returns_metrics_json_cost_summary_and_fills(monkeypatch):
    from server.routes import backtest as backtest_routes

    router = backtest_routes.create_router()
    endpoint = _backtest_route(router, "/api/backtest/run", "POST").endpoint
    saved_payload: dict[str, object] = {}

    class FakeDb:
        async def save_backtest_result(self, **kwargs):
            saved_payload.update(kwargs)
            return 42

    fake_state = SimpleNamespace(
        config=SimpleNamespace(assets=[]),
        db=FakeDb(),
    )
    fake_result = {
        "initial_cash": 100000.0,
        "final_equity": 112000.0,
        "total_return": 0.12,
        "annual_return": 0.18,
        "sharpe": 1.4,
        "sortino": 1.9,
        "max_drawdown": 0.08,
        "win_rate": 0.56,
        "duration_days": 252,
        "equity_curve": [
            {"timestamp": "2026-01-01T00:00:00", "equity": 100000.0},
            {"timestamp": "2026-01-02T00:00:00", "equity": 112000.0},
        ],
        "metrics_json": {
            "calmar": 2.25,
            "volatility": 0.21,
            "total_commission": 12.5,
            "total_slippage": 3.5,
            "total_trades": 2,
            "gross_turnover": 24000.0,
        },
        "cost_summary_json": {
            "total_commission": 12.5,
            "total_slippage": 3.5,
            "total_trades": 2,
            "gross_turnover": 24000.0,
        },
        "fills": [
            {
                "fill_id": "FILL-1",
                "order_id": "ORD-1",
                "timestamp": "2026-01-02T10:00:00",
                "symbol": "600519",
                "side": "buy",
                "fill_price": 120.0,
                "fill_quantity": 100.0,
                "commission": 12.5,
                "slippage": 3.5,
            }
        ],
    }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(backtest_routes, "_run_backtest", lambda request, config: fake_result)

    response = asyncio.run(endpoint(backtest_routes.BacktestRequest()))

    assert response.id == 42
    assert response.metrics.calmar == 2.25
    assert response.metrics.volatility == 0.21
    assert response.metrics.total_commission == 12.5
    assert response.metrics_json["gross_turnover"] == 24000.0
    assert response.cost_summary_json["total_trades"] == 2
    assert response.fills[0].fill_id == "FILL-1"
    assert response.fills[0].symbol == "600519"
    assert '"calmar": 2.25' in str(saved_payload["metrics_json"])
    assert '"total_commission": 12.5' in str(saved_payload["cost_summary_json"])


def test_backtest_result_returns_json_contract_and_empty_fills(monkeypatch):
    from server.routes import backtest as backtest_routes

    router = backtest_routes.create_router()
    endpoint = _backtest_route(
        router, "/api/backtest/results/{result_id}", "GET"
    ).endpoint

    class FakeDb:
        async def get_backtest_result(self, result_id: int):
            assert result_id == 7
            return {
                "id": 7,
                "created_at": "2026-01-03T09:00:00",
                "config_json": backtest_routes.BacktestRequest().model_dump_json(),
                "initial_cash": 100000.0,
                "final_equity": 112000.0,
                "total_return": 0.12,
                "annual_return": 0.18,
                "sharpe": 1.4,
                "sortino": 1.9,
                "max_drawdown": 0.08,
                "win_rate": 0.56,
                "duration_days": 252,
                "equity_curve_json": '[{"timestamp":"2026-01-02T00:00:00","equity":112000.0}]',
                "metrics_json": '{"calmar":2.25,"volatility":0.21,"total_trades":2}',
                "cost_summary_json": '{"total_commission":12.5,"total_slippage":3.5}',
            }

    fake_state = SimpleNamespace(db=FakeDb())
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint(7))

    assert response.metrics.calmar == 2.25
    assert response.metrics.volatility == 0.21
    assert response.metrics.total_trades == 2
    assert response.metrics_json["calmar"] == 2.25
    assert response.cost_summary_json["total_commission"] == 12.5
    assert response.fills == []


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


def test_market_quote_prefers_persisted_snapshot_without_refresh_when_closed(
    monkeypatch,
):
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
            data_source="akshare",
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

    assert response.quotes[0].symbol == "600519"
    assert response.quotes[0].price == 123.45
    assert response.quotes[0].quote_status == "stale"
    assert response.quotes[0].quote_source == "akshare"
    assert response.quotes[0].quote_age_seconds is not None
    assert response.quotes[0].stale_reason == "market_closed_cache_only"
    assert response.provider_name == "akshare"
    assert response.provider_status == "stale"
    assert response.source_health == "stale"
    assert response.cache_age_seconds is not None
    assert response.latest_quote_timestamp is not None
    assert response.stale_symbols_count == 1
    assert response.stale_symbols_sample == ["600519"]
    assert response.market_open is False
    assert response.refresh_policy == "cache_only"


def test_market_quote_refresh_endpoint_returns_structured_result(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    fake_scheduler = SimpleNamespace(is_running=True, latest_quotes={})
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=fake_scheduler,
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(
        market_routes, "_resolve_quote_status", lambda state, quote: "live"
    )
    monkeypatch.setattr(
        market_routes,
        "_fetch_latest_snapshot",
        lambda state, symbol, asset_class: {
            "symbol": symbol,
            "asset_class": asset_class.value,
            "price": 12.5,
            "volume": 1000.0,
            "timestamp": "2026-05-12T10:05:00+08:00",
        },
    )

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519"]))
    )

    assert response.requested_symbols == ["600519"]
    assert response.quote_status == "live"
    assert response.refresh_policy == "live"
    assert response.refreshed[0].symbol == "600519"
    assert response.refreshed[0].quote_timestamp == "2026-05-12T10:05:00+08:00"
    assert response.refreshed[0].quote_source == "akshare"
    assert response.refreshed[0].quote_age_seconds is not None
    assert response.refreshed[0].last_refresh_attempt is not None
    assert response.last_refresh_attempt == response.started_at
    assert response.last_refresh_error is None
    assert fake_scheduler.latest_quotes["600519"]["price"] == 12.5


def test_market_quote_refresh_defaults_to_holding_symbols(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "示例基金", "asset_class": "fund"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(
            is_running=True,
            latest_quotes={},
            portfolio=SimpleNamespace(positions={"018125": SimpleNamespace()}),
            instruments={},
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(market_routes, "_resolve_quote_status", lambda state, quote: "live")
    monkeypatch.setattr(
        market_routes,
        "_fetch_latest_snapshot",
        lambda state, symbol, asset_class: {
            "symbol": symbol,
            "asset_class": asset_class.value,
            "price": 2.25,
            "volume": 1000.0,
            "timestamp": "2026-05-12T10:05:00+08:00",
        },
    )

    response = asyncio.run(endpoint(market_routes.QuoteRefreshRequest()))

    assert response.requested_symbols == ["018125"]


def test_market_quote_refresh_single_symbol_failure_does_not_500(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[
                {"symbol": "600519", "asset_class": "stock"},
                {"symbol": "000001", "asset_class": "stock"},
            ],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(is_running=True, latest_quotes={}),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )

    def fake_fetch(state, symbol, asset_class):
        if symbol == "000001":
            raise RuntimeError("provider unavailable")
        return {
            "symbol": symbol,
            "asset_class": asset_class.value,
            "price": 12.5,
            "volume": 1000.0,
            "timestamp": "2026-05-12T10:05:00+08:00",
        }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(market_routes, "_resolve_quote_status", lambda state, quote: "live")
    monkeypatch.setattr(market_routes, "_fetch_latest_snapshot", fake_fetch)

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519", "000001"]))
    )

    assert response.quote_status == "partial"
    assert [item.symbol for item in response.refreshed] == ["600519"]
    assert [item.symbol for item in response.failed] == ["000001"]
    assert response.failed[0].reason == "行情源刷新失败，已保留缓存行情"
    assert response.failed[0].last_refresh_error == "provider unavailable"
    assert response.last_refresh_error == "provider unavailable"


def test_market_quote_refresh_cache_only_returns_stale_without_fresh_claim(
    monkeypatch,
):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(is_running=True, latest_quotes={}),
        db=SimpleNamespace(
            get_latest_quotes_sync=lambda: [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 10.0,
                    "volume": 1000.0,
                    "timestamp": "2026-04-22T15:00:00",
                }
            ]
        ),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)
    monkeypatch.setattr(
        market_routes, "_fetch_latest_snapshot", lambda state, symbol, asset_class: None
    )

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519"]))
    )

    assert response.market_open is False
    assert response.refresh_policy == "cache_only"
    assert response.quote_status == "stale"
    assert response.skipped[0].status == "stale"
    assert response.skipped[0].quote_timestamp == "2026-04-22T15:00:00"
    assert response.skipped[0].quote_source == "akshare"
    assert response.skipped[0].quote_age_seconds is not None
    assert response.skipped[0].reason == "行情源没有返回新报价，当前仍基于缓存行情"
    assert response.last_refresh_error is None


def test_market_quote_refresh_times_out_without_blocking_request(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(is_running=True, latest_quotes={}),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )

    def slow_fetch(state, symbol, asset_class):
        time.sleep(0.05)
        return {
            "symbol": symbol,
            "asset_class": asset_class.value,
            "price": 12.5,
            "timestamp": "2026-05-12T10:05:00+08:00",
        }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(market_routes, "_fetch_latest_snapshot", slow_fetch)
    monkeypatch.setattr(market_routes, "_MANUAL_REFRESH_TIMEOUT_SECONDS", 0.001)

    started_at = time.monotonic()
    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519"]))
    )
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert response.quote_status == "error"
    assert response.failed[0].error == "provider_timeout"
    assert response.failed[0].reason == "行情源刷新超时，已保留缓存行情"
    assert response.failed[0].last_refresh_error == "provider_timeout"
    assert response.last_refresh_error == "provider_timeout"


def test_market_research_board_merges_watchlist_and_health(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    board_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/research-board"
    )
    endpoint = board_route.endpoint

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
            latest_quotes={
                "600519": {
                    "timestamp": "2026-04-18T10:00:00",
                    "price": 123.45,
                }
            },
            portfolio=SimpleNamespace(positions={"600519": fake_position}),
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)

    response = asyncio.run(endpoint())

    assert response.items[0].symbol == "600519"
    assert response.items[0].price == 123.45
    assert response.items[0].is_holding is True
    assert response.health.market_open is True


def test_market_research_notes_create_and_list(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    list_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/research-notes"
    )
    create_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/research-notes"
        and "POST" in route.methods
    )

    notes: list[dict] = []

    async def fake_add_research_note(**payload):
        note_id = len(notes) + 1
        notes.append(
            {
                "id": note_id,
                **payload,
                "created_at": "2026-04-20T10:00:00",
                "updated_at": "2026-04-20T10:00:00",
            }
        )
        return note_id

    async def fake_get_research_notes(
        symbol=None,
        entry_kind=None,
        priority=None,
        event_date_from=None,
        event_date_to=None,
        limit=100,
        offset=0,
    ):
        rows = [row for row in notes if symbol is None or row["symbol"] == symbol]
        return list(reversed(rows))[:limit]

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            add_research_note=fake_add_research_note,
            get_research_notes=fake_get_research_notes,
        )
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    created = asyncio.run(
        create_route.endpoint(
            market_routes.ResearchNoteCreate(
                symbol="600519",
                asset_class="stock",
                entry_kind="thesis",
                title="Margin stability",
                content="Premium mix remains resilient.",
                priority="high",
            )
        )
    )
    listed = asyncio.run(list_route.endpoint(symbol="600519", limit=50))

    assert created.id == 1
    assert created.entry_kind == "thesis"
    assert listed.items[0].symbol == "600519"
    assert listed.items[0].title == "Margin stability"


def test_market_research_notes_update_and_filter(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    list_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/research-notes"
    )
    update_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/research-notes/{note_id}"
        and "PUT" in route.methods
    )

    notes = [
        {
            "id": 1,
            "symbol": "600519",
            "asset_class": "stock",
            "entry_kind": "note",
            "title": "Old note",
            "content": "old",
            "priority": "low",
            "event_date": "2026-04-25",
            "created_at": "2026-04-20T10:00:00",
            "updated_at": "2026-04-20T10:00:00",
        }
    ]

    async def fake_update_research_note(**payload):
        for note in notes:
            if note["id"] == payload["note_id"]:
                note.update(
                    entry_kind=payload["entry_kind"],
                    title=payload["title"],
                    content=payload["content"],
                    priority=payload["priority"],
                    event_date=payload["event_date"],
                    updated_at="2026-04-20T11:00:00",
                )
                return True
        return False

    async def fake_get_research_notes(
        symbol=None,
        entry_kind=None,
        priority=None,
        event_date_from=None,
        event_date_to=None,
        limit=100,
        offset=0,
    ):
        rows = list(notes)
        if symbol:
            rows = [row for row in rows if row["symbol"] == symbol]
        if entry_kind:
            rows = [row for row in rows if row["entry_kind"] == entry_kind]
        if priority:
            rows = [row for row in rows if row["priority"] == priority]
        if event_date_from:
            rows = [row for row in rows if (row["event_date"] or "") >= event_date_from]
        if event_date_to:
            rows = [row for row in rows if (row["event_date"] or "") <= event_date_to]
        return rows[:limit]

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            update_research_note=fake_update_research_note,
            get_research_notes=fake_get_research_notes,
        )
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    updated = asyncio.run(
        update_route.endpoint(
            1,
            market_routes.ResearchNoteUpdate(
                entry_kind="catalyst",
                title="Earnings watch",
                content="Track the upcoming print.",
                priority="high",
                event_date="2026-04-28",
            ),
        )
    )
    listed = asyncio.run(
        list_route.endpoint(
            symbol="600519",
            entry_kind="catalyst",
            priority="high",
            event_date_from="2026-04-27",
            event_date_to="2026-04-29",
            limit=50,
        )
    )

    assert updated.title == "Earnings watch"
    assert listed.items[0].entry_kind == "catalyst"
    assert listed.items[0].priority == "high"


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
            portfolio=SimpleNamespace(
                positions={"永赢先进制造智选混合C": fake_position}
            ),
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


def test_fetch_latest_snapshot_falls_back_to_akshare_for_fund_when_tushare_returns_none(
    monkeypatch,
):
    from server.routes import market as market_routes

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="tushare",
            tushare_token="token-1234",
            assets=[{"symbol": "018125", "asset_class": "fund"}],
            live_poll_interval=120,
        ),
        db=SimpleNamespace(
            save_quote_snapshot_sync=lambda **kwargs: None,
        ),
    )

    class NullSource:
        def fetch_latest(self, symbol, asset_class):
            return None

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 1.126,
                "volume": None,
                "timestamp": "2026-04-21",
                "previous_close": 1.103,
                "previous_close_date": "2026-04-18",
            }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {
            "tushare": NullSource(),
            "akshare": AkshareSource(),
        },
    )

    response = market_routes._fetch_latest_snapshot(
        fake_state, "018125", market_routes.AssetClass.FUND
    )

    assert response["asset_class"] == "fund"
    assert response["price"] == 1.126
    assert response["timestamp"] == "2026-04-21"
    assert response["previous_close"] == 1.103
    assert response["previous_close_date"] == "2026-04-18"


def test_fetch_latest_snapshot_persists_reported_previous_close(monkeypatch):
    from server.routes import market as market_routes

    saved_quote: dict[str, object] = {}
    saved_close: dict[str, object] = {}

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "018125", "asset_class": "fund"}],
            live_poll_interval=120,
        ),
        db=SimpleNamespace(
            save_quote_snapshot_sync=lambda **kwargs: saved_quote.update(kwargs),
            save_daily_close_snapshot_sync=lambda **kwargs: saved_close.update(kwargs),
        ),
    )

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 2.2503,
                "volume": None,
                "timestamp": "2026-04-22",
                "previous_close": 2.2606,
                "previous_close_date": "2026-04-21",
            }

    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": AkshareSource()},
    )

    response = market_routes._fetch_latest_snapshot(
        fake_state, "018125", market_routes.AssetClass.FUND
    )

    assert response["price"] == 2.2503
    assert saved_quote["timestamp"] == "2026-04-22"
    assert saved_close == {
        "symbol": "018125",
        "asset_class": "fund",
        "trade_date": "2026-04-21",
        "close_price": 2.2606,
        "source": "reported_previous_close",
    }


def test_portfolio_live_holdings_prefers_reported_previous_close_from_latest_quote(
    monkeypatch,
):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )

    fake_position = SimpleNamespace(
        quantity=456.31067961165047,
        available_qty=456.31067961165047,
        frozen_qty=0.0,
        avg_cost=1.0,
        market_value=456.31067961165047 * 2.2503,
        unrealized_pnl=456.31067961165047 * (2.2503 - 1.0),
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=4000),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=0.0, positions={"018125": fake_position}),
            instruments={
                "018125": SimpleNamespace(
                    name="永赢先进制造智选混合发起C",
                    asset_class=SimpleNamespace(value="fund"),
                )
            },
            watchlist=[("018125", SimpleNamespace(value="fund"))],
            latest_quotes={
                "018125": {
                    "symbol": "018125",
                    "asset_class": "fund",
                    "price": 2.2503,
                    "volume": None,
                    "timestamp": "2026-04-22",
                    "previous_close": 2.2606,
                    "previous_close_date": "2026-04-21",
                }
            },
        ),
        db=None,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(live_holdings_route.endpoint())

    assert response.groups[0].items[0].baseline_source == "previous_close"
    assert response.groups[0].items[0].baseline_price == pytest.approx(2.2606)
    assert response.groups[0].items[0].today_change == pytest.approx(-4.70, abs=0.01)
    assert response.groups[0].items[0].today_change_pct == pytest.approx(
        -0.004556312483411484
    )


def test_market_watchlist_prefers_display_name_from_config(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    watchlist_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/watchlist"
    )
    endpoint = watchlist_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[
                {
                    "symbol": "018125",
                    "asset_class": "fund",
                    "display_name": "永赢先进制造智选混合发起C",
                }
            ]
        ),
        scheduler=SimpleNamespace(is_running=False, latest_quotes={}, portfolio=None),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response[0].symbol == "018125"
    assert response[0].name == "永赢先进制造智选混合发起C"


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
        add_route.endpoint(
            market_routes.WatchlistCreateRequest(symbol="510300", asset_class="etf")
        )
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


def test_portfolio_snapshot_prefers_display_name_from_config(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    portfolio_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )
    endpoint = portfolio_route.endpoint

    fake_position = SimpleNamespace(
        quantity=1000,
        available_qty=1000,
        frozen_qty=0,
        avg_cost=1.0,
        market_value=1126.0,
        unrealized_pnl=126.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=4000,
            data_source="akshare",
            tushare_token="",
            assets=[
                {
                    "symbol": "018125",
                    "asset_class": "fund",
                    "display_name": "永赢先进制造智选混合发起C",
                }
            ],
        ),
        db=SimpleNamespace(get_total_deposits=AsyncMock(return_value=0.0)),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=2500.0, positions={"018125": fake_position}),
            latest_quotes={},
            watchlist=[(Symbol("018125"), SimpleNamespace(value="fund"))],
            instruments={
                Symbol("018125"): SimpleNamespace(
                    asset_class=SimpleNamespace(value="fund"), name="018125"
                )
            },
        ),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.allocation[1].symbol == "018125"
    assert response.allocation[1].name == "永赢先进制造智选混合发起C"


def test_portfolio_snapshot_hydrates_missing_fund_quotes_outside_trading_hours(
    monkeypatch,
):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    portfolio_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )
    endpoint = portfolio_route.endpoint

    fake_position = SimpleNamespace(
        quantity=1000,
        available_qty=1000,
        frozen_qty=0,
        avg_cost=1.0,
        market_value=1000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )

    class FakeDb:
        async def get_total_deposits(self):
            return 0.0

        def get_latest_quotes_sync(self):
            return []

        def save_quote_snapshot_sync(self, **kwargs):
            return None

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=4000,
            data_source="akshare",
            tushare_token="",
            assets=[
                {
                    "symbol": "018125",
                    "asset_class": "fund",
                    "display_name": "永赢先进制造智选混合发起C",
                }
            ],
        ),
        db=FakeDb(),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=2500.0, positions={"018125": fake_position}),
            latest_quotes={},
            watchlist=[(Symbol("018125"), SimpleNamespace(value="fund"))],
            instruments={
                Symbol("018125"): SimpleNamespace(
                    asset_class=SimpleNamespace(value="fund"),
                    name="018125",
                )
            },
        ),
    )

    def fake_rebuild(config, db, latest_quotes):
        price = latest_quotes["018125"]["price"]
        return SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=2500.0,
                positions={
                    "018125": SimpleNamespace(
                        quantity=1000,
                        available_qty=1000,
                        frozen_qty=0,
                        avg_cost=1.0,
                        market_value=price * 1000,
                        unrealized_pnl=(price - 1.0) * 1000,
                        realized_pnl=0.0,
                        commission_paid=0.0,
                    )
                },
            ),
            instruments=fake_state.scheduler.instruments,
        )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.market._fetch_latest_snapshot",
        lambda state, symbol, asset_class: {
            "symbol": symbol,
            "asset_class": "fund",
            "price": 1.126,
            "volume": None,
            "timestamp": "2026-04-22",
        },
    )
    monkeypatch.setattr(
        "server.routes.portfolio.rebuild_portfolio_from_ledger",
        fake_rebuild,
    )

    response = asyncio.run(endpoint())

    assert response.total_equity == 3626.0
    assert response.positions[0].market_value == 1126.0
    assert response.positions[0].unrealized_pnl == pytest.approx(126.0)


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


def test_portfolio_explainability_uses_snapshot_and_ledger(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    explain_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/explainability"
    )
    endpoint = explain_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=1500,
        unrealized_pnl=200,
        realized_pnl=50,
        commission_paid=3,
    )

    async def fake_get_total_deposits():
        return 1000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=SimpleNamespace(
            get_total_deposits=fake_get_total_deposits,
            get_latest_quotes_sync=lambda: [],
            get_ledger_entries_sync=lambda limit=12, offset=0: [
                {
                    "id": 1,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-18T10:00:00+00:00",
                    "symbol": "600519",
                    "direction": "buy",
                    "quantity": 100.0,
                    "price": 10.0,
                    "commission": 3.0,
                    "asset_class": "stock",
                    "note": "first build",
                    "source": "manual",
                    "source_ref": None,
                    "created_at": "2026-04-18T10:00:01+00:00",
                }
            ],
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=500,
                positions={"600519": fake_position},
                equity_curve=[
                    (
                        datetime.fromisoformat("2026-04-17T00:00:00+00:00"),
                        Decimal("1400"),
                    ),
                    (
                        datetime.fromisoformat("2026-04-18T00:00:00+00:00"),
                        Decimal("2000"),
                    ),
                ],
            ),
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.equity_bridge[-1].label == "Total Equity"
    assert response.recent_drivers[0].title == "Bought 600519"
    assert response.positions[0].symbol == "600519"
    assert response.timeline[-1].date == "2026-04-18"
    assert response.timeline[-1].market_pnl == 600


def test_portfolio_explainability_filters_timeline(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    explain_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/explainability"
    )
    endpoint = explain_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=1500,
        unrealized_pnl=200,
        realized_pnl=50,
        commission_paid=3,
    )

    async def fake_get_total_deposits():
        return 1000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=SimpleNamespace(
            get_total_deposits=fake_get_total_deposits,
            get_latest_quotes_sync=lambda: [],
            get_ledger_entries_sync=lambda limit=50, offset=0: [
                {
                    "id": 1,
                    "entry_type": "dividend",
                    "timestamp": "2026-04-18T10:00:00+00:00",
                    "symbol": "600519",
                    "amount": 20.0,
                    "note": "cash income",
                },
                {
                    "id": 2,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-19T10:00:00+00:00",
                    "symbol": "600519",
                    "quantity": 100.0,
                    "price": 10.0,
                    "note": "added",
                },
            ],
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=500,
                positions={"600519": fake_position},
                equity_curve=[
                    (
                        datetime.fromisoformat("2026-04-18T00:00:00+00:00"),
                        Decimal("1400"),
                    ),
                    (
                        datetime.fromisoformat("2026-04-19T00:00:00+00:00"),
                        Decimal("2000"),
                    ),
                ],
            ),
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(
        endpoint(
            limit=50,
            from_date="2026-04-19",
            to_date="2026-04-19",
            event_kind="trade_buy",
        )
    )

    assert len(response.timeline) == 1
    assert response.timeline[0].date == "2026-04-19"
    assert response.timeline[0].events[0].category == "trade"


def test_portfolio_risk_workspace_returns_drawdown_and_concentration(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    workspace_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/risk-workspace"
    )
    endpoint = workspace_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=1200,
        unrealized_pnl=180,
        realized_pnl=50,
        commission_paid=3,
    )

    async def fake_get_total_deposits():
        return 1000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=SimpleNamespace(get_total_deposits=fake_get_total_deposits),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=800,
                positions={"600519": fake_position},
                equity_curve=[
                    (
                        datetime.fromisoformat("2026-04-17T00:00:00+00:00"),
                        Decimal("2200"),
                    ),
                    (
                        datetime.fromisoformat("2026-04-18T00:00:00+00:00"),
                        Decimal("2000"),
                    ),
                ],
            ),
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.drawdown.max_drawdown > 0
    assert response.metrics[0].key == "current_drawdown"
    assert response.exposure_buckets[0].positions_count == 1
    assert response.concentration[0].symbol == "600519"


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
        scheduler=SimpleNamespace(
            portfolio=None, latest_quotes={}, watchlist=[], instruments={}
        ),
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
    assert {
        item.asset_class for item in response.allocation if item.symbol != "CASH"
    } == {"fund"}


def test_portfolio_trade_auto_confirms_fund_buy_from_amount(monkeypatch, tmp_path):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    trade_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/trade"
    )

    class FakeDb:
        def __init__(self):
            self.trades: list[dict] = []
            self.ledger_entries: list[dict] = []

        async def add_trade(self, **payload):
            trade_id = len(self.trades) + 1
            self.trades.insert(
                0,
                {
                    "id": trade_id,
                    **payload,
                    "created_at": "2026-04-22T14:46:01",
                },
            )
            return trade_id

        def insert_ledger_entry_sync(self, **payload):
            self.ledger_entries.append(payload)

        async def get_trades(self, limit=50, offset=0):
            return self.trades[offset : offset + limit]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            host="0.0.0.0",
            port=8000,
            live_auto_start=True,
            initial_cash=4000,
            start_date="2025-01-02",
            end_date="2026-04-22",
            assets=[],
            strategy="dual_ma",
            short_period=5,
            long_period=20,
            data_source="akshare",
            tushare_token="",
            notification={"type": "console"},
            live_poll_interval=120,
        ),
        scheduler=SimpleNamespace(is_running=False),
        db=FakeDb(),
    )

    class FakeAkshareSource:
        def _resolve_open_end_fund_name(self, symbol):
            return "华夏核心成长混合C"

        def _resolve_open_end_fund_code(self, symbol):
            return "012710"

        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            import pandas as pd

            return pd.DataFrame(
                {
                    "timestamp": pd.to_datetime(["2026-04-22", "2026-04-23"]),
                    "close": [1.0107, 1.0200],
                }
            )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeAkshareSource()},
    )
    monkeypatch.setattr(
        portfolio_routes, "_persist_runtime_config", lambda config: None
    )

    response = asyncio.run(
        trade_route.endpoint(
            portfolio_routes.TradeCreate(
                timestamp="2026-04-22T14:46:00",
                symbol="012710",
                direction="buy",
                amount=200.0,
                asset_class="fund",
            )
        )
    )

    assert response.symbol == "012710"
    assert response.price == pytest.approx(1.0107)
    assert response.quantity == pytest.approx(200 / 1.0107)
    assert "confirmed_trade_date=2026-04-22" in response.note
    assert fake_state.config.assets[0]["display_name"] == "华夏核心成长混合C"


def test_portfolio_trade_returns_pending_when_fund_nav_not_published(
    monkeypatch, tmp_path
):
    import json

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    trade_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/trade"
    )

    class FakeDb:
        def __init__(self):
            self.pending_orders: list[dict] = []

        def add_pending_fund_order_sync(self, **payload):
            order_id = len(self.pending_orders) + 1
            self.pending_orders.append({"id": order_id, **payload})
            return order_id

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            host="0.0.0.0",
            port=8000,
            live_auto_start=True,
            initial_cash=4000,
            start_date="2025-01-02",
            end_date="2026-04-23",
            assets=[],
            strategy="dual_ma",
            short_period=5,
            long_period=20,
            data_source="akshare",
            tushare_token="",
            notification={"type": "console"},
            live_poll_interval=120,
        ),
        scheduler=SimpleNamespace(is_running=False),
        db=FakeDb(),
    )

    class FakeAkshareSource:
        def _resolve_open_end_fund_name(self, symbol):
            return "华夏核心成长混合C"

        def _resolve_open_end_fund_code(self, symbol):
            return "012710"

        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            import pandas as pd

            return pd.DataFrame(
                {
                    "timestamp": pd.to_datetime(["2026-04-22"]),
                    "close": [1.0107],
                }
            )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeAkshareSource()},
    )
    monkeypatch.setattr(
        portfolio_routes, "_persist_runtime_config", lambda config: None
    )

    response = asyncio.run(
        trade_route.endpoint(
            portfolio_routes.TradeCreate(
                timestamp="2026-04-23T14:46:00",
                symbol="012710",
                direction="buy",
                amount=200.0,
                asset_class="fund",
            )
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 202
    assert payload["status"] == "pending"
    assert payload["target_trade_date"] == "2026-04-23"
    assert "2026-04-23" in payload["detail"]
    assert fake_state.config.assets[0]["symbol"] == "012710"


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
        if isinstance(route, APIRoute)
        and route.path == "/api/signals/actions/{action_id}"
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


def test_portfolio_equity_curve_uses_ledger_projection_when_scheduler_missing(
    monkeypatch,
):
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
        config=SimpleNamespace(initial_cash=0, data_source="akshare"),
        scheduler=SimpleNamespace(
            portfolio=None, latest_quotes={}, watchlist=[], instruments={}
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    curve = asyncio.run(endpoint())

    assert len(curve) == 2
    assert curve[0].equity == 100000.0
    assert curve[-1].equity > curve[0].equity


def test_portfolio_equity_curve_series_groups_asset_buckets(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    curve_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/equity-curve/series"
    )
    endpoint = curve_route.endpoint

    class FakeDb:
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
                    "asset_class": "cash",
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
                    "commission": 0.0,
                    "asset_class": "stock",
                    "note": "",
                    "source": "manual",
                    "source_ref": "stock-1",
                    "created_at": "2026-04-18T10:00:01+00:00",
                },
                {
                    "id": 3,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-18T11:00:00+00:00",
                    "amount": 2000.0,
                    "symbol": "018125",
                    "direction": "buy",
                    "quantity": 1000.0,
                    "price": 2.0,
                    "commission": 0.0,
                    "asset_class": "fund",
                    "note": "",
                    "source": "manual",
                    "source_ref": "fund-1",
                    "created_at": "2026-04-18T11:00:01+00:00",
                },
                {
                    "id": 4,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-18T12:00:00+00:00",
                    "amount": 3000.0,
                    "symbol": "510300",
                    "direction": "buy",
                    "quantity": 1000.0,
                    "price": 3.0,
                    "commission": 0.0,
                    "asset_class": "etf",
                    "note": "",
                    "source": "manual",
                    "source_ref": "etf-1",
                    "created_at": "2026-04-18T12:00:01+00:00",
                },
                {
                    "id": 5,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-18T13:00:00+00:00",
                    "amount": 5000.0,
                    "symbol": "BOND1",
                    "direction": "buy",
                    "quantity": 50.0,
                    "price": 100.0,
                    "commission": 0.0,
                    "asset_class": "bond",
                    "note": "",
                    "source": "manual",
                    "source_ref": "bond-1",
                    "created_at": "2026-04-18T13:00:01+00:00",
                },
                {
                    "id": 6,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-18T14:00:00+00:00",
                    "amount": 4000.0,
                    "symbol": "GOLD1",
                    "direction": "buy",
                    "quantity": 2.0,
                    "price": 2000.0,
                    "commission": 0.0,
                    "asset_class": "gold",
                    "note": "",
                    "source": "manual",
                    "source_ref": "gold-1",
                    "created_at": "2026-04-18T14:00:01+00:00",
                },
            ]

        def get_latest_quotes_sync(self):
            return [
                {"symbol": "600519", "price": 1100.0, "asset_class": "stock"},
                {"symbol": "018125", "price": 2.1, "asset_class": "fund"},
                {"symbol": "510300", "price": 3.2, "asset_class": "etf"},
                {"symbol": "BOND1", "price": 101.0, "asset_class": "bond"},
                {"symbol": "GOLD1", "price": 2100.0, "asset_class": "gold"},
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0, data_source="akshare"),
        scheduler=SimpleNamespace(
            portfolio=None, latest_quotes={}, watchlist=[], instruments={}
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    series = asyncio.run(endpoint())

    assert len(series) == 7
    assert series[0].total == 100000.0
    assert series[0].cash == 100000.0
    assert series[-2].stocks == pytest.approx(11000.0)
    assert series[-2].funds == pytest.approx(5300.0)
    assert series[-2].others == pytest.approx(9250.0)
    assert series[-2].cash == pytest.approx(76000.0)
    assert series[-2].total == pytest.approx(101550.0)
    assert series[-1].timestamp > series[-2].timestamp
    assert series[-1].total == pytest.approx(series[-2].total)
    assert series[-1].quote_status == "stale"


def test_portfolio_equity_curve_series_uses_intraday_mtm_for_1d(monkeypatch):
    from zoneinfo import ZoneInfo

    import pandas as pd

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    curve_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/equity-curve/series"
    )
    endpoint = curve_route.endpoint

    class FakeDb:
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
                    "asset_class": "cash",
                    "note": "",
                    "source": "manual",
                    "source_ref": "deposit-1",
                    "created_at": "2026-04-18T09:00:01+00:00",
                }
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 1010.0,
                    "timestamp": "2026-04-18T09:40:00",
                    "previous_close": 1000.0,
                    "previous_close_date": "2026-04-17",
                },
                {
                    "symbol": "510300",
                    "asset_class": "etf",
                    "price": 3.2,
                    "timestamp": "2026-04-18T09:40:00",
                    "previous_close": 3.0,
                    "previous_close_date": "2026-04-17",
                },
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 0.0

    fake_portfolio = SimpleNamespace(
        cash=76000.0,
        positions={
            "600519": SimpleNamespace(quantity=10.0, avg_cost=1000.0),
            "510300": SimpleNamespace(quantity=1000.0, avg_cost=3.0),
        },
    )
    fake_instruments = {
        Symbol("600519"): SimpleNamespace(asset_class=SimpleNamespace(value="stock")),
        Symbol("510300"): SimpleNamespace(asset_class=SimpleNamespace(value="etf")),
    }

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=0,
            data_source="akshare",
            tushare_token="",
            assets=[],
        ),
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            instruments=fake_instruments,
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    class FakeSource:
        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            if str(symbol) == "600519":
                return pd.DataFrame(
                    {
                        "timestamp": pd.to_datetime(
                            ["2026-04-18T09:35:00", "2026-04-18T09:40:00"]
                        ),
                        "close": [1005.0, 1010.0],
                    }
                )
            if str(symbol) == "510300":
                return pd.DataFrame(
                    {
                        "timestamp": pd.to_datetime(
                            ["2026-04-18T09:35:00", "2026-04-18T09:40:00"]
                        ),
                        "close": [3.1, 3.2],
                    }
                )
            raise AssertionError(f"unexpected symbol {symbol}")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeSource()},
    )
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 4, 18, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    series = asyncio.run(endpoint("1d"))

    assert [point.timestamp[11:16] for point in series] == [
        "09:30",
        "09:35",
        "09:40",
        "09:45",
    ]
    assert series[0].stocks == pytest.approx(10000.0)
    assert series[0].funds == pytest.approx(3000.0)
    assert series[0].cash == pytest.approx(76000.0)
    assert series[0].total == pytest.approx(89000.0)
    assert series[1].total == pytest.approx(89150.0)
    assert series[2].total == pytest.approx(89300.0)
    assert series[-1].total == pytest.approx(89300.0)
    assert series[-1].unrealized_pnl == pytest.approx(300.0)


def test_portfolio_equity_curve_series_1d_falls_back_to_flat_previous_close(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    import pandas as pd

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    curve_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/equity-curve/series"
    )
    endpoint = curve_route.endpoint

    class FakeDb:
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
                    "asset_class": "cash",
                    "note": "",
                    "source": "manual",
                    "source_ref": "deposit-1",
                    "created_at": "2026-04-18T09:00:01+00:00",
                }
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 1000.0,
                    "timestamp": "2026-04-18T09:20:00",
                    "previous_close": 1000.0,
                    "previous_close_date": "2026-04-17",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return {
                "symbol": symbol,
                "trade_date": "2026-04-17",
                "close_price": 1000.0,
            }

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

    fake_portfolio = SimpleNamespace(
        cash=50000.0,
        positions={"600519": SimpleNamespace(quantity=10.0, avg_cost=1000.0)},
    )
    fake_instruments = {
        Symbol("600519"): SimpleNamespace(asset_class=SimpleNamespace(value="stock")),
    }
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=0,
            data_source="akshare",
            tushare_token="",
            assets=[],
        ),
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            instruments=fake_instruments,
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    class FakeSource:
        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            return pd.DataFrame(columns=["timestamp", "close"])

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeSource()},
    )
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 4, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    series = asyncio.run(endpoint("1d"))

    assert series[0].timestamp.startswith("2026-04-18T09:30:00")
    assert series[-1].timestamp.startswith("2026-04-18T15:00:00")
    assert all(point.total == pytest.approx(60000.0) for point in series)
    assert all(point.unrealized_pnl == pytest.approx(0.0) for point in series)


def test_portfolio_live_holdings_groups_positions_and_computes_returns(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )
    overview_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/overview"
    )

    fake_position = SimpleNamespace(
        quantity=100.0,
        available_qty=100.0,
        frozen_qty=0.0,
        avg_cost=10.0,
        market_value=1200.0,
        unrealized_pnl=200.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    fake_portfolio = SimpleNamespace(cash=500.0, positions={"510300": fake_position})
    fake_instrument = SimpleNamespace(
        name="CSI 300 ETF",
        asset_class=SimpleNamespace(value="etf"),
    )

    class FakeDb:
        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "510300",
                    "asset_class": "etf",
                    "price": 12.0,
                    "volume": 1000.0,
                    "timestamp": "2026-04-21T14:30:00",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            assert symbol == "510300"
            assert trade_date == "2026-04-21"
            return {
                "symbol": "510300",
                "asset_class": "etf",
                "trade_date": "2026-04-20",
                "close_price": 11.5,
                "source": "scheduler_close",
                "captured_at": "2026-04-20T15:01:00",
            }

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 0.0

        def save_daily_close_snapshot_sync(self, **kwargs):
            raise AssertionError(
                "should not persist fallback when previous close exists"
            )

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=100000),
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            instruments={"510300": fake_instrument},
            watchlist=[("510300", SimpleNamespace(value="etf"))],
            latest_quotes={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(live_holdings_route.endpoint())

    assert response.groups[0].asset_class == "etf"
    assert response.groups[0].label == "ETF"
    assert response.groups[0].total_market_value == 1200.0
    assert response.groups[0].total_today_change == 50.0
    assert response.groups[0].total_since_buy_pnl == 200.0
    assert response.groups[0].items[0].symbol == "510300"
    assert response.groups[0].items[0].latest_price == 12.0
    assert response.groups[0].items[0].today_change == 50.0
    assert response.groups[0].items[0].today_change_pct == 12.0 / 11.5 - 1
    assert response.groups[0].items[0].since_buy_pnl == 200.0
    assert response.groups[0].items[0].since_buy_pnl_pct == 0.2
    assert response.groups[0].items[0].baseline_source == "previous_close"


def test_portfolio_live_holdings_falls_back_to_previous_quote_close(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )

    fake_position = SimpleNamespace(
        quantity=50.0,
        available_qty=50.0,
        frozen_qty=0.0,
        avg_cost=20.0,
        market_value=1050.0,
        unrealized_pnl=50.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    fake_portfolio = SimpleNamespace(cash=0.0, positions={"159915": fake_position})
    fake_instrument = SimpleNamespace(
        name="ChiNext ETF",
        asset_class=SimpleNamespace(value="etf"),
    )
    persisted: dict[str, object] = {}

    class FakeDb:
        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "159915",
                    "asset_class": "etf",
                    "price": 21.0,
                    "volume": 500.0,
                    "timestamp": "2026-04-21T14:30:00",
                },
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return {
                "symbol": "159915",
                "asset_class": "etf",
                "price": 20.5,
                "volume": 450.0,
                "timestamp": "2026-04-18T15:00:00",
            }

        def save_daily_close_snapshot_sync(self, **kwargs):
            persisted.update(kwargs)

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=100000),
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            instruments={"159915": fake_instrument},
            watchlist=[("159915", SimpleNamespace(value="etf"))],
            latest_quotes={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(live_holdings_route.endpoint())

    assert response.groups[0].items[0].baseline_source == "fallback_close"
    assert response.groups[0].items[0].today_change == 25.0
    assert persisted["trade_date"] == "2026-04-18"
    assert persisted["close_price"] == 20.5
    assert persisted["source"] == "quote_fallback"


def test_portfolio_live_holdings_marks_missing_baseline(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )

    fake_position = SimpleNamespace(
        quantity=10.0,
        available_qty=10.0,
        frozen_qty=0.0,
        avg_cost=100.0,
        market_value=980.0,
        unrealized_pnl=-20.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    fake_portfolio = SimpleNamespace(cash=0.0, positions={"600519": fake_position})
    fake_instrument = SimpleNamespace(
        name="Kweichow Moutai",
        asset_class=SimpleNamespace(value="stock"),
    )

    class FakeDb:
        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 98.0,
                    "volume": 100.0,
                    "timestamp": "2026-04-21T10:30:00",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 0.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=100000),
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            instruments={"600519": fake_instrument},
            watchlist=[("600519", SimpleNamespace(value="stock"))],
            latest_quotes={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(live_holdings_route.endpoint())

    assert response.groups[0].asset_class == "stock"
    assert response.groups[0].items[0].today_change is None
    assert response.groups[0].items[0].today_change_pct is None
    assert response.groups[0].items[0].baseline_source == "unavailable"


def test_portfolio_refreshes_stale_quote_and_revalues_snapshot(monkeypatch):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    snapshot_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )

    stale_position = SimpleNamespace(
        quantity=100.0,
        available_qty=100.0,
        frozen_qty=0.0,
        avg_cost=10.0,
        market_value=1000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    refreshed_position = SimpleNamespace(
        quantity=100.0,
        available_qty=100.0,
        frozen_qty=0.0,
        avg_cost=10.0,
        market_value=1250.0,
        unrealized_pnl=250.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    fake_instruments = {
        Symbol("600519"): SimpleNamespace(
            name="Kweichow Moutai",
            asset_class=SimpleNamespace(value="stock"),
        )
    }

    class FakeDb:
        def __init__(self):
            self.latest_price = 10.0

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": self.latest_price,
                    "volume": 1000.0,
                    "timestamp": (
                        "2026-04-22T15:00:00"
                        if self.latest_price == 10.0
                        else "2026-05-12T10:05:00+08:00"
                    ),
                }
            ]

        def save_quote_snapshot_sync(self, **kwargs):
            self.latest_price = float(kwargs["price"])

        def get_cash_flows_sync(self, limit=1, offset=0):
            return []

        def get_trades_sync(self, limit=1, offset=0):
            return []

        def get_ledger_entries_sync(self, limit=1, offset=0):
            return [{"id": 1}]

        async def get_total_deposits(self):
            return 0.0

    fake_db = FakeDb()
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=0,
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=0.0,
                positions={"600519": stale_position},
            ),
            instruments=fake_instruments,
            watchlist=[("600519", SimpleNamespace(value="stock"))],
            latest_quotes={},
        ),
        db=fake_db,
    )

    class FakeSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 12.5,
                "volume": 2000.0,
                "timestamp": "2026-05-12T10:05:00+08:00",
            }

    def fake_rebuild_portfolio_from_ledger(config, db, latest_quotes):
        assert latest_quotes["600519"]["price"] == 12.5
        return SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=0.0,
                positions={"600519": refreshed_position},
                total_deposits=0.0,
            ),
            instruments=fake_instruments,
        )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 5, 12, 10, 6, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    monkeypatch.setattr(
        "server.routes.market.is_cn_trading_session",
        lambda now=None: True,
    )
    monkeypatch.setattr(
        portfolio_routes,
        "rebuild_portfolio_from_ledger",
        fake_rebuild_portfolio_from_ledger,
    )
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeSource()},
    )

    response = asyncio.run(snapshot_route.endpoint())

    assert response.positions[0].market_value == 1250.0
    assert response.positions[0].unrealized_pnl == 250.0
    assert response.positions[0].quote_status == "live"
    assert response.positions[0].quote_timestamp == "2026-05-12T10:05:00+08:00"


def test_portfolio_live_holdings_marks_cached_stale_quote_when_market_closed(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )
    overview_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/overview"
    )

    fake_position = SimpleNamespace(
        quantity=100.0,
        available_qty=100.0,
        frozen_qty=0.0,
        avg_cost=10.0,
        market_value=1200.0,
        unrealized_pnl=200.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )

    class FakeDb:
        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 12.0,
                    "volume": 1000.0,
                    "timestamp": "2026-04-22T15:00:00",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 0.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0, data_source="akshare"),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=0.0, positions={"600519": fake_position}),
            instruments={
                "600519": SimpleNamespace(
                    name="Kweichow Moutai",
                    asset_class=SimpleNamespace(value="stock"),
                )
            },
            watchlist=[("600519", SimpleNamespace(value="stock"))],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 5, 12, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    monkeypatch.setattr(
        "server.routes.market.is_cn_trading_session",
        lambda now=None: False,
    )

    response = asyncio.run(live_holdings_route.endpoint())
    overview = asyncio.run(overview_route.endpoint())

    assert response.groups[0].items[0].quote_status == "stale"
    assert response.groups[0].items[0].quote_timestamp == "2026-04-22T15:00:00"
    assert response.groups[0].items[0].quote_source == "akshare"
    assert response.groups[0].items[0].quote_age_seconds is not None
    assert response.groups[0].items[0].stale_reason == "market_closed_cache_only"
    assert response.groups[0].items[0].refresh_policy == "cache_only"
    assert overview.quote_status == "stale"
    assert overview.quote_age_seconds is not None
    assert overview.stale_reason == "market_closed_cache_only"
    assert overview.refresh_policy == "cache_only"


def test_portfolio_equity_curve_series_appends_current_valuation_point(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    curve_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/equity-curve/series"
    )

    class FakeDb:
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
                    "asset_class": "cash",
                    "note": "",
                    "source": "manual",
                    "source_ref": "deposit-1",
                    "created_at": "2026-04-18T09:00:01+00:00",
                },
                {
                    "id": 2,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-04-22T10:00:00+00:00",
                    "amount": 1000.0,
                    "symbol": "600519",
                    "direction": "buy",
                    "quantity": 100.0,
                    "price": 10.0,
                    "commission": 0.0,
                    "asset_class": "stock",
                    "note": "",
                    "source": "manual",
                    "source_ref": "stock-1",
                    "created_at": "2026-04-22T10:00:01+00:00",
                },
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 12.0,
                    "volume": 1000.0,
                    "timestamp": "2026-04-22T15:00:00",
                }
            ]

    fake_position = SimpleNamespace(
        quantity=100.0,
        avg_cost=10.0,
        market_value=1200.0,
        unrealized_pnl=200.0,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=99000.0,
                positions={"600519": fake_position},
            ),
            instruments={
                Symbol("600519"): SimpleNamespace(
                    asset_class=SimpleNamespace(value="stock")
                )
            },
            watchlist=[("600519", SimpleNamespace(value="stock"))],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 5, 12, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    series = asyncio.run(curve_route.endpoint("1m"))

    assert series[-1].timestamp.startswith("2026-05-12T20:00:00")
    assert series[-1].total == 100200.0
    assert series[-1].stocks == 1200.0
    assert series[-1].cash == 99000.0
    assert series[-1].quote_status == "stale"


def test_portfolio_equity_curve_series_1d_falls_back_when_intraday_source_blocks(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    curve_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/portfolio/equity-curve/series"
    )

    fake_position = SimpleNamespace(
        quantity=100.0,
        avg_cost=10.0,
        market_value=1200.0,
        unrealized_pnl=200.0,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=0,
            data_source="akshare",
            tushare_token="",
            intraday_curve_timeout_seconds=0.01,
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=99000.0,
                positions={"600519": fake_position},
            ),
            instruments={
                Symbol("600519"): SimpleNamespace(
                    asset_class=SimpleNamespace(value="stock")
                )
            },
            latest_quotes={},
        ),
        db=SimpleNamespace(
            get_latest_quotes_sync=lambda: [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 12.0,
                    "volume": 1000.0,
                    "timestamp": "2026-05-12T09:59:00+08:00",
                }
            ]
        ),
    )

    class BlockingSource:
        def fetch_latest(self, symbol, asset_class):
            raise AssertionError("fresh quote should not be required")

        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            import time as time_module

            time_module.sleep(0.2)
            raise AssertionError("slow source should not control response")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": BlockingSource()},
    )
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    series = asyncio.run(curve_route.endpoint("1d"))

    assert len(series) == 1
    assert series[0].timestamp.startswith("2026-05-12T10:00:00")
    assert series[0].total == 100200.0
