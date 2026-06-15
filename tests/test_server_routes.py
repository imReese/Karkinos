from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from fastapi.routing import APIRoute

from core.types import Symbol


@pytest.fixture(autouse=True)
def _isolate_runtime_config_path(monkeypatch, tmp_path):
    """Route tests must never read or write the developer's real config.json."""
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(tmp_path / "config-test.json"))


@pytest.fixture(autouse=True)
def _run_market_fetch_inline(monkeypatch, request):
    """Keep route tests deterministic; timeout cases override this fixture."""
    test_name = request.node.name
    if not (
        test_name.startswith("test_market_")
        or test_name.startswith("test_refresh_one_quote_")
    ):
        return

    from server.routes import market as market_routes

    async def inline_fetch(func, *args):
        return func(*args)

    monkeypatch.setattr(market_routes, "_run_blocking_fetch", inline_fetch)


@pytest.fixture(autouse=True)
def _run_portfolio_curve_inline(monkeypatch, request):
    """Avoid thread-pool hangs in deterministic route tests; timeout cases opt out."""
    test_name = request.node.name
    if not test_name.startswith("test_portfolio_equity_curve_series_"):
        return
    if test_name.endswith("_blocks"):
        return

    from server.routes import portfolio as portfolio_routes

    async def inline_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(portfolio_routes.asyncio, "to_thread", inline_thread)


def _backtest_route(router, path: str, method: str = "GET"):
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_asset_metadata_resolver_accepts_supported_config_shapes():
    from server.services.asset_metadata import (
        build_asset_metadata_status,
        resolve_asset_metadata,
    )

    state = SimpleNamespace(
        config=SimpleNamespace(
            instruments=[
                {
                    "symbol": "018125",
                    "asset_class": "fund",
                    "display_name": "示例基金A",
                    "provider_symbol": "018125.OF",
                    "aliases": ["018125"],
                }
            ],
            assets={
                "026539": {
                    "asset_class": "fund",
                    "display_name": "示例基金B",
                    "provider_symbol": "026539",
                },
                "012710": "示例基金C",
            },
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                positions={"018125": object(), "026539": object()}
            ),
            watchlist=[("012710", SimpleNamespace(value="fund"))],
            latest_quotes={},
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )

    assert resolve_asset_metadata(state, "018125").display_name == "示例基金A"
    assert resolve_asset_metadata(state, "026539").display_name == "示例基金B"
    assert resolve_asset_metadata(state, "012710").display_name == "示例基金C"

    status = build_asset_metadata_status(state)
    assert status["configured_count"] == 3
    assert status["missing_symbols"] == []
    assert status["has_missing_metadata"] is False


def test_asset_metadata_resolver_prefers_local_db_metadata():
    from server.services.asset_metadata import (
        build_asset_metadata_status,
        resolve_asset_metadata,
    )

    class FakeDb:
        def get_instrument_metadata_sync(self, symbol, asset_type=None):
            assert symbol == "601985"
            return {
                "symbol": "601985",
                "asset_type": "stock",
                "display_name": "中国核电",
                "provider_symbol": "601985",
                "provider_name": "akshare",
                "source": "quote",
            }

        def list_instrument_metadata_sync(self):
            return [
                {
                    "symbol": "601985",
                    "asset_type": "stock",
                    "display_name": "中国核电",
                    "provider_symbol": "601985",
                    "provider_name": "akshare",
                    "source": "quote",
                }
            ]

        def get_latest_quotes_sync(self):
            return []

    state = SimpleNamespace(
        config=SimpleNamespace(
            instruments=[],
            assets={"601985": {"display_name": "601985 A股", "asset_class": "stock"}},
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(positions={"601985": object()}),
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    metadata = resolve_asset_metadata(state, "601985", asset_class="stock")
    status = build_asset_metadata_status(state)

    assert metadata.display_name == "中国核电"
    assert metadata.source == "db"
    assert status["missing_symbols"] == []
    assert status["configured_assets"][0]["display_name"] == "中国核电"


def test_asset_metadata_status_reports_missing_symbols_and_template():
    from server.services.asset_metadata import build_asset_metadata_status

    state = SimpleNamespace(
        config=SimpleNamespace(
            instruments=[],
            assets={"018125": {"display_name": "示例基金A", "asset_class": "fund"}},
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                positions={"018125": object(), "026539": object()}
            ),
            watchlist=[("012710", SimpleNamespace(value="fund"))],
            latest_quotes={},
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )

    status = build_asset_metadata_status(state)

    assert status["configured_count"] == 1
    assert status["missing_symbols"] == ["012710", "026539"]
    assert status["has_missing_metadata"] is True
    assert (
        status["suggested_config"]["watchlist_assets"][0]["display_name"]
        == "<填入资产名称>"
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
    captured_runner_args: dict[str, object] = {}
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
        "evidence_json": {
            "net_return": 0.12,
            "gross_return_before_costs": 0.12016,
            "total_cost": 16.0,
            "fill_count": 1,
            "assumptions": ["after-cost metrics include simulated fills"],
            "limitations": ["paper backtest evidence, not a profit claim"],
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

    def fake_run_backtest(request, config, db=None):
        captured_runner_args["db"] = db
        return fake_result

    monkeypatch.setattr(backtest_routes, "_run_backtest", fake_run_backtest)

    async def run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(backtest_routes.asyncio, "to_thread", run_inline)

    response = asyncio.run(endpoint(backtest_routes.BacktestRequest()))

    assert response.id == 42
    assert response.metrics.calmar == 2.25
    assert response.metrics.volatility == 0.21
    assert response.metrics.total_commission == 12.5
    assert response.metrics_json["gross_turnover"] == 24000.0
    assert response.cost_summary_json["total_trades"] == 2
    assert response.evidence_json["total_cost"] == 16.0
    assert response.evidence_json["limitations"] == [
        "paper backtest evidence, not a profit claim"
    ]
    assert response.fills[0].fill_id == "FILL-1"
    assert response.fills[0].symbol == "600519"
    assert captured_runner_args["db"] is fake_state.db
    assert '"calmar": 2.25' in str(saved_payload["metrics_json"])
    assert '"evidence_bundle":' in str(saved_payload["metrics_json"])
    assert '"total_commission": 12.5' in str(saved_payload["cost_summary_json"])


def test_run_single_backtest_attaches_oos_validation_for_benchmark_strategy(
    monkeypatch,
):
    import pandas as pd

    from core.types import AssetClass, BarFrequency, Symbol
    from data.handler import DataHandler
    from domain.instrument import make_etf
    from server.routes import backtest as backtest_routes

    class FakeStore:
        pass

    class FakeDataManager:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def get_instrument(symbol, asset_class):
            assert symbol == Symbol("510300")
            assert asset_class == AssetClass.FUND
            return make_etf("510300", "沪深300ETF")

        def get_bars(self, symbol, start, end, asset_class):
            prices = [
                10,
                9,
                8,
                7,
                6,
                7,
                8,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
            ]
            dates = pd.bdate_range("2026-01-05", periods=len(prices))
            df = pd.DataFrame(
                {
                    "timestamp": dates,
                    "open": prices,
                    "high": [price + 0.2 for price in prices],
                    "low": [price - 0.2 for price in prices],
                    "close": prices,
                    "volume": [1_000_000.0] * len(prices),
                }
            )
            return DataHandler(
                df,
                symbol,
                frequency=BarFrequency.DAILY,
                asset_class=asset_class,
            )

    monkeypatch.setattr("data.store.DataStore", FakeStore)
    monkeypatch.setattr("data.manager.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "data.manager.build_sources", lambda **kwargs: {"fixture": object()}
    )

    result = backtest_routes._run_single_backtest(
        backtest_routes.BacktestRequest(
            start_date="2026-01-05",
            end_date="2026-01-23",
            initial_cash=100000,
            strategy="dual_ma",
            short_period=3,
            long_period=5,
            assets=[{"symbol": "510300", "asset_class": "etf"}],
            oos_split_date="2026-01-14",
            benchmark_return=0.0,
        ),
        SimpleNamespace(
            assets=[],
            data_source="fixture",
            tushare_token="",
        ),
    )

    oos = result["metrics_json"]["oos_validation"]

    assert oos["strategy_id"] == "dual_ma"
    assert oos["benchmark_role"] == "etf_rotation_trend_following"
    assert oos["benchmark_return"] == 0.0
    assert oos["out_of_sample"]["fill_count"] >= 1
    assert oos["validation_status"] in {"benchmark_passed", "benchmark_failed"}
    assert "not investment advice" in oos["limitations"][0]


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
    assert response.evidence_json == {}
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
    assert response.provider_configured is True
    assert response.provider_requires_token is False
    assert response.provider_supports_funds is True
    assert response.provider_timeout_seconds is not None
    assert response.provider_last_error is None
    assert response.next_action == "refresh_quotes_or_check_source"
    assert response.provider_status == "stale"
    assert response.source_health == "stale"
    assert response.cache_age_seconds is not None
    assert response.latest_quote_timestamp is not None
    assert response.stale_symbols_count == 1
    assert response.stale_symbols_sample == ["600519"]
    assert response.market_open is False
    assert response.refresh_policy == "cache_only"


def test_market_data_health_prefers_materialized_latest_quotes(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    health_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/data-health"
    )

    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_type": "stock",
                    "price": 125.0,
                    "quote_timestamp": "2026-05-26T09:31:00+08:00",
                    "quote_source": "akshare",
                    "provider_name": "akshare",
                    "quote_status": "live",
                }
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 100.0,
                    "timestamp": "2026-05-25T15:00:00+08:00",
                    "quote_source": "akshare",
                    "provider_name": "akshare",
                    "quote_status": "stale",
                }
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
        ),
        scheduler=SimpleNamespace(watchlist=[("600519", "stock")], latest_quotes={}),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)

    response = asyncio.run(health_route.endpoint())

    assert response.quotes[0].symbol == "600519"
    assert response.quotes[0].asset_class == "stock"
    assert response.quotes[0].price == 125.0
    assert response.quotes[0].timestamp == "2026-05-26T09:31:00+08:00"
    assert response.quotes[0].quote_source == "akshare"
    assert response.latest_quote_timestamp == "2026-05-26T09:31:00+08:00"
    assert response.has_persistent_cache is True


def test_market_data_health_treats_live_fund_fallback_as_supported(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    health_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/data-health"
    )

    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "018125",
                    "asset_type": "fund",
                    "price": 2.4062,
                    "quote_timestamp": "2026-06-05 15:00",
                    "quote_source": "eastmoney_fund_estimate",
                    "provider_name": "akshare",
                    "provider_status": "live",
                    "quote_status": "live",
                }
            ]

        def get_latest_quotes_sync(self):
            return []

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "018125", "asset_class": "fund"}],
            data_source="tushare",
            tushare_token="token",
        ),
        scheduler=SimpleNamespace(watchlist=[("018125", "fund")], latest_quotes={}),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)

    response = asyncio.run(health_route.endpoint())

    assert response.provider_name == "tushare"
    assert response.provider_supports_funds is True
    assert response.source_health == "live"
    assert response.next_action is None
    assert response.quotes[0].quote_source == "eastmoney_fund_estimate"


def test_market_data_health_includes_ledger_holdings_not_in_scheduler(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    health_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/data-health"
    )

    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "601985",
                    "asset_type": "stock",
                    "price": 9.25,
                    "quote_timestamp": "2026-06-04",
                    "quote_source": "tushare_daily",
                    "provider_name": "tushare",
                    "provider_status": "live",
                    "quote_status": "live",
                    "is_demo": 0,
                },
                {
                    "symbol": "603659",
                    "asset_type": "stock",
                    "price": 28.4,
                    "quote_timestamp": "2026-06-04",
                    "quote_source": "tushare_daily",
                    "provider_name": "tushare",
                    "provider_status": "live",
                    "quote_status": "live",
                    "is_demo": 0,
                },
            ]

        def get_latest_quotes_sync(self):
            return []

        def get_ledger_entries_sync(self, limit=500, offset=0):
            if offset:
                return []
            return [
                {
                    "id": 1,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-05-29T14:16:00",
                    "amount": 2998.0,
                    "symbol": "603659",
                    "direction": "buy",
                    "quantity": 100.0,
                    "price": 29.98,
                    "commission": 5.03,
                    "asset_class": "stock",
                }
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[],
            data_source="tushare",
            tushare_token="token-1234",
            live_poll_interval=120,
        ),
        scheduler=SimpleNamespace(
            watchlist=[],
            portfolio=SimpleNamespace(positions={"601985": object()}),
            instruments={},
            latest_quotes={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)

    response = asyncio.run(health_route.endpoint())

    assert {quote.symbol for quote in response.quotes} == {"601985", "603659"}
    ledger_quote = next(quote for quote in response.quotes if quote.symbol == "603659")
    assert ledger_quote.price == 28.4
    assert ledger_quote.quote_source == "tushare_daily"


def test_market_data_health_prefers_materialized_quote_over_runtime(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    health_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/data-health"
    )

    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "601985",
                    "asset_type": "stock",
                    "price": 8.99,
                    "quote_timestamp": "2026-06-05",
                    "quote_source": "tushare_daily",
                    "provider_name": "tushare",
                    "provider_status": "live",
                    "quote_status": "live",
                    "captured_at": "2026-06-05T22:23:17+08:00",
                    "is_demo": 0,
                }
            ]

        def get_latest_quotes_sync(self):
            return []

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            data_source="tushare",
            tushare_token="token-1234",
            live_poll_interval=120,
        ),
        scheduler=SimpleNamespace(
            watchlist=[("601985", "stock")],
            portfolio=None,
            instruments={},
            latest_quotes={
                "601985": {
                    "symbol": "601985",
                    "asset_class": "stock",
                    "price": 9.13,
                    "timestamp": "2026-06-05T 11:01:13",
                    "quote_source": "tushare_realtime_quote",
                }
            },
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)

    response = asyncio.run(health_route.endpoint())

    assert response.quotes[0].symbol == "601985"
    assert response.quotes[0].price == 8.99
    assert response.quotes[0].timestamp == "2026-06-05"
    assert response.quotes[0].quote_source == "tushare_daily"


