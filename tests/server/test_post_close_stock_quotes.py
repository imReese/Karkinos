from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import AssetClass, Symbol
from data.market_daily_store import is_supported_stock_receipt_identity
from data.store import DataStore
from server.db import AppDatabase
from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
)
from server.services.post_close_stock_quotes import publish_post_close_stock_quotes

_CAPTURED_AT = datetime(2026, 5, 29, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
_SOURCE_FINGERPRINT = "c" * 64
_ORIGINAL_OFFICIAL_FINGERPRINT = "d" * 64
_DRIFTED_OFFICIAL_FINGERPRINT = "e" * 64
_TRADE_DATE = date(2026, 5, 29)
_WATCHLIST = [(Symbol("600001"), AssetClass.STOCK)]


def test_stock_daily_receipt_identity_accepts_only_legacy_or_typed_stock() -> None:
    assert is_supported_stock_receipt_identity(
        {
            "schema_version": "karkinos.market_daily_ingestion_receipt.v1",
            "storage_authority": "sqlite_market_bars",
        }
    )
    assert is_supported_stock_receipt_identity(
        {
            "schema_version": "karkinos.market_daily_ingestion_receipt.v2",
            "storage_authority": "sqlite_market_bars_v2:stock",
        }
    )
    assert not is_supported_stock_receipt_identity(
        {
            "schema_version": "karkinos.market_daily_ingestion_receipt.v2",
            "storage_authority": "sqlite_market_bars_v2:etf",
        }
    )
    assert not is_supported_stock_receipt_identity(
        {
            "schema_version": "karkinos.market_daily_ingestion_receipt.v2",
            "storage_authority": "sqlite_market_bars",
        }
    )


def _database(tmp_path) -> AppDatabase:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    return database


def _install_verified_calendar(database: AppDatabase) -> tuple[str, ...]:
    current = date(2026, 1, 1)
    end = date(2027, 1, 1)
    days: list[dict[str, object]] = []
    while current < end:
        days.append(
            {
                "date": current.isoformat(),
                "is_trading_day": current.weekday() < 5,
            }
        )
        current += timedelta(days=1)
    trading_day_count = sum(1 for day in days if day["is_trading_day"])
    database.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "unit_fixture",
            "status": "available",
            "trading_day_count": trading_day_count,
            "closed_day_count": len(days) - trading_day_count,
            "source_fingerprint": _SOURCE_FINGERPRINT,
            "days": days,
            "limitations": [],
        }
    )
    _verify_calendar(database, _ORIGINAL_OFFICIAL_FINGERPRINT)
    return _calendar_evidence_refs(database)


def _verify_calendar(database: AppDatabase, official_fingerprint: str) -> None:
    database.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=_SOURCE_FINGERPRINT,
        verification_status="verified",
        official_source_url="https://example.test/sse-calendar",
        official_source_fingerprint=official_fingerprint,
        verified_by="unit-test",
    )


def _calendar_evidence_refs(database: AppDatabase) -> tuple[str, ...]:
    resolved = resolve_latest_verified_closed_trading_date(database, _CAPTURED_AT)
    assert resolved is not None
    assert resolved.trade_date == _TRADE_DATE.isoformat()
    return resolved.calendar_evidence_refs


def _ingest_receipt(store: DataStore, *, provider_name: str = "akshare") -> None:
    store.ingest_market_daily_batch(
        trade_date=_TRADE_DATE.isoformat(),
        provider_name=provider_name,
        bars=pd.DataFrame(
            [
                {
                    "symbol": "600001",
                    "timestamp": f"{_TRADE_DATE.isoformat()}T00:00:00",
                    "open": 11.0,
                    "high": 11.0,
                    "low": 11.0,
                    "close": 11.0,
                    "volume": 1000.0,
                    "amount": 11000.0,
                }
            ]
        ),
    )


def _publish(
    database: AppDatabase,
    store: Any,
    *,
    provider_name: str,
    calendar_evidence_refs: tuple[str, ...],
):
    return publish_post_close_stock_quotes(
        database,
        store,
        _WATCHLIST,
        provider_name=provider_name,
        trade_date=_TRADE_DATE,
        calendar_evidence_refs=calendar_evidence_refs,
        captured_at=_CAPTURED_AT,
    )


def test_calendar_evidence_drift_during_receipt_bar_receipt_window_creates_no_run(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    original_refs = _install_verified_calendar(database)
    store = DataStore(tmp_path / "market-data")
    _ingest_receipt(store)

    class CalendarDriftStore:
        def __init__(self) -> None:
            self.receipt_reads = 0

        def get_market_daily_ingestion_receipt(self, **kwargs):
            receipt = store.get_market_daily_ingestion_receipt(**kwargs)
            self.receipt_reads += 1
            if self.receipt_reads == 2:
                _verify_calendar(database, _DRIFTED_OFFICIAL_FINGERPRINT)
            return receipt

        def load_market_bar_windows(self, **kwargs):
            return store.load_market_bar_windows(**kwargs)

    drift_store = CalendarDriftStore()
    result = _publish(
        database,
        drift_store,
        provider_name="akshare",
        calendar_evidence_refs=original_refs,
    )

    assert result.published is False
    assert result.error_message == "verified_market_calendar_changed_during_read"
    assert drift_store.receipt_reads == 2
    assert database.list_quote_fetch_runs(trigger="post_close_market_bar") == []
    assert database.get_latest_quotes_sync() == []


def test_canonical_replay_rejects_successful_run_with_stale_calendar_identity(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    original_refs = _install_verified_calendar(database)
    store = DataStore(tmp_path / "market-data")
    _ingest_receipt(store)

    initial = _publish(
        database,
        store,
        provider_name="akshare",
        calendar_evidence_refs=original_refs,
    )
    assert initial.published is True
    assert initial.run_id is not None
    assert database.get_quote_fetch_run(initial.run_id)["status"] == "success"

    _verify_calendar(database, _DRIFTED_OFFICIAL_FINGERPRINT)
    current_refs = _calendar_evidence_refs(database)
    assert current_refs != original_refs

    replay = _publish(
        database,
        store,
        provider_name="akshare",
        calendar_evidence_refs=current_refs,
    )

    assert replay.published is False
    assert replay.error_message == "current_quote_receipt_identity_invalid"
    runs = database.list_quote_fetch_runs(trigger="post_close_market_bar")
    assert [run["run_id"] for run in runs] == [initial.run_id]


def test_same_timestamp_trusted_equivalent_requires_live_provider_status(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    calendar_refs = _install_verified_calendar(database)
    store = DataStore(tmp_path / "market-data")
    _ingest_receipt(store, provider_name="tushare")
    database.upsert_latest_quote_sync(
        symbol="600001",
        asset_type="stock",
        price=11.0,
        quote_timestamp="2026-05-29T15:00:00+08:00",
        quote_source="tushare_daily",
        provider_name="tushare",
        provider_status="cache",
        quote_status="confirmed",
    )

    result = _publish(
        database,
        store,
        provider_name="tushare",
        calendar_evidence_refs=calendar_refs,
    )

    assert result.published is False
    assert result.error_message == "current_quote_conflicts_with_verified_close"
    assert database.list_quote_fetch_runs(trigger="post_close_market_bar") == []
