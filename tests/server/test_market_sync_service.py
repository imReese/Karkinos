"""Tests for MarketSyncService and sync HTTP endpoints."""

from __future__ import annotations

from datetime import datetime
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