def test_market_data_health_falls_back_to_quote_snapshots(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    health_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/data-health"
    )

    class FakeDb:
        def list_latest_quotes_sync(self):
            return []

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 100.0,
                    "timestamp": "2026-05-25T15:00:00+08:00",
                    "quote_source": "akshare",
                    "provider_name": "akshare",
                    "quote_status": "stale",
                }
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
        ),
        scheduler=SimpleNamespace(watchlist=[("600519", "stock")], latest_quotes={}),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: False)

    response = asyncio.run(health_route.endpoint())

    assert response.quotes[0].symbol == "600519"
    assert response.quotes[0].asset_class == "stock"
    assert response.quotes[0].price == 100.0
    assert response.quotes[0].timestamp == "2026-05-25T15:00:00+08:00"
    assert response.has_persistent_cache is True
    assert response.latest_persistent_quote_timestamp == "2026-05-25T15:00:00+08:00"


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
        "_load_latest_snapshot_from_provider",
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


def test_market_quote_refresh_records_successful_fetch_run(monkeypatch, tmp_path):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(
            is_running=True,
            latest_quotes={},
            portfolio=SimpleNamespace(positions={}),
            instruments={},
        ),
        db=db,
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(
        market_routes, "_resolve_quote_status", lambda state, quote: "live"
    )
    monkeypatch.setattr(
        market_routes,
        "_load_latest_snapshot_from_provider",
        lambda state, symbol, asset_class: {
            "symbol": symbol,
            "asset_class": asset_class.value,
            "price": 12.5,
            "volume": 1000.0,
            "timestamp": "2026-05-12T10:05:00+08:00",
            "quote_source": "akshare",
            "provider_name": "akshare",
            "quote_status": "live",
            "provider_status": "live",
        },
    )

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519"]))
    )

    runs = db.list_quote_fetch_runs()
    assert response.quote_status == "live"
    assert len(runs) == 1
    assert runs[0]["trigger"] == "manual_refresh"
    assert runs[0]["provider"] == "akshare"
    assert runs[0]["asset_type"] == "stock"
    assert runs[0]["symbol_count"] == 1
    assert runs[0]["success_count"] == 1
    assert runs[0]["failure_count"] == 0
    assert runs[0]["cache_hit_count"] == 0
    assert runs[0]["status"] == "success"
    metadata = json.loads(runs[0]["metadata_json"])
    assert metadata["provider_status"] == "live"
    assert metadata["quote_status"] == "live"
    assert metadata["using_persistent_cache"] is False


def test_market_quote_refresh_success_upserts_latest_quote(monkeypatch, tmp_path):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 12.5,
                "volume": 1000.0,
                "timestamp": "2026-05-12T10:05:00+08:00",
                "source": "akshare",
                "display_name": "贵州茅台",
                "previous_close": 12.0,
                "previous_close_date": "2026-05-11",
            }

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(
            is_running=True,
            latest_quotes={},
            portfolio=SimpleNamespace(positions={}),
            instruments={},
        ),
        db=db,
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(
        market_routes, "_resolve_quote_status", lambda state, quote: "live"
    )
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": AkshareSource()},
    )

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519"]))
    )

    latest = db.get_latest_quote_sync("600519", asset_type="stock")
    instrument = db.get_instrument_metadata_sync("600519", "stock")
    snapshots = db.get_recent_quote_snapshots_sync("600519", limit=10)
    assert response.quote_status == "live"
    assert len(snapshots) == 1
    assert latest is not None
    assert latest["symbol"] == "600519"
    assert latest["asset_type"] == "stock"
    assert latest["price"] == 12.5
    assert latest["previous_close"] == 12.0
    assert latest["quote_source"] == "akshare"
    assert latest["provider_name"] == "akshare"
    assert latest["provider_status"] == "live"
    assert latest["quote_status"] == "live"
    assert latest["captured_reason"] == "manual_or_route_refresh"
    assert instrument is not None
    assert instrument["display_name"] == "贵州茅台"
    assert instrument["provider_name"] == "akshare"


def test_market_quote_refresh_records_cache_fallback_fetch_run(monkeypatch, tmp_path):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_quote_snapshot_sync(
        symbol="600519",
        asset_class="stock",
        price=10.0,
        volume=1000.0,
        timestamp="2026-05-12T09:30:00+08:00",
        quote_source="akshare",
        provider_name="akshare",
        quote_status="live",
        provider_status="live",
        captured_reason="test_cache",
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "600519", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(
            is_running=True,
            latest_quotes={},
            portfolio=SimpleNamespace(positions={}),
            instruments={},
        ),
        db=db,
    )

    def fail_fetch(state, symbol, asset_class):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(
        market_routes, "_load_latest_snapshot_from_provider", fail_fetch
    )

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519"]))
    )

    runs = db.list_quote_fetch_runs()
    latest = db.list_latest_quotes_sync()
    assert response.failed[0].using_persistent_cache is True
    assert latest == []
    assert len(runs) == 1
    assert runs[0]["status"] == "cache_only"
    assert runs[0]["success_count"] == 0
    assert runs[0]["failure_count"] == 1
    assert runs[0]["cache_hit_count"] == 1
    assert runs[0]["error_message"] == "provider unavailable"
    metadata = json.loads(runs[0]["metadata_json"])
    assert metadata["provider_status"] == "failed"
    assert metadata["quote_status"] == "error"
    assert metadata["using_persistent_cache"] is True


def test_market_quote_refresh_records_failed_run_without_provider_fallback(
    monkeypatch,
    tmp_path,
):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    class BrokenAkshareSource:
        def fetch_latest(self, symbol, asset_class):
            raise RuntimeError("provider unavailable")

    router = market_routes.create_router()
    refresh_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quotes/refresh"
    )
    endpoint = refresh_route.endpoint

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "000000", "asset_class": "fund"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(
            is_running=True,
            latest_quotes={},
            portfolio=SimpleNamespace(positions={}),
            instruments={},
        ),
        db=db,
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {
            "akshare": BrokenAkshareSource(),
        },
    )

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["000000"]))
    )

    runs = db.list_quote_fetch_runs()
    latest = db.list_latest_quotes_sync()
    assert response.quote_status == "error"
    assert response.failed[0].using_persistent_cache is False
    assert latest == []
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["provider"] == "akshare"
    assert runs[0]["asset_type"] == "fund"
    assert runs[0]["symbol_count"] == 1
    assert runs[0]["success_count"] == 0
    assert runs[0]["failure_count"] == 1
    assert runs[0]["cache_hit_count"] == 0
    assert runs[0]["error_message"] == "provider unavailable"
    metadata = json.loads(runs[0]["metadata_json"])
    assert metadata["provider_status"] == "failed"
    assert metadata["using_persistent_cache"] is False


def test_market_quote_fetch_runs_endpoint_lists_recent_runs(monkeypatch, tmp_path):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote-fetch-runs"
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.create_quote_fetch_run(
        run_id="older",
        started_at="2026-05-23T09:30:00+08:00",
        trigger="scheduler_poll",
        provider="akshare",
        status="success",
        metadata={"provider_status": "live"},
    )
    db.create_quote_fetch_run(
        run_id="newer",
        started_at="2026-05-23T09:31:00+08:00",
        trigger="manual_refresh",
        provider="akshare",
        status="failed",
        error_message="provider unavailable",
        metadata={"provider_status": "failed"},
    )
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(route.endpoint())
    limited = asyncio.run(route.endpoint(limit=1))

    assert [item.run_id for item in response] == ["newer", "older"]
    assert [item.run_id for item in limited] == ["newer"]
    assert response[0].trigger == "manual_refresh"
    assert response[0].status == "failed"
    assert response[0].error_message == "provider unavailable"
    assert response[0].metadata == {"provider_status": "failed"}
    assert not hasattr(response[0], "metadata_json")


def test_market_quote_fetch_runs_endpoint_filters_runs(monkeypatch, tmp_path):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote-fetch-runs"
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.create_quote_fetch_run(
        run_id="manual-akshare-success",
        started_at="2026-05-23T09:32:00+08:00",
        trigger="manual_refresh",
        provider="akshare",
        status="success",
    )
    db.create_quote_fetch_run(
        run_id="scheduler-akshare-failed",
        started_at="2026-05-23T09:31:00+08:00",
        trigger="scheduler_poll",
        provider="akshare",
        status="failed",
    )
    db.create_quote_fetch_run(
        run_id="manual-tushare-success",
        started_at="2026-05-23T09:30:00+08:00",
        trigger="manual_refresh",
        provider="tushare",
        status="success",
    )
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(
        route.endpoint(
            limit=1,
            trigger="manual_refresh",
            status="success",
            provider="tushare",
        )
    )

    assert [item.run_id for item in response] == ["manual-tushare-success"]


def test_market_quote_fetch_runs_endpoint_tolerates_malformed_metadata(
    monkeypatch,
    tmp_path,
):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/quote-fetch-runs"
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.create_quote_fetch_run(
        run_id="bad-metadata",
        started_at="2026-05-23T09:30:00+08:00",
        trigger="manual_refresh",
        provider="akshare",
        status="failed",
    )
    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.execute(
            "UPDATE quote_fetch_runs SET metadata_json = ? WHERE run_id = ?",
            ("{bad json", "bad-metadata"),
        )
        conn.commit()
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(route.endpoint())

    assert response[0].metadata == {
        "raw_metadata": "{bad json",
        "parse_error": "invalid_json",
    }


def test_market_instrument_metadata_backfill_updates_watchlist_and_holdings(
    monkeypatch,
    tmp_path,
):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/instrument-metadata/backfill"
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    fake_position = SimpleNamespace(quantity=100.0, avg_cost=8.69, market_value=869.0)
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "018125", "asset_class": "fund"}],
            data_source="akshare",
            tushare_token="",
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(positions={"601985": fake_position}),
            instruments={
                Symbol("601985"): SimpleNamespace(
                    asset_class=SimpleNamespace(value="stock")
                )
            },
            latest_quotes={},
        ),
        db=db,
    )

    class FakeAkshare:
        def fetch_latest(self, symbol, asset_class):
            if str(symbol) == "601985":
                return {"display_name": "中国核电", "timestamp": "2026-06-01 11:22:00"}
            if str(symbol) == "018125":
                return {
                    "display_name": "永赢先进制造智选混合C",
                    "timestamp": "2026-06-01",
                }
            raise AssertionError(f"unexpected symbol {symbol}")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeAkshare()},
    )

    response = asyncio.run(
        route.endpoint(market_routes.InstrumentMetadataBackfillRequest())
    )

    assert response.updated_count == 2
    assert response.failed_count == 0
    assert {item.symbol for item in response.items} == {"018125", "601985"}
    stock = db.get_instrument_metadata_sync("601985", "stock")
    fund = db.get_instrument_metadata_sync("018125", "fund")
    assert stock["display_name"] == "中国核电"
    assert stock["source"] == "backfill"
    assert stock["provider_name"] == "akshare"
    assert fund["display_name"] == "永赢先进制造智选混合C"


def test_market_instrument_metadata_backfill_preserves_provider_quote_identity(
    monkeypatch,
    tmp_path,
):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/instrument-metadata/backfill"
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            initial_cash=0,
        ),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}),
        db=db,
    )

    class FakeAkshare:
        def fetch_latest(self, symbol, asset_class):
            return {
                "symbol": "601985",
                "asset_class": "stock",
                "provider_name": "akshare",
                "provider_symbol": "601985.SH",
                "source": "akshare",
                "quote_source": "akshare_stock_spot",
                "price": 8.69,
                "timestamp": "2026-06-01 11:22:00",
                "display_name": "中国核电",
                "exchange": "SH",
                "market": "CN",
            }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeAkshare()},
    )

    response = asyncio.run(
        route.endpoint(market_routes.InstrumentMetadataBackfillRequest())
    )

    assert response.updated_count == 1
    metadata = db.get_instrument_metadata_sync("601985", "stock")
    assert metadata["provider_name"] == "akshare"
    assert metadata["provider_symbol"] == "601985.SH"
    assert metadata["exchange"] == "SH"
    assert metadata["market"] == "CN"
    assert json.loads(metadata["metadata_json"])["quote_source"] == "akshare_stock_spot"


def test_market_instrument_metadata_backfill_skips_existing_metadata(
    monkeypatch,
    tmp_path,
):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/instrument-metadata/backfill"
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_instrument_metadata_sync(
        symbol="601985",
        asset_type="stock",
        display_name="中国核电",
        provider_name="akshare",
        source="backfill",
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            initial_cash=0,
        ),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}),
        db=db,
    )

    class UnexpectedAkshare:
        def fetch_latest(self, symbol, asset_class):
            raise AssertionError("existing metadata should not be fetched")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": UnexpectedAkshare()},
    )

    response = asyncio.run(
        route.endpoint(market_routes.InstrumentMetadataBackfillRequest())
    )

    assert response.updated_count == 0
    assert response.skipped_count == 1
    assert response.items[0].status == "skipped"
    assert response.items[0].display_name == "中国核电"


