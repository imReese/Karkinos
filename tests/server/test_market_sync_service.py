"""Tests for MarketSyncService and sync HTTP endpoints."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.market_calendar import MarketCalendarSnapshot
from data.store import DataStore
from server.contracts.http.market import MarketSyncApiRequest
from server.db import AppDatabase
from server.http.market_endpoints.dependencies import RefreshEndpointDependencies
from server.http.market_endpoints.refresh import create_router
from server.services.market_sync import (
    DEFAULT_BENCHMARK_INDICES,
    DEFAULT_ETFS,
    MarketSyncItem,
    MarketSyncRequest,
    MarketSyncService,
    SyncTarget,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def temp_data_env(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    app_db = data_dir / "app.db"
    meta_db = data_dir / "meta.db"

    import sqlite3

    from data.meta_store_schema import prepare_meta_database
    from server.persistence.initializer import initialize_database

    initialize_database(app_db)
    prepare_meta_database(meta_db)
    return data_dir


def test_resolve_targets_core(temp_data_env):
    service = MarketSyncService(data_dir=temp_data_env)
    targets = service.resolve_targets(MarketSyncRequest(universe="core"))
    symbols = {t.symbol for t in targets}

    for sym, _ in DEFAULT_BENCHMARK_INDICES:
        assert sym in symbols
    for sym, _ in DEFAULT_ETFS:
        assert sym in symbols
    assert "018125" in symbols  # Default fund
    assert "601985" in symbols  # Default stock


def test_resolve_targets_custom_symbols(temp_data_env):
    service = MarketSyncService(data_dir=temp_data_env)
    targets = service.resolve_targets(
        MarketSyncRequest(symbols=["000001", "510300", "018125", "600519"])
    )
    by_sym = {t.symbol: t for t in targets}
    assert by_sym["000001"].instrument_type == InstrumentType.INDEX
    assert by_sym["510300"].instrument_type == InstrumentType.ETF
    assert by_sym["018125"].instrument_type == InstrumentType.OPEN_END_FUND
    assert by_sym["600519"].instrument_type == InstrumentType.STOCK


def test_sync_calendar(temp_data_env):
    service = MarketSyncService(data_dir=temp_data_env)
    mock_provider = MagicMock()
    from data.market_calendar import MarketCalendarDay, MarketCalendarDayType

    days = (
        MarketCalendarDay(
            date="2026-01-05",
            day_type=MarketCalendarDayType.TRADING_DAY,
            reason_code="trading_day",
            reason="trading_day",
            is_trading_day=True,
        ),
        MarketCalendarDay(
            date="2026-01-01",
            day_type=MarketCalendarDayType.HOLIDAY,
            reason_code="new_years_day",
            reason="元旦",
            is_trading_day=False,
        ),
    )
    mock_provider.fetch_snapshot.return_value = MarketCalendarSnapshot(
        exchange="SSE",
        year=2026,
        provider="akshare",
        days=days,
        source_fingerprint="test_fp",
        fetched_at="2026-01-01T00:00:00",
    )

    with patch(
        "server.services.market_sync.build_market_calendar_provider",
        return_value=mock_provider,
    ):
        synced = service.sync_calendar(2026, 2026, force=True)
        assert synced == [2026]

        # Second run without force should skip already-synced year
        synced_cached = service.sync_calendar(2026, 2026, force=False)
        assert synced_cached == []


def test_sync_target_bars(temp_data_env):
    mock_tdx = MagicMock()
    mock_ak = MagicMock()
    sample_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "open": [10.0, 10.5],
            "high": [11.0, 11.2],
            "low": [9.8, 10.3],
            "close": [10.8, 11.0],
            "volume": [1000.0, 1200.0],
            "amount": [10800.0, 13200.0],
        }
    )
    mock_tdx.fetch_bars.return_value = sample_df
    mock_ak.fetch_bars.return_value = sample_df

    service = MarketSyncService(
        data_dir=temp_data_env,
        tdx_source=mock_tdx,
        ak_source=mock_ak,
    )
    start = datetime(2026, 1, 1, tzinfo=_SHANGHAI)
    end = datetime(2026, 1, 10, tzinfo=_SHANGHAI)

    # 1. Index
    item_index = service.sync_target_bars(
        SyncTarget("000300", AssetClass.INDEX, InstrumentType.INDEX, "沪深300"),
        start,
        end,
    )
    assert item_index.status == "updated"
    assert item_index.bars_count == 2

    # Verify persisted in DataStore
    store = DataStore(temp_data_env)
    loaded = store.load_bars(
        Symbol("000300"), BarFrequency.DAILY, instrument_type=InstrumentType.INDEX
    )
    assert loaded is not None
    assert len(loaded) == 2

    # 2. Fund (via AKShare)
    item_fund = service.sync_target_bars(
        SyncTarget("018125", AssetClass.FUND, InstrumentType.OPEN_END_FUND, "测试基金"),
        start,
        end,
    )
    assert item_fund.status == "updated"
    assert item_fund.bars_count == 2
    mock_ak.fetch_bars.assert_called_once()


def test_sync_target_bars_stock_merges_safely(temp_data_env):
    store = DataStore(temp_data_env)
    sym = Symbol("600519")

    # Initial historical bar in storage
    initial_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-05"]),
            "open": [100.0],
            "high": [105.0],
            "low": [99.0],
            "close": [104.0],
            "volume": [500.0],
            "amount": [52000.0],
        }
    )
    store.save_bars(
        sym, BarFrequency.DAILY, initial_df, instrument_type=InstrumentType.STOCK
    )

    # Remote returns 2 bars, including the first bar with slight remote difference
    mock_tdx = MagicMock()
    mock_tdx.fetch_bars.return_value = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "open": [99.9, 104.0],  # Remote slight drift on 01-05
            "high": [105.0, 108.0],
            "low": [99.0, 103.0],
            "close": [104.0, 107.0],
            "volume": [500.0, 600.0],
            "amount": [52000.0, 64200.0],
        }
    )

    service = MarketSyncService(data_dir=temp_data_env, tdx_source=mock_tdx)
    start = datetime(2026, 1, 1, tzinfo=_SHANGHAI)
    end = datetime(2026, 1, 10, tzinfo=_SHANGHAI)

    item = service.sync_target_bars(
        SyncTarget("600519", AssetClass.STOCK, InstrumentType.STOCK, "贵州茅台"),
        start,
        end,
    )
    assert item.status == "updated"
    assert item.bars_count == 2

    # The preserved bar for 2026-01-05 must keep exact 100.0 open, not 99.9!
    loaded = store.load_bars(
        sym, BarFrequency.DAILY, instrument_type=InstrumentType.STOCK
    )
    assert loaded is not None
    assert len(loaded) == 2
    row0 = loaded.iloc[0]
    assert row0["open"] == 100.0


def test_sync_latest_quotes(temp_data_env):
    mock_tdx = MagicMock()
    mock_tdx.fetch_latest.return_value = {
        "price": 1800.5,
        "previous_close": 1790.0,
        "change": 10.5,
        "change_percent": 0.005866,
        "volume": 20000.0,
        "turnover": 36000000.0,
        "timestamp": "2026-10-12T15:00:00",
        "provider_name": "tdx",
        "quote_source": "tdx_realtime",
    }
    mock_ak = MagicMock()

    service = MarketSyncService(
        data_dir=temp_data_env,
        tdx_source=mock_tdx,
        ak_source=mock_ak,
    )
    targets = [SyncTarget("600519", AssetClass.STOCK, InstrumentType.STOCK, "贵州茅台")]
    updated = service.sync_latest_quotes(targets)
    assert updated == 1

    # Verify quote and daily close snapshot using AppDatabase facade
    from server.db import AppDatabase

    db = AppDatabase(temp_data_env / "app.db")
    quote = db.get_latest_quote_sync("600519")
    assert quote is not None
    assert quote["price"] == 1800.5

    snapshot = db.get_latest_daily_close_before_sync(
        "600519", "2099-01-01", instrument_type="stock"
    )
    assert snapshot is not None
    assert snapshot["close_price"] == 1800.5


def test_sync_full_summary(temp_data_env):
    mock_tdx = MagicMock()
    mock_tdx.fetch_bars.return_value = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-05"]),
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000.0],
            "amount": [10200.0],
        }
    )
    mock_tdx.fetch_latest.return_value = {
        "price": 10.2,
        "timestamp": "2026-01-05T15:00:00",
    }
    mock_ak = MagicMock()
    mock_ak.fetch_bars.return_value = pd.DataFrame()
    mock_ak.fetch_latest.return_value = None

    service = MarketSyncService(
        data_dir=temp_data_env,
        tdx_source=mock_tdx,
        ak_source=mock_ak,
    )

    summary = service.sync(
        MarketSyncRequest(
            universe="indices",
            start_date="2026-01-01",
            end_date="2026-01-10",
            skip_calendar=True,
        )
    )
    assert summary.status == "success"
    assert summary.total_targets == len(DEFAULT_BENCHMARK_INDICES)
    assert summary.successful_targets == len(DEFAULT_BENCHMARK_INDICES)
    assert summary.duration_seconds >= 0.0
    assert service.get_last_summary() is summary


def test_http_sync_endpoints(temp_data_env):
    dependencies = RefreshEndpointDependencies(
        asset_class_map={},
        create_manual_quote_fetch_run=lambda *args, **kwargs: None,
        default_refresh_symbols=lambda state: [],
        finish_manual_quote_fetch_run=lambda *args, **kwargs: None,
        merged_watchlist_assets=lambda state: [],
        normalize_refresh_symbols=lambda syms: syms or [],
        publish_committed_runtime_quotes=lambda *args, **kwargs: None,
        quote_fetch_run_asset_type=lambda *args, **kwargs: None,
        quote_fetch_run_metadata=lambda *args, **kwargs: {},
        refresh_one_quote=lambda *args, **kwargs: None,
        with_default_market_indices=lambda assets: assets,
        asyncio_provider=lambda: __import__("asyncio"),
        datetime_provider=lambda: datetime,
        uuid_provider=lambda: __import__("uuid"),
        is_cn_trading_session=lambda: False,
    )

    app = FastAPI()
    router = create_router(dependencies)
    app.include_router(router)

    state_obj = MagicMock()
    state_obj.data_dir = temp_data_env
    state_obj.db = None
    state_obj.config = None

    with patch("server.dependencies.get_app_state", return_value=state_obj):
        client = TestClient(app)

        # GET status when empty
        resp_status = client.get("/api/market/sync/status")
        assert resp_status.status_code == 200

        # POST sync
        with patch.object(MarketSyncService, "sync") as mock_sync:
            from server.services.market_sync import MarketSyncSummary

            mock_sync.return_value = MarketSyncSummary(
                status="success",
                started_at="2026-10-12T15:00:00",
                completed_at="2026-10-12T15:00:05",
                duration_seconds=5.0,
                total_targets=10,
                successful_targets=10,
                failed_targets=0,
                quotes_updated=10,
            )

            post_resp = client.post(
                "/api/market/sync",
                json={"universe": "indices", "start": "2026-01-01"},
            )
            assert post_resp.status_code == 200
            data = post_resp.json()
            assert data["status"] == "success"
            assert data["total_targets"] == 10


def _daily_closes(db):
    with sqlite3.connect(db.path) as connection:
        return connection.execute(
            "SELECT symbol, instrument_type, trade_date, close_price, source "
            "FROM daily_close_snapshots_v2 ORDER BY symbol, instrument_type"
        ).fetchall()


@pytest.fixture
def sync_quote_clock(monkeypatch):
    current = datetime(2026, 10, 13, 16, 30, tzinfo=_SHANGHAI)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return (
                current.astimezone(tz)
                if tz is not None
                else current.replace(tzinfo=None)
            )

    monkeypatch.setattr("server.services.market_sync.datetime", FixedDateTime)
    return current


@pytest.mark.parametrize(
    ("symbol", "left_type", "left_class", "right_type", "right_class"),
    [
        (
            "510300",
            InstrumentType.ETF,
            AssetClass.FUND,
            InstrumentType.OPEN_END_FUND,
            AssetClass.FUND,
        ),
        (
            "000001",
            InstrumentType.STOCK,
            AssetClass.STOCK,
            InstrumentType.INDEX,
            AssetClass.INDEX,
        ),
    ],
)
def test_latest_quote_sync_preserves_both_typed_daily_closes(
    temp_data_env,
    sync_quote_clock,
    symbol,
    left_type,
    left_class,
    right_type,
    right_class,
):
    db = AppDatabase(temp_data_env / "app.db")
    for kind, price in ((left_type, 2.5), (right_type, 1.75)):
        db.save_daily_close_snapshot_sync(
            symbol=symbol,
            asset_class=kind.value,
            trade_date="2026-10-13",
            close_price=price,
            source="synthetic_prior_close",
        )
    tdx = MagicMock()
    akshare = MagicMock()
    service = MarketSyncService(
        data_dir=temp_data_env, db=db, tdx_source=tdx, ak_source=akshare
    )
    targets = [
        SyncTarget(symbol, left_class, left_type, "synthetic left"),
        SyncTarget(symbol, right_class, right_type, "synthetic right"),
    ]
    expected_prices = {left_type.value: 2.5, right_type.value: 1.75}
    for target, new_price in zip(targets, (3.25, 1.8), strict=True):
        provider = (
            akshare if target.instrument_type is InstrumentType.OPEN_END_FUND else tdx
        )
        provider.fetch_latest.return_value = {
            "price": new_price,
            "timestamp": "2026-10-13T15:00:00+08:00",
            "provider_name": "synthetic_provider",
            "quote_source": (
                "eastmoney_fund_page"
                if target.instrument_type is InstrumentType.OPEN_END_FUND
                else "synthetic_published_close"
            ),
            "provider_status": "live",
            "quote_status": "live",
            "nav_date": (
                "2026-10-13"
                if target.instrument_type is InstrumentType.OPEN_END_FUND
                else None
            ),
        }
        assert service.sync_latest_quotes([target]) == 1
        provider.fetch_latest.assert_called_with(
            Symbol(symbol), asset_class=target.asset_class
        )
        expected_prices[target.instrument_type.value] = new_price
        assert {
            kind: price for _, kind, _, price, _ in _daily_closes(db)
        } == expected_prices
        assert (
            db.get_latest_quote_sync(symbol, target.instrument_type.value)["price"]
            == new_price
        )

    before_closes = _daily_closes(db)
    before_quotes = db.list_latest_quotes_sync()
    tdx.fetch_latest.return_value = None
    akshare.fetch_latest.return_value = None
    assert service.sync_latest_quotes(targets) == 0
    assert _daily_closes(db) == before_closes
    assert db.list_latest_quotes_sync() == before_quotes


def test_http_etf_sync_does_not_overwrite_same_code_fund_close(
    temp_data_env, sync_quote_clock, monkeypatch
):
    from server.routes import market

    db = AppDatabase(temp_data_env / "app.db")
    for kind, price in (("etf", 2.5), ("open_end_fund", 1.75)):
        db.save_daily_close_snapshot_sync(
            symbol="510300",
            asset_class=kind,
            trade_date="2026-10-13",
            close_price=price,
            source="synthetic_prior_close",
        )
    tdx = MagicMock()
    tdx.fetch_bars.return_value = pd.DataFrame()
    tdx.fetch_latest.side_effect = lambda symbol, asset_class: (
        {
            "price": 3.25,
            "timestamp": "2026-10-13T15:00:00+08:00",
            "provider_name": "synthetic_tdx",
            "quote_source": "synthetic_exchange_close",
        }
        if str(symbol) == "510300" and asset_class is AssetClass.FUND
        else None
    )
    akshare = MagicMock()
    service = MarketSyncService(
        data_dir=temp_data_env, db=db, tdx_source=tdx, ak_source=akshare
    )
    monkeypatch.setattr("server.services.market_sync._GLOBAL_SERVICE", service)
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(data_dir=temp_data_env, db=db, config=None),
    )
    app = FastAPI()
    app.include_router(market.create_router())
    with TestClient(app) as client:
        response = client.post(
            "/api/market/sync",
            json={
                "universe": "etfs",
                "start": "2026-10-13",
                "end": "2026-10-13",
                "skip_calendar": True,
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["quotes_updated"] == 1
    assert {kind: price for _, kind, _, price, _ in _daily_closes(db)} == {
        "etf": 3.25,
        "open_end_fund": 1.75,
    }
    assert db.get_latest_quote_sync("510300", "etf")["price"] == 3.25
    assert db.get_latest_quote_sync("510300", "open_end_fund") is None
    akshare.fetch_latest.assert_not_called()


@pytest.mark.parametrize("via_http", [False, True], ids=["service", "http"])
@pytest.mark.parametrize(
    ("kind", "evidence", "expected_close_date"),
    [
        pytest.param(
            InstrumentType.STOCK,
            {"timestamp": "2026-10-12T15:00:00"},
            "2026-10-12",
            id="prior-session-close",
        ),
        pytest.param(
            InstrumentType.INDEX,
            {"timestamp": "2026-10-12T07:00:00Z"},
            "2026-10-12",
            id="utc-at-shanghai-close",
        ),
        pytest.param(
            InstrumentType.ETF,
            {"timestamp": "2026-10-12T16:30:00Z"},
            None,
            id="utc-next-shanghai-day-before-open",
        ),
        pytest.param(
            InstrumentType.ETF,
            {"timestamp": "2026-10-13T14:59:59+08:00"},
            None,
            id="intraday",
        ),
        pytest.param(InstrumentType.ETF, {}, None, id="missing-timestamp"),
        pytest.param(
            InstrumentType.ETF,
            {"timestamp": "invalid"},
            None,
            id="invalid-timestamp",
        ),
        pytest.param(
            InstrumentType.ETF,
            {"timestamp": "2026-10-14T15:00:00+08:00"},
            None,
            id="future-timestamp",
        ),
        pytest.param(
            InstrumentType.STOCK,
            {"timestamp": "2026-10-13T15:00:00+08:00", "quote_status": "stale"},
            None,
            id="explicitly-stale",
        ),
        pytest.param(
            InstrumentType.OPEN_END_FUND,
            {
                "timestamp": "2026-10-13T09:30:00+08:00",
                "nav_date": "2026-10-12",
                "quote_source": "eastmoney_fund_page",
            },
            "2026-10-12",
            id="confirmed-nav-economic-date",
        ),
        pytest.param(
            InstrumentType.OPEN_END_FUND,
            {
                "timestamp": "2026-10-13T15:00:00+08:00",
                "quote_source": "eastmoney_fund_page",
            },
            "2026-10-13",
            id="published-page-date-from-source-timestamp",
        ),
        pytest.param(
            InstrumentType.OPEN_END_FUND,
            {
                "quote_timestamp": "2026-10-12T16:30:00Z",
                "quote_source": "eastmoney_fund_page",
            },
            "2026-10-13",
            id="published-nav-quote-timestamp-only",
        ),
        *[
            pytest.param(
                InstrumentType.OPEN_END_FUND,
                {
                    "timestamp": "2026-10-13T15:00:00+08:00",
                    "nav_date": "2026-10-12",
                    "quote_source": "eastmoney_fund_page",
                    **failure,
                },
                None,
                id=name,
            )
            for name, failure in [
                ("published-nav-provider-failed", {"provider_status": "failed"}),
                ("published-nav-stale-status", {"quote_status": "stale"}),
                ("published-nav-stale-reason", {"stale_reason": "cached"}),
                ("published-nav-future-economic-date", {"nav_date": "2026-10-14"}),
                ("unconfirmed-source", {"quote_source": "unknown_source"}),
            ]
        ],
        pytest.param(
            InstrumentType.OPEN_END_FUND,
            {
                "timestamp": "2026-10-13T15:00:00+08:00",
                "nav_date": "not-a-date",
                "quote_source": "eastmoney_fund_page",
            },
            None,
            id="invalid-nav-date",
        ),
        pytest.param(
            InstrumentType.OPEN_END_FUND,
            {
                "timestamp": "2026-10-13T15:00:00+08:00",
                "nav_date": "2026-10-12",
                "quote_source": "sina_fund_estimate",
            },
            None,
            id="estimate-with-prior-nav-date",
        ),
        pytest.param(
            InstrumentType.OPEN_END_FUND,
            {
                "nav_date": "2026-10-12",
                "quote_source": "eastmoney_fund_page",
            },
            None,
            id="confirmed-nav-missing-observation-time",
        ),
    ],
)
def test_quote_sync_daily_close_requires_source_session_evidence(
    temp_data_env,
    sync_quote_clock,
    monkeypatch,
    via_http,
    kind,
    evidence,
    expected_close_date,
):
    from server.routes import market

    db = AppDatabase(temp_data_env / "app.db")
    db.save_daily_close_snapshot_sync(
        symbol="510300",
        asset_class="open_end_fund" if kind is InstrumentType.ETF else "etf",
        trade_date="2026-10-13",
        close_price=1.75,
        source="synthetic_other_identity",
    )
    prior_closes = _daily_closes(db)
    snapshot = {
        "price": 3.25,
        "provider_name": "synthetic_provider",
        "provider_status": "live",
        "quote_source": "synthetic_exchange_quote",
        "quote_status": "live",
        **evidence,
    }
    provider = MagicMock()
    provider.fetch_latest.return_value = snapshot
    provider.fetch_bars.return_value = pd.DataFrame()
    service = MarketSyncService(
        data_dir=temp_data_env, db=db, tdx_source=provider, ak_source=provider
    )
    asset_class = (
        AssetClass.FUND
        if kind in {InstrumentType.ETF, InstrumentType.OPEN_END_FUND}
        else AssetClass(kind.value)
    )
    target = SyncTarget("510300", asset_class, kind, "synthetic instrument")
    if via_http:
        monkeypatch.setattr("server.services.market_sync._GLOBAL_SERVICE", service)
        monkeypatch.setattr(service, "resolve_targets", lambda request: [target])
        monkeypatch.setattr(
            "server.dependencies.get_app_state",
            lambda: SimpleNamespace(data_dir=temp_data_env, db=db, config=None),
        )
        app = FastAPI()
        app.include_router(market.create_router())
        with TestClient(app) as client:
            response = client.post(
                "/api/market/sync",
                json={
                    "start": "2026-10-12",
                    "end": "2026-10-13",
                    "skip_calendar": True,
                },
            )
        assert response.status_code == 200, response.text
        assert response.json()["quotes_updated"] == 1
    else:
        assert service.sync_latest_quotes([target]) == 1
    provider.fetch_latest.assert_called_once_with(
        Symbol("510300"), asset_class=asset_class
    )
    quote = db.get_latest_quote_sync("510300", kind.value)
    assert quote is not None and quote["price"] == 3.25
    if not evidence.get("timestamp") and not evidence.get("quote_timestamp"):
        # The existing latest-quote capture fallback does not grant close authority.
        assert (
            quote["quote_timestamp"]
            == sync_quote_clock.astimezone(ZoneInfo("UTC")).isoformat()
        )
    closes = _daily_closes(db)
    if expected_close_date is None:
        assert closes == prior_closes
    else:
        new_rows = [row for row in closes if row[1] == kind.value]
        assert len(new_rows) == 1
        assert new_rows[0][2:] == (
            expected_close_date,
            3.25,
            "synthetic_provider",
        )
        assert all(row in closes for row in prior_closes)


def test_real_akshare_page_nav_writes_dated_close_and_estimate_cannot_replace_it(
    temp_data_env, sync_quote_clock, monkeypatch
):
    from data.providers.akshare import AKShareSource

    source = AKShareSource()
    monkeypatch.setattr(
        source, "_fetch_open_end_fund_latest_from_estimate", lambda _code: None
    )
    trend = [
        {
            "x": int(datetime(2026, 10, 9, tzinfo=_SHANGHAI).timestamp() * 1000),
            "y": 1.2,
        },
        {
            "x": int(datetime(2026, 10, 12, tzinfo=_SHANGHAI).timestamp() * 1000),
            "y": 1.25,
        },
    ]
    monkeypatch.setattr(
        "data.providers.akshare.eastmoney_upstream.fetch_eastmoney_fund_page",
        lambda **_kwargs: (
            'var fS_name = "Synthetic Fund";\nvar Data_netWorthTrend = '
            + json.dumps(trend)
            + ";"
        ),
    )
    raw = source.fetch_latest(Symbol("018125"), asset_class=AssetClass.FUND)
    assert raw["quote_source"] == "eastmoney_fund_page"
    assert not {"nav_date", "provider_status", "quote_status"}.intersection(raw)
    db = AppDatabase(temp_data_env / "app.db")
    service = MarketSyncService(data_dir=temp_data_env, db=db, ak_source=source)
    target = SyncTarget(
        "018125", AssetClass.FUND, InstrumentType.OPEN_END_FUND, "Synthetic Fund"
    )
    for _ in range(2):
        assert service.sync_latest_quotes([target]) == 1
        assert _daily_closes(db) == [
            ("018125", "open_end_fund", "2026-10-12", 1.25, "akshare")
        ]
    assert db.get_latest_quote_sync("018125", "open_end_fund")["price"] == 1.25
    closes = _daily_closes(db)
    monkeypatch.setattr(
        source,
        "_fetch_open_end_fund_latest_from_estimate",
        lambda _code: {
            "price": 9.0,
            "timestamp": "2026-10-13T15:00:00+08:00",
            "quote_source": "sina_fund_estimate",
            "source": "sina",
        },
    )
    assert service.sync_latest_quotes([target]) == 1
    assert db.get_latest_quote_sync("018125", "open_end_fund")["price"] == 9.0
    assert _daily_closes(db) == closes