def test_market_instrument_metadata_backfill_reports_missing_provider_name(
    monkeypatch,
    tmp_path,
):
    from server.db import AppDatabase
    from server.routes import market as market_routes

    router = market_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/instrument-metadata/backfill"
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            data_source="akshare",
            tushare_token="",
            initial_cash=0,
        ),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}),
        db=db,
    )

    class NamelessAkshare:
        def fetch_latest(self, symbol, asset_class):
            return {"price": 8.69, "timestamp": "2026-06-01 11:22:00"}

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": NamelessAkshare()},
    )

    response = asyncio.run(
        route.endpoint(market_routes.InstrumentMetadataBackfillRequest())
    )

    assert response.updated_count == 0
    assert response.failed_count == 1
    assert response.items[0].status == "failed"
    assert response.items[0].error == "metadata_not_available"
    assert db.get_instrument_metadata_sync("601985", "stock") is None


def test_market_data_health_reports_provider_configuration_next_action(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    health_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/data-health"
    )

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "018125", "asset_class": "fund"}],
            data_source="tushare",
            tushare_token="",
        ),
        scheduler=SimpleNamespace(
            watchlist=[("018125", "fund")],
            latest_quotes={},
            portfolio=None,
            instruments={},
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)

    response = asyncio.run(health_route.endpoint())

    assert response.provider_name == "tushare"
    assert response.provider_configured is False
    assert response.provider_requires_token is True
    assert response.provider_supports_funds is False
    assert response.next_action == "configure_data_source_token"


def test_refresh_one_quote_real_provider_does_not_fallback_to_unregistered_provider(
    monkeypatch,
):
    from server.routes import market as market_routes

    class BrokenAkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return None

    class FakeDb:
        def get_latest_quotes_sync(self):
            return []

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "000000", "asset_class": "fund"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(is_running=True, latest_quotes={}),
        db=FakeDb(),
    )

    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {
            "akshare": BrokenAkshareSource(),
        },
    )
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)

    response = asyncio.run(
        market_routes._refresh_one_quote(
            fake_state,
            "000000",
            market_routes.AssetClass.FUND,
            timeout_seconds=0.01,
        )
    )

    assert response.status == "failed"
    assert response.quote_source is None
    assert response.error == "no_real_data_available"
    assert response.reason == "暂无真实行情数据，请配置数据源或执行首次同步"
    assert response.using_persistent_cache is False


def test_refresh_one_quote_uses_persistent_real_cache_when_provider_fails(
    monkeypatch,
):
    from server.routes import market as market_routes

    class BrokenAkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return None

    class FakeDb:
        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "000000",
                    "asset_class": "fund",
                    "price": 1.2345,
                    "volume": None,
                    "timestamp": "2026-05-20",
                    "quote_source": "akshare",
                    "provider_name": "akshare",
                    "quote_status": "live",
                }
            ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[{"symbol": "000000", "asset_class": "fund"}],
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
        ),
        scheduler=SimpleNamespace(is_running=True, latest_quotes={}),
        db=FakeDb(),
    )

    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": BrokenAkshareSource()},
    )
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)

    response = asyncio.run(
        market_routes._refresh_one_quote(
            fake_state,
            "000000",
            market_routes.AssetClass.FUND,
            timeout_seconds=0.01,
        )
    )

    assert response.status == "stale"
    assert response.quote_source == "akshare"
    assert response.error is None
    assert response.using_persistent_cache is True
    assert response.reason == "行情源没有返回新报价，继续使用本地缓存"


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
    monkeypatch.setattr(
        market_routes, "_resolve_quote_status", lambda state, quote: "live"
    )
    monkeypatch.setattr(
        market_routes,
        "_load_latest_snapshot_from_provider",
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
    monkeypatch.setattr(
        market_routes, "_resolve_quote_status", lambda state, quote: "live"
    )
    monkeypatch.setattr(
        market_routes, "_load_latest_snapshot_from_provider", fake_fetch
    )

    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519", "000001"]))
    )

    assert response.quote_status == "partial"
    assert [item.symbol for item in response.refreshed] == ["600519"]
    assert [item.symbol for item in response.failed] == ["000001"]
    assert response.failed[0].reason == "行情源刷新失败，暂无真实行情数据"
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
        market_routes,
        "_load_latest_snapshot_from_provider",
        lambda state, symbol, asset_class: None,
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
    assert response.skipped[0].reason == "行情源没有返回新报价，继续使用本地缓存"
    assert response.skipped[0].using_persistent_cache is True
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
    monkeypatch.setattr(
        market_routes, "_load_latest_snapshot_from_provider", slow_fetch
    )
    monkeypatch.setattr(market_routes, "_MANUAL_REFRESH_TIMEOUT_SECONDS", 0.001)

    async def slow_blocking_fetch(func, *args):
        await asyncio.sleep(0.05)
        return func(*args)

    monkeypatch.setattr(market_routes, "_run_blocking_fetch", slow_blocking_fetch)

    started_at = time.monotonic()
    response = asyncio.run(
        endpoint(market_routes.QuoteRefreshRequest(symbols=["600519"]))
    )
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert response.quote_status == "error"
    assert response.failed[0].error == "provider_timeout"
    assert response.failed[0].reason == "行情源刷新超时，暂无真实行情数据"
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


def test_market_kline_timeout_does_not_block_route(monkeypatch):
    from server.routes import market as market_routes

    router = market_routes.create_router()
    kline_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/kline/{symbol}"
    )
    endpoint = kline_route.endpoint

    class FakeManager:
        def __init__(self, *args, **kwargs):
            pass

        def get_bars(self, *args, **kwargs):
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
    monkeypatch.setattr(market_routes, "is_cn_trading_session", lambda: True)
    monkeypatch.setattr(market_routes, "_KLINE_FETCH_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("data.manager.DataManager", FakeManager)
    monkeypatch.setattr("data.store.DataStore", FakeStore)

    async def slow_blocking_fetch(func, *args, **kwargs):
        await asyncio.sleep(0.1)
        return func(*args, **kwargs)

    monkeypatch.setattr(market_routes, "_run_blocking_fetch", slow_blocking_fetch)

    started = time.monotonic()
    response = asyncio.run(endpoint("600519"))

    assert response == []
    assert time.monotonic() - started < 0.08


def test_market_bars_backfill_writes_authoritative_store(monkeypatch, tmp_path):
    import pandas as pd

    from data.store import DataStore as RealStore
    from server.routes import market as market_routes

    store = RealStore(root=tmp_path / "store")
    router = market_routes.create_router()
    backfill_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/bars/backfill"
    )
    endpoint = backfill_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            start_date="2026-05-01",
            assets=[{"symbol": "601985", "asset_class": "stock"}],
        ),
        scheduler=None,
        db=None,
    )

    class FakeSource:
        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            assert str(symbol) == "601985"
            assert frequency.value == "1d"
            assert asset_class.value == "stock"
            return pd.DataFrame(
                {
                    "timestamp": pd.to_datetime(["2026-05-27", "2026-05-28"]),
                    "open": [8.69, 8.72],
                    "high": [8.80, 8.85],
                    "low": [8.60, 8.66],
                    "close": [8.74, 8.78],
                    "volume": [100000.0, 120000.0],
                    "amount": [874000.0, 1053600.0],
                }
            )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr("data.store.DataStore", lambda: store)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeSource()},
    )

    response = asyncio.run(
        endpoint(
            market_routes.MarketBarsBackfillRequest(
                symbols=["601985"],
                start="2026-05-27",
                end="2026-05-28",
            )
        )
    )

    assert response.provider == "akshare"
    assert response.updated_count == 1
    assert response.failed_count == 0
    assert response.items[0].symbol == "601985"
    assert response.items[0].row_count == 2

    stored = store.load_bars(Symbol("601985"))
    assert stored is not None
    assert list(stored["close"]) == [8.74, 8.78]
    assert (
        store.get_meta(Symbol("601985"), market_routes.BarFrequency.DAILY)["row_count"]
        == 2
    )


def test_market_bars_backfill_reports_provider_failure(monkeypatch, tmp_path):
    from data.store import DataStore as RealStore
    from server.routes import market as market_routes

    store = RealStore(root=tmp_path / "store")
    router = market_routes.create_router()
    backfill_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/market/bars/backfill"
    )
    endpoint = backfill_route.endpoint

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            start_date="2026-05-01",
            assets=[{"symbol": "601985", "asset_class": "stock"}],
        ),
        scheduler=None,
        db=None,
    )

    class FailingSource:
        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr("data.store.DataStore", lambda: store)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FailingSource()},
    )

    response = asyncio.run(
        endpoint(
            market_routes.MarketBarsBackfillRequest(
                symbols=["601985"],
                start="2026-05-27",
                end="2026-05-28",
            )
        )
    )

    assert response.updated_count == 0
    assert response.failed_count == 1
    assert response.items[0].status == "failed"
    assert "provider unavailable" in response.items[0].error
    assert store.load_bars(Symbol("601985")) is None


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
                "display_name": "永赢先进制造智选混合发起C",
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
    assert response["display_name"] == "永赢先进制造智选混合发起C"
    assert response["previous_close"] == 1.103
    assert response["previous_close_date"] == "2026-04-18"


def test_fetch_latest_snapshot_falls_back_to_akshare_for_stock_when_tushare_returns_none(
    monkeypatch,
):
    from server.routes import market as market_routes

    saved_quote: dict[str, object] = {}

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="tushare",
            tushare_token="token-1234",
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            live_poll_interval=120,
        ),
        db=SimpleNamespace(
            save_quote_snapshot_sync=lambda **kwargs: saved_quote.update(kwargs),
        ),
    )

    class NullSource:
        def fetch_latest(self, symbol, asset_class):
            return None

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 8.76,
                "volume": 123456.0,
                "timestamp": "10:30:00",
                "display_name": "中国核电",
            }

    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {
            "tushare": NullSource(),
            "akshare": AkshareSource(),
        },
    )

    response = market_routes._fetch_latest_snapshot(
        fake_state, "601985", market_routes.AssetClass.STOCK
    )

    assert response["asset_class"] == "stock"
    assert response["price"] == 8.76
    assert response["provider_name"] == "akshare"
    assert response["display_name"] == "中国核电"
    assert saved_quote["symbol"] == "601985"
    assert saved_quote["provider_name"] == "akshare"
    assert saved_quote["captured_reason"] == "manual_or_route_refresh"


def test_fetch_latest_snapshot_falls_back_to_akshare_when_tushare_raises(
    monkeypatch,
):
    from server.routes import market as market_routes

    saved_quote: dict[str, object] = {}

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="tushare",
            tushare_token="token-1234",
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            live_poll_interval=120,
        ),
        db=SimpleNamespace(
            save_quote_snapshot_sync=lambda **kwargs: saved_quote.update(kwargs),
        ),
    )

    class RaisingTushareSource:
        def fetch_latest(self, symbol, asset_class):
            raise NotImplementedError("Tushare fetch_latest is not implemented")

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 8.76,
                "volume": 123456.0,
                "timestamp": "10:30:00",
                "display_name": "中国核电",
                "previous_close": 8.65,
                "previous_close_date": "2026-06-03",
            }

    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {
            "tushare": RaisingTushareSource(),
            "akshare": AkshareSource(),
        },
    )

    response = market_routes._fetch_latest_snapshot(
        fake_state, "601985", market_routes.AssetClass.STOCK
    )

    assert response["asset_class"] == "stock"
    assert response["price"] == 8.76
    assert response["provider_name"] == "akshare"
    assert response["display_name"] == "中国核电"
    assert response["previous_close"] == 8.65
    assert saved_quote["symbol"] == "601985"
    assert saved_quote["provider_name"] == "akshare"


def test_fetch_latest_snapshot_falls_back_to_akshare_when_tushare_times_out(
    monkeypatch,
):
    from server.routes import market as market_routes

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="tushare",
            tushare_token="token-1234",
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            live_poll_interval=120,
        ),
        db=SimpleNamespace(
            save_quote_snapshot_sync=lambda **kwargs: None,
        ),
    )

    class SlowTushareSource:
        def fetch_latest(self, symbol, asset_class):
            time.sleep(0.05)
            return {
                "price": 8.50,
                "volume": 1.0,
                "timestamp": "2026-06-05",
            }

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 8.76,
                "volume": 123456.0,
                "timestamp": "2026-06-05T10:30:00",
                "display_name": "中国核电",
            }

    monkeypatch.setattr(market_routes, "_PROVIDER_REFRESH_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {
            "tushare": SlowTushareSource(),
            "akshare": AkshareSource(),
        },
    )

    response = market_routes._fetch_latest_snapshot(
        fake_state, "601985", market_routes.AssetClass.STOCK
    )

    assert response["price"] == 8.76
    assert response["provider_name"] == "akshare"
    assert response["quote_source"] == "akshare"


def test_parse_quote_timestamp_accepts_legacy_space_after_t():
    from server.routes import portfolio as portfolio_routes

    parsed = portfolio_routes._parse_quote_timestamp("2026-06-05T 11:01:13")

    assert parsed is not None
    assert parsed.isoformat() == "2026-06-05T11:01:13+08:00"


def test_fetch_latest_snapshot_persists_stock_change_fields(monkeypatch):
    from server.routes import market as market_routes

    saved_latest: dict[str, object] = {}

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            live_poll_interval=120,
        ),
        db=SimpleNamespace(
            save_quote_snapshot_sync=lambda **kwargs: None,
            upsert_latest_quote_sync=lambda **kwargs: saved_latest.update(kwargs),
            upsert_instrument_metadata_sync=lambda **kwargs: None,
            save_daily_close_snapshot_sync=lambda **kwargs: None,
        ),
    )

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "price": 8.76,
                "volume": 123456.0,
                "timestamp": "10:30:00",
                "display_name": "中国核电",
                "previous_close": 8.65,
                "previous_close_date": "2026-06-03",
                "change": 0.11,
                "change_percent": 0.0127,
            }

    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": AkshareSource()},
    )

    response = market_routes._fetch_latest_snapshot(
        fake_state, "601985", market_routes.AssetClass.STOCK
    )

    assert response["change"] == 0.11
    assert response["change_percent"] == pytest.approx(0.0127)
    assert saved_latest["previous_close"] == 8.65
    assert saved_latest["change"] == 0.11
    assert saved_latest["change_percent"] == pytest.approx(0.0127)


def test_fetch_latest_snapshot_preserves_normalized_provider_identity(monkeypatch):
    from server.routes import market as market_routes

    saved_latest: dict[str, object] = {}
    saved_metadata: dict[str, object] = {}

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            data_source="akshare",
            tushare_token="",
            assets=[{"symbol": "601985", "asset_class": "stock"}],
            live_poll_interval=120,
        ),
        db=SimpleNamespace(
            save_quote_snapshot_sync=lambda **kwargs: None,
            upsert_latest_quote_sync=lambda **kwargs: saved_latest.update(kwargs),
            upsert_instrument_metadata_sync=lambda **kwargs: saved_metadata.update(
                kwargs
            ),
        ),
    )

    class AkshareSource:
        def fetch_latest(self, symbol, asset_class):
            return {
                "symbol": "601985",
                "asset_class": "stock",
                "provider_name": "akshare",
                "provider_symbol": "601985.SH",
                "source": "akshare",
                "quote_source": "akshare_stock_spot",
                "price": 8.76,
                "volume": 123456.0,
                "timestamp": "10:30:00",
                "display_name": "中国核电",
                "exchange": "SH",
                "market": "CN",
            }

    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": AkshareSource()},
    )

    response = market_routes._fetch_latest_snapshot(
        fake_state, "601985", market_routes.AssetClass.STOCK
    )

    assert response["quote_source"] == "akshare_stock_spot"
    assert response["provider_name"] == "akshare"
    assert response["provider_symbol"] == "601985.SH"
    assert response["exchange"] == "SH"
    assert response["market"] == "CN"
    assert saved_latest["quote_source"] == "akshare_stock_spot"
    assert saved_latest["provider_name"] == "akshare"
    assert saved_metadata["provider_symbol"] == "601985.SH"
    assert saved_metadata["exchange"] == "SH"
    assert saved_metadata["market"] == "CN"
    assert saved_metadata["metadata"]["quote_source"] == "akshare_stock_spot"


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


def test_market_watchlist_add_and_remove(monkeypatch):
    from server.bootstrap import resolve_config_path
    from server.routes import market as market_routes

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

    class FakeWatchlistDb:
        def __init__(self):
            self.assets = [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "display_name": "600519",
                    "source": "manual",
                }
            ]

        def get_latest_quotes_sync(self):
            return []

        def list_watchlist_assets_sync(self):
            return list(self.assets)

        def upsert_watchlist_asset_sync(self, **payload):
            row = {
                "symbol": payload["symbol"],
                "asset_class": payload["asset_class"],
                "display_name": payload.get("display_name") or payload["symbol"],
                "source": payload.get("source") or "manual",
            }
            self.assets.append(row)
            return row

        def delete_watchlist_asset_sync(self, symbol):
            original_len = len(self.assets)
            self.assets = [
                asset
                for asset in self.assets
                if asset["symbol"].lower() != symbol.lower()
            ]
            return len(self.assets) != original_len

    fake_db = FakeWatchlistDb()
    fake_state = SimpleNamespace(
        config=config,
        scheduler=SimpleNamespace(is_running=False, latest_quotes={}, portfolio=None),
        db=fake_db,
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    config_path = resolve_config_path()
    original_config = {"data_source": "akshare", "sentinel": "watchlist-read-only"}
    config_path.write_text(json.dumps(original_config), encoding="utf-8")

    add_response = asyncio.run(
        add_route.endpoint(
            market_routes.WatchlistCreateRequest(symbol="510300", asset_class="etf")
        )
    )
    assert any(item.symbol == "510300" for item in add_response)

    remove_response = asyncio.run(remove_route.endpoint("510300"))
    assert all(item.symbol != "510300" for item in remove_response)
    assert config.assets == [{"symbol": "600519", "asset_class": "stock"}]
    assert all(asset["symbol"] != "510300" for asset in fake_db.assets)
    assert json.loads(config_path.read_text(encoding="utf-8")) == original_config


def test_update_data_source_settings_does_not_persist_business_state(monkeypatch):
    from server.bootstrap import resolve_config_path
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
            {
                "symbol": "永赢先进制造智选混合C",
                "asset_class": "fund",
                "display_name": "永赢先进制造智选混合C",
                "provider_symbol": "018125",
                "aliases": ["018125"],
            },
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

    config_path = resolve_config_path()
    original_config = {"data_source": "akshare", "sentinel": "do-not-overwrite"}
    config_path.write_text(json.dumps(original_config), encoding="utf-8")

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
        {
            "symbol": "永赢先进制造智选混合C",
            "asset_class": "fund",
            "display_name": "永赢先进制造智选混合C",
            "provider_symbol": "018125",
            "aliases": ["018125"],
        },
        {"symbol": "融通科技臻选混合C", "asset_class": "fund"},
    ]
    assert json.loads(config_path.read_text(encoding="utf-8")) == original_config


def test_get_asset_metadata_status_reports_missing_symbols(monkeypatch):
    from server.routes import settings as settings_routes

    router = settings_routes.create_router()
    status_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/settings/asset-metadata"
        and "GET" in route.methods
    )

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets={"018125": "示例基金A"},
            instruments=[],
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                positions={"018125": object(), "026539": object()}
            ),
            watchlist=[("012710", SimpleNamespace(value="fund"))],
            latest_quotes={},
        ),
        db=SimpleNamespace(get_latest_quotes_sync=lambda: []),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(status_route.endpoint())

    assert response.configured_count == 1
    assert response.missing_symbols == ["012710", "026539"]
    assert response.has_missing_metadata is True
    assert (
        response.suggested_config["watchlist_assets"][0]["provider_symbol"] == "012710"
    )


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
                    "symbol": "永赢先进制造智选混合C",
                    "asset_class": "fund",
                    "display_name": "永赢先进制造智选混合发起C",
                    "provider_symbol": "018125",
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

    assert response.positions[0].symbol == "018125"
    assert response.positions[0].name == "永赢先进制造智选混合发起C"
    assert response.positions[0].display_name == "永赢先进制造智选混合发起C"
    assert response.positions[0].asset_class == "fund"
    assert response.allocation[1].symbol == "018125"
    assert response.allocation[1].name == "永赢先进制造智选混合发起C"


def test_empty_portfolio_snapshot_does_not_seed_config_initial_cash(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )

    class EmptyDb:
        def get_latest_quotes_sync(self):
            return []

        def get_ledger_entries_sync(self, limit=50, offset=0):
            return []

        def get_cash_flows_sync(self, limit=1, offset=0):
            return []

        def get_trades_sync(self, limit=1, offset=0):
            return []

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=Decimal("100000"),
            data_source="akshare",
            tushare_token="",
        ),
        db=EmptyDb(),
        scheduler=SimpleNamespace(portfolio=None, latest_quotes={}, instruments={}),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.cash == 0.0
    assert response.total_equity == 0.0
    assert response.total_deposits == 0.0
    assert response.positions == []
    assert response.allocation == []


def test_portfolio_snapshot_uses_simple_asset_mapping(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )

    fake_position = SimpleNamespace(
        quantity=1000,
        available_qty=1000,
        frozen_qty=0,
        avg_cost=1.0,
        market_value=1200.0,
        unrealized_pnl=200.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=4000,
            data_source="akshare",
            tushare_token="",
            instruments=[],
            assets={"026539": "示例基金B"},
        ),
        db=SimpleNamespace(get_total_deposits=AsyncMock(return_value=0.0)),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=0.0, positions={"026539": fake_position}),
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.positions[0].display_name == "示例基金B"
    allocation_item = next(
        item for item in response.allocation if item.symbol == "026539"
    )
    assert allocation_item.name == "示例基金B"


def test_portfolio_snapshot_does_not_fetch_missing_fund_quotes_in_request(
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
        lambda *args, **kwargs: pytest.fail(
            "portfolio snapshot must not fetch remotely"
        ),
    )
    monkeypatch.setattr(
        "server.routes.portfolio.rebuild_portfolio_from_ledger",
        fake_rebuild,
    )

    response = asyncio.run(endpoint())

    assert response.total_equity == 3500.0
    assert response.positions[0].market_value == 1000.0
    assert response.positions[0].unrealized_pnl == pytest.approx(0.0)


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


def test_portfolio_risk_summary_accepts_timezone_aware_quote_timestamps(monkeypatch):
    from zoneinfo import ZoneInfo

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
                    "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                }
            ],
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=Decimal("1000"),
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

    assert all(item.kind != "data" for item in response)


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


def test_portfolio_explainability_builds_daily_timeline_from_ledger_history(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    explain_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/explainability"
    )
    endpoint = explain_route.endpoint

    class FakeDb:
        daily_closes = [
            {
                "symbol": "600519",
                "asset_class": "stock",
                "trade_date": "2026-04-22",
                "close_price": 10.5,
                "source": "test_close",
            },
            {
                "symbol": "600519",
                "asset_class": "stock",
                "trade_date": "2026-05-08",
                "close_price": 11.0,
                "source": "test_close",
            },
        ]

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
                    "note": "seed cash",
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
                    "note": "first stock lot",
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
                    "timestamp": "2026-05-12T15:00:00+08:00",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            candidates = [
                close
                for close in self.daily_closes
                if close["symbol"] == symbol and close["trade_date"] < trade_date
            ]
            return candidates[-1] if candidates else None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 100000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            watchlist=[],
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

    response = asyncio.run(endpoint(limit=50))
    timeline_by_date = {point.date: point for point in response.timeline}

    assert timeline_by_date["2026-04-22"].equity == pytest.approx(100050.0)
    assert timeline_by_date["2026-05-08"].equity == pytest.approx(100100.0)
    assert timeline_by_date["2026-05-08"].market_pnl == pytest.approx(50.0)
    assert response.timeline[-1].date == "2026-05-11"
    assert "2026-05-12" not in timeline_by_date


def test_portfolio_explainability_marks_missing_historical_prices(monkeypatch):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    explain_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/explainability"
    )
    endpoint = explain_route.endpoint

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
                    "note": "seed cash",
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
                    "note": "first stock lot",
                    "source": "manual",
                    "source_ref": "stock-1",
                    "created_at": "2026-04-22T10:00:01+00:00",
                },
            ]

        def get_latest_quotes_sync(self):
            return []

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 100000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 4, 24, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    response = asyncio.run(endpoint(limit=50))
    timeline_by_date = {point.date: point for point in response.timeline}

    assert timeline_by_date["2026-04-22"].valuation_status == "missing"
    assert timeline_by_date["2026-04-22"].missing_price_symbols == ["600519"]


def test_portfolio_explainability_does_not_attribute_weekend_current_quotes(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    explain_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/explainability"
    )
    endpoint = explain_route.endpoint

    class FakeDb:
        daily_closes = [
            {
                "symbol": "600519",
                "asset_class": "stock",
                "trade_date": "2026-04-22",
                "close_price": 10.0,
                "source": "test_close",
            },
            {
                "symbol": "600519",
                "asset_class": "stock",
                "trade_date": "2026-05-08",
                "close_price": 11.0,
                "source": "test_close",
            },
        ]

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
                    "note": "seed cash",
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
                    "note": "first stock lot",
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
                    "timestamp": "2026-05-10T12:00:00+08:00",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            candidates = [
                close
                for close in self.daily_closes
                if close["symbol"] == symbol and close["trade_date"] < trade_date
            ]
            return candidates[-1] if candidates else None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 100000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 5, 10, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    response = asyncio.run(endpoint(limit=50))

    assert response.timeline[-1].date == "2026-05-08"
    assert response.timeline[-1].equity == pytest.approx(100100.0)
    assert all(point.date != "2026-05-10" for point in response.timeline)


def test_portfolio_explainability_does_not_attribute_stale_quote_to_current_day(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    explain_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/explainability"
    )
    endpoint = explain_route.endpoint

    class FakeDb:
        market_bars = {
            ("012710", "2026-06-12"): {"close": 0.9194},
        }

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [
                {
                    "id": 1,
                    "entry_type": "cash_deposit",
                    "timestamp": "2026-06-10T01:00:00+00:00",
                    "amount": 1000.0,
                    "symbol": None,
                    "direction": None,
                    "quantity": None,
                    "price": None,
                    "commission": 0.0,
                    "asset_class": "cash",
                    "note": "seed cash",
                    "source": "manual",
                    "source_ref": "deposit-1",
                    "created_at": "2026-06-10T01:00:01+00:00",
                },
                {
                    "id": 2,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-06-12T06:00:00+00:00",
                    "amount": 100.0,
                    "symbol": "012710",
                    "direction": "buy",
                    "quantity": 100.0,
                    "price": 0.9,
                    "commission": 0.0,
                    "asset_class": "fund",
                    "note": "手工录入基金申购：华夏核心成长混合C，申购金额 100.00",
                    "source": "manual",
                    "source_ref": "fund-1",
                    "created_at": "2026-06-12T06:00:01+00:00",
                },
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "012710",
                    "asset_class": "fund",
                    "price": 0.9202,
                    "volume": 0.0,
                    "timestamp": "2026-06-12T15:00:00+08:00",
                    "quote_timestamp": "2026-06-12T15:00:00+08:00",
                    "quote_source": "eastmoney_fund_estimate",
                }
            ]

        def get_latest_market_bar_before_date_sync(self, symbol: str, trade_date: str):
            candidates = [
                (bar_date, bar)
                for (bar_symbol, bar_date), bar in self.market_bars.items()
                if bar_symbol == symbol and bar_date < trade_date
            ]
            if not candidates:
                return None
            bar_date, bar = sorted(candidates)[-1]
            return {
                "symbol": symbol,
                "asset_class": "fund",
                "trade_date": bar_date,
                "timestamp": f"{bar_date}T15:00:00+08:00",
                "close": bar["close"],
                "price": bar["close"],
                "source": "market_bars",
            }

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 1000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 6, 15, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    response = asyncio.run(endpoint(limit=50))

    assert response.timeline[-1].date == "2026-06-12"
    assert all(point.date != "2026-06-15" for point in response.timeline)


def test_portfolio_explainability_trims_intraday_terminal_point_from_return_calendar():
    from zoneinfo import ZoneInfo

    from server.models import EquitySeriesPoint
    from server.routes.portfolio import _trim_intraday_terminal_series_point

    shanghai = ZoneInfo("Asia/Shanghai")
    points = [
        EquitySeriesPoint(
            timestamp="2026-06-12T15:00:00+08:00",
            total=15084.30,
            stocks=6596.0,
            funds=2718.9,
            others=0.0,
            cash=5769.4,
            unrealized_pnl=760.0,
            quote_status="live",
        ),
        EquitySeriesPoint(
            timestamp="2026-06-15T10:45:00+08:00",
            total=15204.42,
            stocks=6678.0,
            funds=2757.01,
            others=0.0,
            cash=5769.4,
            unrealized_pnl=880.12,
            quote_status="live",
        ),
    ]

    trimmed = _trim_intraday_terminal_series_point(
        points,
        now=datetime(2026, 6, 15, 10, 50, tzinfo=shanghai),
    )

    assert [point.timestamp for point in trimmed] == ["2026-06-12T15:00:00+08:00"]


def test_portfolio_explainability_keeps_daily_close_terminal_point():
    from zoneinfo import ZoneInfo

    from server.models import EquitySeriesPoint
    from server.routes.portfolio import _trim_intraday_terminal_series_point

    shanghai = ZoneInfo("Asia/Shanghai")
    points = [
        EquitySeriesPoint(
            timestamp="2026-06-12T15:00:00+08:00",
            total=15084.30,
            stocks=6596.0,
            funds=2718.9,
            others=0.0,
            cash=5769.4,
            unrealized_pnl=760.0,
            quote_status="live",
        ),
        EquitySeriesPoint(
            timestamp="2026-06-15T15:00:00+08:00",
            total=15204.42,
            stocks=6678.0,
            funds=2757.01,
            others=0.0,
            cash=5769.4,
            unrealized_pnl=880.12,
            quote_status="live",
        ),
    ]

    trimmed = _trim_intraday_terminal_series_point(
        points,
        now=datetime(2026, 6, 15, 16, 0, tzinfo=shanghai),
    )

    assert [point.timestamp for point in trimmed] == [
        "2026-06-12T15:00:00+08:00",
        "2026-06-15T15:00:00+08:00",
    ]


def test_historical_equity_quote_does_not_use_current_latest_quote_for_daily_attribution():
    from server.routes.portfolio import _historical_quote_for_equity_day

    class FakeDb:
        def get_latest_market_bar_before_date_sync(self, symbol: str, trade_date: str):
            assert symbol == "012710"
            assert trade_date == "2026-06-16"
            return {
                "symbol": symbol,
                "asset_class": "fund",
                "trade_date": "2026-06-12",
                "timestamp": "2026-06-12T15:00:00+08:00",
                "close": 0.9194,
                "price": 0.9194,
                "source": "market_bars",
            }

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

    quote = _historical_quote_for_equity_day(
        SimpleNamespace(db=FakeDb()),
        symbol="012710",
        asset_class="fund",
        trade_date=date(2026, 6, 15),
        latest_quotes={
            "012710": {
                "symbol": "012710",
                "asset_class": "fund",
                "price": 0.9075,
                "quote_timestamp": "2026-06-15 10:45",
                "quote_source": "eastmoney_fund_estimate",
            }
        },
        is_current_day=True,
    )

    assert quote is not None
    assert quote["source"] == "market_bars"
    assert quote["timestamp"] == "2026-06-12T15:00:00+08:00"
    assert quote["price"] == pytest.approx(0.9194)


def test_portfolio_explainability_maps_ledger_events_to_shanghai_dates():
    from server.models import EquityPoint
    from server.routes.portfolio import _build_timeline

    timeline = _build_timeline(
        [
            EquityPoint(timestamp="2026-04-24T15:00:00+08:00", equity=0.0),
            EquityPoint(timestamp="2026-04-27T15:00:00+08:00", equity=12000.0),
        ],
        [
            {
                "entry_type": "cash_deposit",
                "timestamp": "2026-04-26T16:00:00+00:00",
                "amount": 12000.0,
                "note": "Shanghai Monday deposit",
            }
        ],
    )

    apr27 = timeline[-1]
    assert apr27.date == "2026-04-27"
    assert apr27.external_flow == pytest.approx(12000.0)
    assert apr27.market_pnl == pytest.approx(0.0)
    assert apr27.events[0].category == "capital"
    assert apr27.external_flow_breakdown[0].key == "cash_deposit"
    assert apr27.external_flow_breakdown[0].value == pytest.approx(12000.0)


def test_portfolio_explainability_breaks_daily_change_into_asset_and_flow_buckets():
    from server.models import EquityPoint
    from server.routes.portfolio import _build_timeline

    timeline = _build_timeline(
        [
            EquityPoint(timestamp="2026-06-11T15:00:00+08:00", equity=14852.827551),
            EquityPoint(timestamp="2026-06-12T15:00:00+08:00", equity=15082.897551),
        ],
        [
            {
                "entry_type": "dividend",
                "timestamp": "2026-06-12T06:00:00+00:00",
                "amount": 5.0,
                "symbol": "601985",
                "asset_class": "stock",
                "note": "cash dividend",
            }
        ],
        component_values_by_date={
            "2026-06-11": {
                "stocks": 6362.0,
                "funds": 2727.827551,
                "others": 0.0,
                "cash": 5763.0,
            },
            "2026-06-12": {
                "stocks": 6596.0,
                "funds": 2718.897551,
                "others": 0.0,
                "cash": 5768.0,
            },
        },
    )

    jun12 = timeline[-1]
    assert jun12.market_pnl == pytest.approx(225.07)
    assert {item.key: item.value for item in jun12.market_breakdown} == pytest.approx(
        {
            "stock": 234.0,
            "fund": -8.93,
        }
    )
    assert {
        item.key: item.value for item in jun12.external_flow_breakdown
    } == pytest.approx({"dividend": 5.0})


def test_portfolio_explainability_marks_return_after_missing_valuation_as_gap():
    from server.models import EquityPoint
    from server.routes.portfolio import _build_timeline

    timeline = _build_timeline(
        [
            EquityPoint(timestamp="2026-06-11T15:00:00+08:00", equity=15131.8275),
            EquityPoint(timestamp="2026-06-12T15:00:00+08:00", equity=14852.8275),
        ],
        [],
        valuation_status_by_date={
            "2026-06-11": "missing",
            "2026-06-12": "live",
        },
        missing_price_symbols_by_date={
            "2026-06-11": ["601985", "603659"],
        },
    )

    assert timeline[-1].date == "2026-06-12"
    assert timeline[-1].market_pnl == pytest.approx(0.0)
    assert timeline[-1].valuation_status == "missing"
    assert timeline[-1].missing_price_symbols == ["601985", "603659"]


def test_portfolio_explainability_prefers_market_bars_for_stock_daily_returns(
    monkeypatch,
):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    explain_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/explainability"
    )
    endpoint = explain_route.endpoint

    class FakeDb:
        daily_closes = [
            {
                "symbol": "601985",
                "asset_class": "stock",
                "trade_date": "2026-06-12",
                "close_price": 9.12,
                "source": "reported_previous_close",
            },
            {
                "symbol": "603659",
                "asset_class": "stock",
                "trade_date": "2026-06-12",
                "close_price": 27.23,
                "source": "reported_previous_close",
            },
        ]
        market_bars = {
            ("601985", "2026-06-11"): {"open": 9.05, "close": 9.12},
            ("601985", "2026-06-12"): {"open": 9.10, "close": 9.24},
            ("603659", "2026-06-11"): {"open": 27.48, "close": 27.23},
            ("603659", "2026-06-12"): {"open": 27.59, "close": 28.34},
        }

        def get_ledger_entries_sync(self, limit=500, offset=0):
            return [
                {
                    "id": 1,
                    "entry_type": "cash_deposit",
                    "timestamp": "2026-06-10T01:00:00+00:00",
                    "amount": 100000.0,
                    "symbol": None,
                    "direction": None,
                    "quantity": None,
                    "price": None,
                    "commission": 0.0,
                    "asset_class": "cash",
                    "note": "seed cash",
                    "source": "manual",
                    "source_ref": "deposit-1",
                    "created_at": "2026-06-10T01:00:01+00:00",
                },
                {
                    "id": 2,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-06-11T02:00:00+00:00",
                    "amount": 912.0,
                    "symbol": "601985",
                    "direction": "buy",
                    "quantity": 100.0,
                    "price": 9.12,
                    "commission": 0.0,
                    "asset_class": "stock",
                    "note": "first stock lot",
                    "source": "manual",
                    "source_ref": "stock-1",
                    "created_at": "2026-06-11T02:00:01+00:00",
                },
                {
                    "id": 3,
                    "entry_type": "trade_buy",
                    "timestamp": "2026-06-11T02:30:00+00:00",
                    "amount": 5446.0,
                    "symbol": "603659",
                    "direction": "buy",
                    "quantity": 200.0,
                    "price": 27.23,
                    "commission": 0.0,
                    "asset_class": "stock",
                    "note": "second stock lot",
                    "source": "manual",
                    "source_ref": "stock-2",
                    "created_at": "2026-06-11T02:30:01+00:00",
                },
            ]

        def get_latest_quotes_sync(self):
            return []

        def get_latest_market_bar_before_date_sync(self, symbol: str, trade_date: str):
            candidates = [
                (bar_date, bar)
                for (bar_symbol, bar_date), bar in self.market_bars.items()
                if bar_symbol == symbol and bar_date < trade_date
            ]
            if not candidates:
                return None
            bar_date, bar = sorted(candidates)[-1]
            return {
                "symbol": symbol,
                "trade_date": bar_date,
                "timestamp": f"{bar_date}T00:00:00",
                "open": bar["open"],
                "close": bar["close"],
                "price": bar["close"],
                "source": "market_bars",
            }

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            candidates = [
                close
                for close in self.daily_closes
                if close["symbol"] == symbol and close["trade_date"] < trade_date
            ]
            return candidates[-1] if candidates else None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 100000.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 6, 12, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    response = asyncio.run(endpoint(limit=50))
    timeline_by_date = {point.date: point for point in response.timeline}

    assert timeline_by_date["2026-06-12"].valuation_status == "live"
    assert timeline_by_date["2026-06-12"].missing_price_symbols == []
    assert timeline_by_date["2026-06-12"].market_pnl == pytest.approx(234.0)
    assert {
        item.key: item.value for item in timeline_by_date["2026-06-12"].market_breakdown
    } == pytest.approx({"stock": 234.0})


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


def test_portfolio_cockpit_returns_targets_drift_actions_and_risk_alerts(
    monkeypatch,
):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    cockpit_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/cockpit"
    )
    endpoint = cockpit_route.endpoint

    fake_position = SimpleNamespace(
        quantity=100,
        available_qty=100,
        frozen_qty=0,
        avg_cost=10,
        market_value=800,
        unrealized_pnl=100,
        realized_pnl=0,
        commission_paid=2,
    )

    async def fake_get_total_deposits():
        return 1000.0

    async def fake_get_action_tasks(statuses=None, limit=10):
        assert statuses == ["pending", "deferred"]
        return [
            {
                "id": 7,
                "source_signal_id": 3,
                "symbol": "600519",
                "title": "建议降至目标仓位",
                "detail": "dual_ma target 50%",
                "direction": "sell",
                "urgency": "medium",
                "target_weight": 0.5,
                "price": 8.0,
                "strategy_id": "dual_ma",
                "timestamp": "2026-04-18T09:40:00",
                "asset_class": "stock",
                "status": "pending",
                "risk_decision_id": "RISK-BLOCKED",
                "risk_gate_passed": False,
                "risk_gate_severity": "warning",
                "risk_gate_reasons": ["max position weight exceeded"],
                "risk_gate_status": "blocked",
                "manual_confirmation_required": True,
                "manual_confirmation_status": "blocked_by_risk_gate",
                "manual_confirmation_reason": "Risk gate blocked this action; do not execute without review.",
            }
        ]

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=1000),
        db=SimpleNamespace(
            get_total_deposits=fake_get_total_deposits,
            get_action_tasks=fake_get_action_tasks,
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=200,
                positions={"600519": fake_position},
            ),
            latest_quotes={},
            watchlist=[],
            instruments={},
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.summary.total_equity == 1000.0
    assert len(response.positions) == 1
    assert response.positions[0].symbol == "600519"
    assert response.positions[0].actual_weight == pytest.approx(0.8)
    assert response.positions[0].target_weight == pytest.approx(0.5)
    assert response.positions[0].drift == pytest.approx(-0.3)
    assert response.positions[0].action_task.id == 7
    assert len(response.action_queue) == 1
    assert response.action_queue[0].risk_gate_passed is False
    assert response.action_queue[0].risk_gate_status == "blocked"
    assert response.action_queue[0].manual_confirmation_required is True
    assert response.action_queue[0].manual_confirmation_status == "blocked_by_risk_gate"
    assert response.risk_alerts[0].title == "仓位集中度偏高"


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
            self.watchlist_assets: list[dict] = []
            self.instrument_metadata: list[dict] = []

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

        def upsert_watchlist_asset_sync(self, **payload):
            self.watchlist_assets.append(payload)
            return payload

        def upsert_instrument_metadata_sync(self, **payload):
            self.instrument_metadata.append(payload)
            return payload

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
    assert fake_state.config.assets == []
    assert fake_state.db.watchlist_assets[0]["display_name"] == "华夏核心成长混合C"
    assert fake_state.db.instrument_metadata[0]["display_name"] == "华夏核心成长混合C"


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
            self.watchlist_assets: list[dict] = []
            self.instrument_metadata: list[dict] = []

        def add_pending_fund_order_sync(self, **payload):
            order_id = len(self.pending_orders) + 1
            self.pending_orders.append({"id": order_id, **payload})
            return order_id

        def upsert_watchlist_asset_sync(self, **payload):
            self.watchlist_assets.append(payload)
            return payload

        def upsert_instrument_metadata_sync(self, **payload):
            self.instrument_metadata.append(payload)
            return payload

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
    assert fake_state.config.assets == []
    assert fake_state.db.watchlist_assets[0]["symbol"] == "012710"


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
                "risk_decision_id": "RISK-BLOCKED",
                "risk_gate_passed": False,
                "risk_gate_severity": "warning",
                "risk_gate_reasons": ["max position weight exceeded"],
                "risk_gate_status": "blocked",
                "manual_confirmation_required": True,
                "manual_confirmation_status": "blocked_by_risk_gate",
                "manual_confirmation_reason": "Risk gate blocked this action; do not execute without review.",
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
                "risk_decision_id": None,
                "risk_gate_passed": None,
                "risk_gate_severity": None,
                "risk_gate_reasons": [],
                "risk_gate_status": "not_checked",
                "manual_confirmation_required": True,
                "manual_confirmation_status": "awaiting_risk_gate",
                "manual_confirmation_reason": "Risk gate has not produced a decision yet.",
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
    assert response[0].risk_decision_id == "RISK-BLOCKED"
    assert response[0].risk_gate_passed is False
    assert response[0].risk_gate_severity == "warning"
    assert response[0].risk_gate_reasons == ["max position weight exceeded"]
    assert response[0].risk_gate_status == "blocked"
    assert response[0].manual_confirmation_required is True
    assert response[0].manual_confirmation_status == "blocked_by_risk_gate"
    assert response[1].title == "建议减仓 510300"
    assert response[1].urgency == "medium"
    assert response[1].risk_gate_status == "not_checked"
    assert response[1].manual_confirmation_status == "awaiting_risk_gate"
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


def test_signal_journal_route_returns_auditable_chain(monkeypatch):
    from server.routes import signals as signal_routes

    router = signal_routes.create_router()
    journal_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/signals/journal"
    )
    endpoint = journal_route.endpoint

    async def fake_list_signal_journal(limit=20, offset=0):
        assert limit == 20
        assert offset == 0
        return [
            {
                "signal": {
                    "id": 1,
                    "timestamp": "2026-04-18T09:35:00",
                    "strategy_id": "dual_ma",
                    "symbol": "600519",
                    "direction": "buy",
                    "target_weight": 0.2,
                    "price": 123.45,
                    "asset_class": "stock",
                },
                "action_task": {
                    "id": 9,
                    "source_signal_id": 1,
                    "status": "pending",
                    "title": "建议增持 600519",
                    "detail": "dual_ma 触发，目标仓位 20%",
                    "symbol": "600519",
                    "direction": "buy",
                    "urgency": "high",
                    "target_weight": 0.2,
                    "price": 123.45,
                    "strategy_id": "dual_ma",
                    "timestamp": "2026-04-18T09:35:00",
                    "asset_class": "stock",
                },
                "risk_decision": {
                    "decision_id": "RISK-1",
                    "intent_id": "INTENT-1",
                    "passed": False,
                    "symbol": "600519",
                    "side": "buy",
                    "reasons": ["max position weight exceeded"],
                    "severity": "warning",
                    "timestamp": "2026-04-18T14:50:00",
                    "payload": {"decision": {"passed": False}},
                },
                "latest_event": {
                    "event_type": "risk.signal.recorded",
                    "timestamp": "2026-04-18T14:50:00",
                    "source": "risk_decisions",
                    "source_ref": "RISK-1",
                    "payload": {"risk_decision_id": 1},
                },
            }
        ]

    fake_state = SimpleNamespace(
        db=SimpleNamespace(list_signal_journal=fake_list_signal_journal)
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert len(response) == 1
    assert response[0].signal.symbol == "600519"
    assert response[0].action_task.status == "pending"
    assert response[0].risk_decision.passed is False
    assert response[0].latest_event.event_type == "risk.signal.recorded"


def test_decision_today_returns_candidate_with_evidence_bundle(monkeypatch):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    today_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/decision/today"
    )
    endpoint = today_route.endpoint

    class FakeDb:
        def get_action_tasks_sync(self, statuses=None, limit=50, offset=0):
            assert statuses == ["pending", "deferred"]
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
                    "risk_decision_id": "RISK-1",
                    "risk_gate_status": "passed",
                    "risk_gate_passed": True,
                    "risk_gate_severity": "info",
                    "risk_gate_reasons": [],
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "ready_for_manual_confirmation",
                    "manual_confirmation_reason": "Risk gate passed; operator confirmation is still required.",
                }
            ]

        def list_signal_journal_sync(self, limit=50, offset=0):
            return [
                {
                    "signal": {
                        "id": 1,
                        "timestamp": "2026-04-18T09:35:00",
                        "strategy_id": "dual_ma",
                        "symbol": "600519",
                        "direction": "buy",
                        "target_weight": 0.2,
                        "price": 123.45,
                        "asset_class": "stock",
                    },
                    "latest_event": {
                        "event_type": "risk.signal.recorded",
                        "source": "risk_decisions",
                        "source_ref": "RISK-1",
                    },
                }
            ]

        def get_latest_quote_sync(self, symbol, asset_type=None):
            return {
                "symbol": symbol,
                "asset_type": asset_type or "stock",
                "price": 123.45,
                "quote_status": "live",
                "quote_timestamp": "2026-04-18T09:34:00+08:00",
                "quote_source": "fixture",
            }

    fake_state = SimpleNamespace(db=FakeDb())
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response["lane"] == "daily"
    assert response["decision"] == "buy"
    assert response["requires_manual_confirmation"] is True
    assert response["no_action_reasons"] == []
    assert response["summary"]["candidate_count"] == 1
    candidate = response["candidates"][0]
    assert candidate["action"] == "buy"
    assert candidate["manual_confirmation_status"] == "ready_for_manual_confirmation"
    assert candidate["evidence"]["strategy"]["strategy_id"] == "dual_ma"
    assert candidate["evidence"]["signal"]["id"] == 1
    assert candidate["evidence"]["risk_gate"]["status"] == "passed"
    assert candidate["evidence"]["data_freshness"]["status"] == "live"
    assert candidate["evidence"]["manual_confirmation"]["required"] is True
    assert candidate["evidence"]["journal"]["latest_event_type"] == (
        "risk.signal.recorded"
    )
    assert "not investment advice" in response["limitations"][0]


def test_decision_today_attaches_latest_after_cost_oos_validation(monkeypatch):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    today_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/decision/today"
    )
    endpoint = today_route.endpoint

    class FakeDb:
        def get_action_tasks_sync(self, statuses=None, limit=50, offset=0):
            return [
                {
                    "id": 9,
                    "source_signal_id": 1,
                    "symbol": "600519",
                    "direction": "buy",
                    "strategy_id": "dual_ma",
                    "asset_class": "stock",
                    "risk_gate_status": "passed",
                    "risk_gate_passed": True,
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "ready_for_manual_confirmation",
                }
            ]

        def list_signal_journal_sync(self, limit=50, offset=0):
            return []

        def get_latest_quote_sync(self, symbol, asset_type=None):
            return {
                "symbol": symbol,
                "price": 123.45,
                "quote_status": "live",
                "quote_timestamp": "2026-04-18T09:34:00+08:00",
                "quote_source": "fixture",
            }

        async def get_backtest_results(self):
            return [
                {
                    "id": 101,
                    "created_at": "2026-04-17T15:30:00",
                    "config_json": json.dumps({"strategy": "dual_ma"}),
                    "total_return": 0.08,
                    "sharpe": 1.2,
                    "max_drawdown": 0.05,
                    "metrics_json": json.dumps(
                        {
                            "evidence_bundle": {
                                "schema_version": 1,
                                "gross_return": 0.1,
                                "net_return": 0.08,
                                "total_commission": 12.3,
                                "total_slippage": 4.5,
                                "limitations": [
                                    "Backtest evidence is not a profitability claim."
                                ],
                            },
                            "oos_validation": {
                                "schema_version": 1,
                                "strategy_id": "dual_ma",
                                "validation_status": "passed",
                                "out_of_sample": {
                                    "net_return": 0.03,
                                    "benchmark_excess_return": 0.01,
                                },
                            },
                        }
                    ),
                    "cost_summary_json": json.dumps(
                        {"commission": 12.3, "slippage": 4.5}
                    ),
                }
            ]

    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=FakeDb()),
    )

    response = asyncio.run(endpoint())

    validation = response["candidates"][0]["evidence"]["after_cost_oos_validation"]
    assert validation["status"] == "attached"
    assert validation["strategy_id"] == "dual_ma"
    assert validation["backtest_result_id"] == 101
    assert validation["has_after_cost_report"] is True
    assert validation["has_out_of_sample_validation"] is True
    assert validation["after_cost"]["net_return"] == 0.08
    assert validation["oos_validation"]["validation_status"] == "passed"
    assert "not a profitability claim" in validation["limitations"][0]


def test_decision_today_summary_aggregates_portfolio_market_and_audit_state(
    monkeypatch,
):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    today_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/decision/today"
    )
    endpoint = today_route.endpoint

    class FakeDb:
        def get_action_tasks_sync(self, statuses=None, limit=50, offset=0):
            return [
                {
                    "id": 9,
                    "source_signal_id": 1,
                    "symbol": "600519",
                    "direction": "buy",
                    "strategy_id": "dual_ma",
                    "asset_class": "stock",
                    "status": "pending",
                    "risk_gate_status": "passed",
                    "risk_gate_passed": True,
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "ready_for_manual_confirmation",
                },
                {
                    "id": 10,
                    "source_signal_id": 2,
                    "symbol": "018125",
                    "direction": "hold",
                    "strategy_id": "monthly_rebalance",
                    "asset_class": "fund",
                    "status": "deferred",
                    "risk_gate_status": "blocked",
                    "risk_gate_passed": False,
                    "risk_gate_reasons": ["data_quality:stale_quote"],
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "blocked_by_risk_gate",
                },
            ]

        def list_signal_journal_sync(self, limit=50, offset=0):
            return [
                {
                    "signal": {"id": 1, "strategy_id": "dual_ma"},
                    "latest_event": {"event_type": "risk.signal.recorded"},
                },
                {
                    "signal": {"id": 2, "strategy_id": "monthly_rebalance"},
                    "latest_event": {"event_type": "risk.signal.recorded"},
                },
            ]

        def get_latest_quote_sync(self, symbol, asset_type=None):
            return {
                "symbol": symbol,
                "asset_type": asset_type,
                "price": 123.45 if symbol == "600519" else 2.34,
                "quote_status": "live" if symbol == "600519" else "stale",
                "quote_timestamp": (
                    "2026-04-18T09:34:00+08:00"
                    if symbol == "600519"
                    else "2026-04-17T15:00:00+08:00"
                ),
                "quote_source": "fixture",
            }

        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_type": "stock",
                    "price": 123.45,
                    "quote_status": "live",
                    "quote_timestamp": "2026-04-18T09:34:00+08:00",
                    "quote_source": "fixture",
                },
                {
                    "symbol": "018125",
                    "asset_type": "fund",
                    "price": 2.34,
                    "quote_status": "stale",
                    "quote_timestamp": "2026-04-17T15:00:00+08:00",
                    "quote_source": "fixture",
                },
            ]

        async def get_backtest_results(self):
            return []

    fake_portfolio = SimpleNamespace(
        cash=12000.0,
        positions={
            "600519": SimpleNamespace(market_value=20000.0),
            "018125": SimpleNamespace(market_value=8000.0),
        },
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            assets=[
                {"symbol": "600519", "asset_class": "stock"},
                {"symbol": "018125", "asset_class": "fund"},
            ]
        ),
        scheduler=SimpleNamespace(
            portfolio=fake_portfolio,
            latest_quotes={},
            watchlist=[("600519", "stock"), ("018125", "fund")],
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    summary = response["summary"]
    assert summary["portfolio"]["status"] == "available"
    assert summary["portfolio"]["cash"] == 12000.0
    assert summary["portfolio"]["position_count"] == 2
    assert summary["portfolio"]["total_market_value"] == 28000.0
    assert summary["portfolio"]["total_equity"] == 40000.0
    assert summary["market_data"]["source_health"] == "partial"
    assert summary["market_data"]["quote_count"] == 2
    assert summary["market_data"]["live_quote_count"] == 1
    assert summary["market_data"]["stale_quote_count"] == 1
    assert summary["market_data"]["missing_symbols"] == []
    assert summary["market_data"]["latest_quote_timestamp"] == (
        "2026-04-18T09:34:00+08:00"
    )
    assert summary["action_tasks"]["pending_count"] == 1
    assert summary["action_tasks"]["deferred_count"] == 1
    assert summary["audit"]["signal_count"] == 2
    assert summary["audit"]["journal_entry_count"] == 2
    assert summary["audit"]["risk_checked_count"] == 2
    assert summary["audit"]["risk_blocked_count"] == 1


def test_decision_today_returns_no_action_reason(monkeypatch):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    today_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/decision/today"
    )
    endpoint = today_route.endpoint

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            get_action_tasks_sync=lambda statuses=None, limit=50, offset=0: [],
            list_signal_journal_sync=lambda limit=50, offset=0: [],
            get_latest_quote_sync=lambda symbol, asset_type=None: None,
        )
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response["decision"] == "no_action"
    assert response["summary"]["candidate_count"] == 0
    assert response["no_action_reasons"] == ["no_pending_action_tasks"]
    assert response["requires_manual_confirmation"] is False


def test_decision_intraday_returns_stock_and_etf_candidates_only(monkeypatch):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    intraday_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/decision/intraday"
    )
    endpoint = intraday_route.endpoint

    class FakeDb:
        def get_action_tasks_sync(self, statuses=None, limit=50, offset=0):
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
                    "risk_decision_id": "RISK-STOCK",
                    "risk_gate_status": "passed",
                    "risk_gate_passed": True,
                    "risk_gate_severity": "info",
                    "risk_gate_reasons": [],
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "ready_for_manual_confirmation",
                },
                {
                    "id": 10,
                    "source_signal_id": 2,
                    "symbol": "510300",
                    "title": "建议减仓 510300",
                    "detail": "ETF rotation 触发，目标仓位 0%",
                    "direction": "sell",
                    "urgency": "medium",
                    "target_weight": 0.0,
                    "price": 4.56,
                    "strategy_id": "dual_ma",
                    "timestamp": "2026-04-18T09:36:00",
                    "asset_class": "fund",
                    "status": "pending",
                    "risk_decision_id": "RISK-ETF",
                    "risk_gate_status": "passed",
                    "risk_gate_passed": True,
                    "risk_gate_severity": "info",
                    "risk_gate_reasons": [],
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "ready_for_manual_confirmation",
                },
                {
                    "id": 11,
                    "source_signal_id": 3,
                    "symbol": "018125",
                    "title": "建议申购 018125",
                    "detail": "长期配置日级检查",
                    "direction": "buy",
                    "urgency": "low",
                    "target_weight": 0.1,
                    "price": 1.23,
                    "strategy_id": "monthly_rebalance",
                    "timestamp": "2026-04-18T09:37:00",
                    "asset_class": "fund",
                    "status": "pending",
                    "risk_gate_status": "passed",
                    "risk_gate_passed": True,
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "ready_for_manual_confirmation",
                },
            ]

        def list_signal_journal_sync(self, limit=50, offset=0):
            return [
                {
                    "signal": {
                        "id": 1,
                        "strategy_id": "dual_ma",
                        "symbol": "600519",
                        "target_weight": 0.2,
                    },
                    "latest_event": {"event_type": "risk.signal.recorded"},
                },
                {
                    "signal": {
                        "id": 2,
                        "strategy_id": "dual_ma",
                        "symbol": "510300",
                        "target_weight": 0.0,
                    },
                    "latest_event": {"event_type": "risk.signal.recorded"},
                },
            ]

        def get_latest_quote_sync(self, symbol, asset_type=None):
            return {
                "symbol": symbol,
                "asset_type": asset_type or "stock",
                "price": 123.45 if symbol == "600519" else 4.56,
                "quote_status": "live",
                "quote_timestamp": "2026-04-18T09:34:00+08:00",
                "quote_source": "fixture",
            }

    fake_state = SimpleNamespace(db=FakeDb())
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response["lane"] == "intraday"
    assert response["decision"] == "rebalance"
    assert response["summary"]["candidate_count"] == 2
    assert response["summary"]["excluded_daily_count"] == 1
    assert [candidate["symbol"] for candidate in response["candidates"]] == [
        "600519",
        "510300",
    ]
    assert response["candidates"][1]["asset_class"] == "fund"
    assert response["candidates"][1]["evidence"]["data_freshness"]["status"] == "live"
    assert response["excluded_daily_symbols"] == ["018125"]
    assert response["no_action_reasons"] == []


def test_decision_intraday_returns_no_action_reason_when_only_daily_assets(
    monkeypatch,
):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    intraday_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/decision/intraday"
    )
    endpoint = intraday_route.endpoint

    fake_state = SimpleNamespace(
        db=SimpleNamespace(
            get_action_tasks_sync=lambda statuses=None, limit=50, offset=0: [
                {
                    "id": 11,
                    "source_signal_id": 3,
                    "symbol": "018125",
                    "direction": "buy",
                    "asset_class": "fund",
                    "status": "pending",
                    "manual_confirmation_required": True,
                    "manual_confirmation_status": "ready_for_manual_confirmation",
                }
            ],
            list_signal_journal_sync=lambda limit=50, offset=0: [],
            get_latest_quote_sync=lambda symbol, asset_type=None: None,
        )
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response["decision"] == "no_action"
    assert response["summary"]["candidate_count"] == 0
    assert response["summary"]["excluded_daily_count"] == 1
    assert response["no_action_reasons"] == ["no_intraday_stock_or_etf_action_tasks"]
    assert response["excluded_daily_symbols"] == ["018125"]


def test_backtest_strategies_route_returns_benchmark_metadata():
    from server.routes import backtest as backtest_routes

    router = backtest_routes.create_router()
    strategies_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/backtest/strategies"
    )
    endpoint = strategies_route.endpoint

    response = asyncio.run(endpoint())
    by_name = {item.name: item for item in response}

    assert by_name["dual_ma"].benchmark_role == "etf_rotation_trend_following"
    assert by_name["dual_ma"].requires_out_of_sample_validation is True
    assert by_name["dual_ma"].requires_after_cost_report is True
    assert by_name["monthly_rebalance"].benchmark_role == "defensive_allocation"
    assert by_name["bollinger"].benchmark_role == "a_share_or_etf_mean_reversion"
    assert by_name["rsi"].benchmark_role is None


def test_backtest_strategy_validation_route_returns_evidence_matrix(monkeypatch):
    from analytics.benchmark_fixtures import build_benchmark_fixture_backtest_rows
    from server.routes import backtest as backtest_routes

    class FakeDb:
        async def get_backtest_results(self):
            return build_benchmark_fixture_backtest_rows()

    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=FakeDb()),
    )

    router = backtest_routes.create_router()
    validation_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/backtest/strategy-validation"
    )

    response = asyncio.run(validation_route.endpoint())
    by_strategy = {row.strategy_id: row for row in response.rows}

    assert response.required_strategy_count == 3
    assert response.ready_strategy_count == 3
    assert response.is_complete is True
    assert set(by_strategy) == {"dual_ma", "monthly_rebalance", "bollinger"}
    assert by_strategy["dual_ma"].benchmark_role == "etf_rotation_trend_following"
    assert by_strategy["monthly_rebalance"].has_after_cost_report is True
    assert by_strategy["bollinger"].has_out_of_sample_validation is True
    assert all(row.missing_requirements == [] for row in response.rows)
    assert "not investment advice" in response.limitations[0]


def test_backtest_strategy_promotion_readiness_route_requires_all_gates(monkeypatch):
    from analytics.benchmark_fixtures import build_benchmark_fixture_backtest_rows
    from server.routes import backtest as backtest_routes

    class FakeDb:
        async def get_backtest_results(self):
            return build_benchmark_fixture_backtest_rows()

        def get_risk_decisions_sync(self, limit=500, offset=0):
            return [
                {
                    "decision_id": f"RISK-{strategy_id}",
                    "passed": 0,
                    "payload_json": json.dumps(
                        {
                            "intent": {"strategy_id": strategy_id},
                            "decision": {
                                "passed": False,
                                "reasons": ["unsafe test condition"],
                            },
                        }
                    ),
                }
                for strategy_id in ("dual_ma", "monthly_rebalance", "bollinger")
            ]

        def list_orders_sync(self, limit=500, offset=0):
            return [
                {
                    "order_id": f"SHADOW-{strategy_id}",
                    "execution_mode": "paper_shadow",
                    "status": "shadow_recorded",
                    "payload_json": json.dumps(
                        {
                            "strategy_id": strategy_id,
                            "divergence_status": "within_expectations",
                        }
                    ),
                }
                for strategy_id in ("dual_ma", "monthly_rebalance", "bollinger")
            ]

    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=FakeDb()),
    )

    router = backtest_routes.create_router()
    promotion_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/backtest/strategy-promotion-readiness"
    )

    response = asyncio.run(promotion_route.endpoint())

    assert response.required_strategy_count == 3
    assert response.promotable_strategy_count == 3
    assert response.is_complete is True
    assert all(row.is_promotable for row in response.rows)
    assert all(
        row.promotion_status == "promotable_for_paper_review" for row in response.rows
    )
    assert "manual confirmation" in response.limitations[1]


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
        config=SimpleNamespace(initial_cash=0, data_source="akshare", assets=[]),
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
        config=SimpleNamespace(initial_cash=0, data_source="akshare", assets=[]),
        scheduler=SimpleNamespace(
            portfolio=None, latest_quotes={}, watchlist=[], instruments={}
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    series = asyncio.run(endpoint())

    assert len(series) > 7
    assert series[0].timestamp.endswith("T15:00:00+08:00")
    assert series[0].stocks == pytest.approx(11000.0)
    assert series[0].funds == pytest.approx(5300.0)
    assert series[0].others == pytest.approx(9250.0)
    assert series[0].cash == pytest.approx(76000.0)
    assert series[0].total == pytest.approx(101550.0)
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
                    "timestamp": "2026-04-20T09:40:00",
                    "previous_close": 1000.0,
                    "previous_close_date": "2026-04-17",
                },
                {
                    "symbol": "510300",
                    "asset_class": "etf",
                    "price": 3.2,
                    "timestamp": "2026-04-20T09:40:00",
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
                            ["2026-04-20T09:35:00", "2026-04-20T09:40:00"]
                        ),
                        "close": [1005.0, 1010.0],
                    }
                )
            if str(symbol) == "510300":
                return pd.DataFrame(
                    {
                        "timestamp": pd.to_datetime(
                            ["2026-04-20T09:35:00", "2026-04-20T09:40:00"]
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
        lambda now=None: datetime(2026, 4, 20, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")),
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
                    "timestamp": "2026-04-20T09:00:00+00:00",
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
                    "created_at": "2026-04-20T09:00:01+00:00",
                }
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "price": 1000.0,
                    "timestamp": "2026-04-20T09:20:00",
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
        lambda now=None: datetime(2026, 4, 20, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    series = asyncio.run(endpoint("1d"))

    assert series[0].timestamp.startswith("2026-04-20T09:30:00")
    assert series[-1].timestamp.startswith("2026-04-20T15:00:00")
    assert all(point.total == pytest.approx(60000.0) for point in series)
    assert all(point.unrealized_pnl == pytest.approx(0.0) for point in series)


def test_portfolio_equity_curve_series_1d_skips_intraday_source_when_market_closed(
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
    endpoint = curve_route.endpoint

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
            intraday_curve_timeout_seconds=4.0,
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
                    "timestamp": "2026-06-14T09:59:00+08:00",
                }
            ]
        ),
    )

    class UnexpectedSource:
        def fetch_bars(self, symbol, start, end, frequency, asset_class):
            raise AssertionError("closed market 1d curve must not fetch intraday bars")

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": UnexpectedSource()},
    )
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 6, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    series = asyncio.run(endpoint("1d"))

    assert [point.timestamp[11:16] for point in series[:2]] == ["09:30", "09:35"]
    assert series[-1].timestamp.startswith("2026-06-14T15:00:00")
    assert all(point.total == pytest.approx(100200.0) for point in series)
    assert all(point.stocks == pytest.approx(1200.0) for point in series)


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


def test_portfolio_live_holdings_merges_materialized_previous_close(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )

    fake_position = SimpleNamespace(
        quantity=100.0,
        available_qty=100.0,
        frozen_qty=0.0,
        avg_cost=8.7401,
        market_value=925.0,
        unrealized_pnl=50.99,
        realized_pnl=0.0,
        commission_paid=5.01,
    )

    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "601985",
                    "asset_type": "stock",
                    "price": 9.25,
                    "quote_timestamp": "2026-06-04",
                    "quote_source": "tushare_daily",
                    "provider_name": "tushare",
                    "quote_status": "live",
                    "previous_close": 9.26,
                    "change": -0.01,
                    "change_percent": -0.00108,
                }
            ]

        def get_latest_quotes_sync(self):
            return []

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

        async def get_total_deposits(self):
            return 0.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0, live_poll_interval=120),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=0.0, positions={"601985": fake_position}),
            instruments={
                "601985": SimpleNamespace(
                    name="中国核电",
                    asset_class=SimpleNamespace(value="stock"),
                )
            },
            watchlist=[],
            latest_quotes={
                "601985": {
                    "symbol": "601985",
                    "asset_class": "stock",
                    "price": 9.25,
                    "timestamp": "2026-06-04",
                    "quote_source": "tushare_daily",
                }
            },
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(live_holdings_route.endpoint())

    item = response.groups[0].items[0]
    assert item.symbol == "601985"
    assert item.baseline_price == 9.26
    assert item.baseline_source == "previous_close"
    assert item.today_change == pytest.approx(-1.0)
    assert item.today_change_pct == pytest.approx(9.25 / 9.26 - 1)


def test_portfolio_live_holdings_does_not_block_on_remote_refresh(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    live_holdings_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )

    fake_position = SimpleNamespace(
        quantity=100.0,
        available_qty=100.0,
        frozen_qty=0.0,
        avg_cost=8.7401,
        market_value=925.0,
        unrealized_pnl=50.99,
        realized_pnl=0.0,
        commission_paid=5.01,
    )
    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0, live_poll_interval=1),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=0.0, positions={"601985": fake_position}),
            instruments={
                "601985": SimpleNamespace(
                    name="中国核电",
                    asset_class=SimpleNamespace(value="stock"),
                )
            },
            watchlist=[],
            latest_quotes={
                "601985": {
                    "symbol": "601985",
                    "asset_class": "stock",
                    "price": 9.25,
                    "timestamp": "2026-05-01",
                    "quote_source": "tushare_daily",
                    "previous_close": 9.26,
                    "previous_close_date": "2026-05-01",
                }
            },
        ),
        db=SimpleNamespace(
            list_latest_quotes_sync=lambda: [],
            get_latest_quotes_sync=lambda: [],
            get_latest_daily_close_before_sync=lambda symbol, trade_date: None,
            get_latest_quote_before_date_sync=lambda symbol, trade_date: None,
            get_total_deposits=lambda: 0.0,
        ),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.market._fetch_latest_snapshot",
        lambda *args, **kwargs: pytest.fail("live holdings must not fetch remotely"),
    )

    response = asyncio.run(live_holdings_route.endpoint())

    assert response.groups[0].items[0].latest_price == 9.25


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


def test_portfolio_snapshot_does_not_refresh_stale_quote_in_request(monkeypatch):
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

    assert response.positions[0].market_value == 1000.0
    assert response.positions[0].unrealized_pnl == 0.0
    assert response.positions[0].quote_status == "stale"
    assert response.positions[0].quote_timestamp == "2026-04-22T15:00:00"
    assert fake_state.scheduler.latest_quotes == {}


def test_portfolio_snapshot_does_not_fetch_missing_ledger_quote_in_request(monkeypatch):
    from zoneinfo import ZoneInfo

    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    snapshot_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio"
    )

    fetched: list[tuple[str, str]] = []

    class FakeDb:
        def get_latest_quotes_sync(self):
            return []

        def list_latest_quotes_sync(self):
            return []

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

        def save_quote_snapshot_sync(self, **kwargs):
            pass

        async def get_total_deposits(self):
            return 0.0

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=0,
            data_source="akshare",
            tushare_token="",
            live_poll_interval=60,
            assets=[],
        ),
        scheduler=SimpleNamespace(
            portfolio=None,
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )

    class FakeSource:
        def fetch_latest(self, symbol, asset_class):
            fetched.append((str(symbol), asset_class.value))
            return {
                "price": 31.0,
                "volume": 2000.0,
                "timestamp": "2026-06-04T10:05:00+08:00",
                "display_name": "璞泰来",
                "previous_close": 30.1,
                "previous_close_date": "2026-06-03",
            }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        portfolio_routes,
        "get_shanghai_now",
        lambda now=None: datetime(2026, 6, 4, 10, 6, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    monkeypatch.setattr(
        "server.routes.market.is_cn_trading_session",
        lambda now=None: True,
    )
    monkeypatch.setattr(
        "data.manager.build_sources",
        lambda **kwargs: {"akshare": FakeSource()},
    )

    response = asyncio.run(snapshot_route.endpoint())

    assert fetched == []
    assert response.positions[0].symbol == "603659"
    assert response.positions[0].display_name == "璞泰来"
    assert response.positions[0].market_value == pytest.approx(3003.03)
    assert response.positions[0].quote_status == "missing"
    assert response.positions[0].quote_timestamp is None


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
        config=SimpleNamespace(
            initial_cash=0,
            data_source="akshare",
            assets=[
                {
                    "symbol": "600519",
                    "asset_class": "stock",
                    "display_name": "贵州茅台",
                }
            ],
        ),
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
    assert response.groups[0].items[0].name == "贵州茅台"
    assert response.groups[0].items[0].display_name == "贵州茅台"
    assert response.groups[0].items[0].quote_timestamp == "2026-04-22T15:00:00"
    assert response.groups[0].items[0].quote_source == "akshare"
    assert response.groups[0].items[0].quote_age_seconds is not None
    assert response.groups[0].items[0].stale_reason == "market_closed_cache_only"
    assert response.groups[0].items[0].refresh_policy == "cache_only"
    assert overview.quote_status == "stale"
    assert overview.quote_age_seconds is not None
    assert overview.stale_reason == "market_closed_cache_only"
    assert overview.refresh_policy == "cache_only"


def test_portfolio_live_holdings_uses_dict_asset_mapping(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )

    fake_position = SimpleNamespace(
        quantity=100.0,
        available_qty=100.0,
        frozen_qty=0.0,
        avg_cost=1.0,
        market_value=120.0,
        unrealized_pnl=20.0,
        realized_pnl=0.0,
        commission_paid=0.0,
    )

    class FakeDb:
        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "012710",
                    "asset_class": "fund",
                    "price": 1.2,
                    "timestamp": "2026-05-22T09:30:00+08:00",
                    "source": "akshare",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

    fake_state = SimpleNamespace(
        config=SimpleNamespace(
            initial_cash=0,
            data_source="akshare",
            instruments=[],
            assets={
                "012710": {
                    "display_name": "示例基金C",
                    "asset_class": "fund",
                    "provider_symbol": "012710",
                }
            },
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(cash=0.0, positions={"012710": fake_position}),
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())

    assert response.groups[0].items[0].name == "示例基金C"
    assert response.groups[0].items[0].display_name == "示例基金C"


def test_portfolio_live_holdings_prefers_latest_quote_identity(monkeypatch):
    from server.routes import portfolio as portfolio_routes

    router = portfolio_routes.create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/portfolio/live-holdings"
    )

    class FakeDb:
        def list_latest_quotes_sync(self):
            return [
                {
                    "symbol": "012710",
                    "asset_type": "fund",
                    "price": 0.9477,
                    "quote_timestamp": "2026-05-22",
                    "quote_source": "akshare",
                    "provider_name": "akshare",
                    "metadata_json": '{"display_name":"华夏核心成长混合C"}',
                },
                {
                    "symbol": "600519",
                    "asset_type": "stock",
                    "price": 1650.0,
                    "quote_timestamp": "2026-05-22T14:30:00+08:00",
                    "quote_source": "akshare",
                    "provider_name": "akshare",
                    "metadata_json": '{"display_name":"贵州茅台"}',
                },
            ]

        def get_latest_quotes_sync(self):
            return [
                {
                    "symbol": "012710",
                    "asset_class": "stock",
                    "price": 0.90,
                    "timestamp": "2026-05-21T15:00:00+08:00",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            return None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

    fake_state = SimpleNamespace(
        config=SimpleNamespace(initial_cash=0, assets=[]),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(
                cash=0.0,
                positions={
                    "012710": SimpleNamespace(
                        quantity=100.0,
                        avg_cost=1.0,
                        market_value=94.77,
                        unrealized_pnl=-5.23,
                    ),
                    "600519": SimpleNamespace(
                        quantity=1.0,
                        avg_cost=1500.0,
                        market_value=1650.0,
                        unrealized_pnl=150.0,
                    ),
                },
            ),
            instruments={},
            watchlist=[],
            latest_quotes={},
        ),
        db=FakeDb(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    response = asyncio.run(endpoint())
    groups = {group.asset_class: group for group in response.groups}

    assert set(groups) == {"fund", "stock"}
    assert groups["fund"].label == "基金"
    assert groups["fund"].items[0].name == "华夏核心成长混合C"
    assert groups["fund"].items[0].display_name == "华夏核心成长混合C"
    assert groups["fund"].items[0].asset_class == "fund"
    assert groups["fund"].items[0].quote_timestamp == "2026-05-22"
    assert groups["stock"].items[0].name == "贵州茅台"


def test_collect_latest_quotes_prefers_newer_persistent_quote_over_runtime():
    from server.routes import portfolio as portfolio_routes

    fake_state = SimpleNamespace(
        scheduler=SimpleNamespace(
            latest_quotes={
                "601985": {
                    "symbol": "601985",
                    "asset_class": "stock",
                    "price": 9.13,
                    "timestamp": "2026-06-05T 11:01:13",
                    "quote_source": "tushare_realtime_quote",
                    "display_name": "中国核电",
                }
            }
        ),
        db=SimpleNamespace(
            list_latest_quotes_sync=lambda: [
                {
                    "symbol": "601985",
                    "asset_type": "stock",
                    "price": 8.99,
                    "quote_timestamp": "2026-06-05",
                    "quote_source": "tushare_daily",
                    "provider_name": "tushare",
                    "display_name": "中国核电",
                    "captured_at": "2026-06-05T22:23:17+08:00",
                }
            ],
            get_latest_quotes_sync=lambda: [],
        ),
    )

    latest = portfolio_routes._collect_latest_quotes(fake_state)

    assert latest["601985"]["price"] == 8.99
    assert latest["601985"]["timestamp"] == "2026-06-05"
    assert latest["601985"]["quote_source"] == "tushare_daily"
    assert latest["601985"]["display_name"] == "中国核电"


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

    assert len(series) > 5
    assert series[0].timestamp.startswith("2026-04-20")
    assert any(point.timestamp.startswith("2026-05-08") for point in series)
    assert series[-1].timestamp.startswith("2026-05-12T20:00:00")
    assert series[-1].total == 100200.0
    assert series[-1].stocks == 1200.0
    assert series[-1].cash == 99000.0
    assert series[-1].quote_status == "stale"


def test_portfolio_equity_curve_series_uses_daily_close_history(monkeypatch):
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
        daily_closes = [
            {
                "symbol": "600519",
                "asset_class": "stock",
                "trade_date": "2026-04-22",
                "close_price": 10.5,
                "source": "test_close",
            },
            {
                "symbol": "600519",
                "asset_class": "stock",
                "trade_date": "2026-05-08",
                "close_price": 11.0,
                "source": "test_close",
            },
        ]

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
                    "timestamp": "2026-05-12T15:00:00+08:00",
                }
            ]

        def get_latest_daily_close_before_sync(self, symbol: str, trade_date: str):
            candidates = [
                close
                for close in self.daily_closes
                if close["symbol"] == symbol and close["trade_date"] < trade_date
            ]
            return candidates[-1] if candidates else None

        def get_latest_quote_before_date_sync(self, symbol: str, trade_date: str):
            return None

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

    apr22 = next(point for point in series if point.timestamp.startswith("2026-04-22"))
    may8 = next(point for point in series if point.timestamp.startswith("2026-05-08"))

    assert apr22.total == pytest.approx(100050.0)
    assert apr22.stocks == pytest.approx(1050.0)
    assert may8.total == pytest.approx(100100.0)
    assert may8.stocks == pytest.approx(1100.0)
    assert series[-1].timestamp.startswith("2026-05-12T20:00:00")
    assert series[-1].total == pytest.approx(100200.0)


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
            raise AssertionError("slow source should not control response")

    async def slow_intraday_builder(func, *args, **kwargs):
        await asyncio.sleep(0.2)
        return func(*args, **kwargs)

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(portfolio_routes.asyncio, "to_thread", slow_intraday_builder)
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

    assert len(series) > 1
    assert series[0].timestamp.startswith("2026-05-12T09:30:00")
    assert series[-1].timestamp.startswith("2026-05-12T15:00:00")
    assert {point.total for point in series} == {100200.0}
    assert {point.quote_status for point in series} == {"live"}
