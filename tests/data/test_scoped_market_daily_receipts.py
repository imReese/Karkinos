from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.types import AssetClass, Symbol
from data.store import DataStore
from server.db import AppDatabase
from server.services.market.calendar import (
    resolve_latest_verified_closed_trading_date,
)
from server.services.market.post_close import publish_post_close_stock_quotes

_TRADE_DATE = "2026-05-29"
_CAPTURED_AT = datetime(2026, 5, 29, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
_SOURCE_FINGERPRINT = "c" * 64
_OFFICIAL_FINGERPRINT = "d" * 64


def _create_bars(symbols_with_prices: list[tuple[str, float]]) -> pd.DataFrame:
    rows = []
    for sym, px in symbols_with_prices:
        rows.append(
            {
                "symbol": sym,
                "timestamp": f"{_TRADE_DATE}T00:00:00",
                "open": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "close": px,
                "volume": 1000.0,
                "amount": px * 1000.0,
            }
        )
    return pd.DataFrame(rows)


def _setup_calendar_database(db_path: Path) -> AppDatabase:
    database = AppDatabase(db_path)
    database.init_sync()
    current = date(2026, 1, 1)
    end = date(2027, 1, 1)
    days = []
    while current < end:
        days.append(
            {
                "date": current.isoformat(),
                "is_trading_day": current.weekday() < 5,
            }
        )
        current += pd.Timedelta(days=1)
    trading_count = sum(1 for d in days if d["is_trading_day"])
    database.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "unit_fixture",
            "status": "available",
            "trading_day_count": trading_count,
            "closed_day_count": len(days) - trading_count,
            "source_fingerprint": _SOURCE_FINGERPRINT,
            "days": days,
            "limitations": [],
        }
    )
    database.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=_SOURCE_FINGERPRINT,
        verification_status="verified",
        official_source_url="https://example.test/sse-calendar",
        official_source_fingerprint=_OFFICIAL_FINGERPRINT,
        verified_by="unit-test",
    )
    return database


def test_scoped_receipt_a_to_ab_extension_keeps_old_receipt_replayable(
    tmp_path: Path,
) -> None:
    store = DataStore(tmp_path / "data")

    # 1. First recover stock A (600001)
    bars_a = _create_bars([("600001", 10.0)])
    receipt_a = store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=bars_a,
    )
    assert receipt_a["scope_type"] == "scoped"
    assert receipt_a["symbols"] == ["600001"]

    # Full market receipts table must NOT have this scoped receipt
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date=_TRADE_DATE,
            provider_name="source1",
        )
        is None
    )

    # Scoped receipt lookup for [600001] succeeds
    fetched_a = store.get_market_daily_scoped_receipt(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        symbols=["600001"],
    )
    assert fetched_a == receipt_a

    # 2. Scope extended to A + B (600001, 600002)
    bars_ab = _create_bars([("600001", 10.0), ("600002", 20.0)])
    receipt_ab = store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=bars_ab,
    )
    assert receipt_ab["scope_type"] == "scoped"
    assert receipt_ab["symbols"] == ["600001", "600002"]
    assert receipt_ab["scope_fingerprint"] != receipt_a["scope_fingerprint"]

    # 3. Old receipt for A must still exist, be distinct, and be verifiable
    old_a_replay = store.get_market_daily_scoped_receipt(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        scope_fingerprint=str(receipt_a["scope_fingerprint"]),
        verify=True,
    )
    assert old_a_replay == receipt_a

    # Lookup by symbols=['600001', '600002'] returns receipt_ab
    covered = store.get_market_daily_ingestion_receipt(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        symbols=["600001", "600002"],
        verify=True,
    )
    assert covered == receipt_ab

    # Both receipts exist in scoped receipts list
    receipts_list = store.list_market_daily_scoped_receipts(
        trade_date=_TRADE_DATE,
        provider_name="source1",
    )
    assert len(receipts_list) == 2


def test_scoped_receipt_repeated_recovery_is_idempotent(tmp_path: Path) -> None:
    store = DataStore(tmp_path / "data")
    bars_a = _create_bars([("600001", 10.0)])

    first = store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=bars_a,
    )
    second = store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=bars_a,
    )
    assert first == second
    assert (
        len(
            store.list_market_daily_scoped_receipts(
                trade_date=_TRADE_DATE, provider_name="source1"
            )
        )
        == 1
    )


def test_scoped_receipt_coexists_with_full_market_batch(tmp_path: Path) -> None:
    store = DataStore(tmp_path / "data")

    # Scoped recovery first
    bars_scoped = _create_bars([("600001", 10.0)])
    scoped = store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=bars_scoped,
    )

    # Later full-market batch arrives with 600001 (same price) and 600002, 600003
    bars_full = _create_bars([("600001", 10.0), ("600002", 20.0), ("600003", 30.0)])
    full = store.ingest_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=bars_full,
    )
    assert full["schema_version"] == "karkinos.market_daily_ingestion_receipt.v3"

    # Full batch lookup without symbols returns full batch
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date=_TRADE_DATE,
            provider_name="source1",
        )
        == full
    )

    # Scoped receipt remains accessible and uncorrupted
    assert (
        store.get_market_daily_scoped_receipt(
            trade_date=_TRADE_DATE,
            provider_name="source1",
            symbols=["600001"],
        )
        == scoped
    )


def test_different_provider_data_conflict_on_frozen_bar(tmp_path: Path) -> None:
    store = DataStore(tmp_path / "data")

    # Provider 1 freezes stock 600001 close at 10.0
    store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="provider_alpha",
        bars=_create_bars([("600001", 10.0)]),
    )

    # Provider 2 attempts to ingest stock 600001 with close at 15.0 on the same date
    with pytest.raises(ValueError, match="frozen_market_bar_conflict:600001"):
        store.ingest_scoped_market_daily_batch(
            trade_date=_TRADE_DATE,
            provider_name="provider_beta",
            bars=_create_bars([("600001", 15.0)]),
        )


def test_post_close_stock_quotes_publication_with_scoped_receipt(
    tmp_path: Path,
) -> None:
    db = _setup_calendar_database(tmp_path / "app.db")
    store = DataStore(tmp_path / "data")
    resolved = resolve_latest_verified_closed_trading_date(db, _CAPTURED_AT)
    assert resolved is not None
    refs = resolved.calendar_evidence_refs

    # Watchlist with 600001 and 600002
    watchlist = [
        (Symbol("600001"), AssetClass.STOCK),
        (Symbol("600002"), AssetClass.STOCK),
    ]

    # Ingest scoped batch for only 600001
    store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=_create_bars([("600001", 10.0)]),
    )

    # Publication must fail because 600002 is missing from receipt scope
    result1 = publish_post_close_stock_quotes(
        db,
        store,
        watchlist,
        provider_name="source1",
        trade_date=date.fromisoformat(_TRADE_DATE),
        calendar_evidence_refs=refs,
        captured_at=_CAPTURED_AT,
    )
    assert result1.published is False
    assert result1.error_message == "market_daily_ingestion_receipt_scope_incomplete"
    assert result1.missing_symbols == ("600002",)

    # Scope extended to 600001 and 600002
    store.ingest_scoped_market_daily_batch(
        trade_date=_TRADE_DATE,
        provider_name="source1",
        bars=_create_bars([("600001", 10.0), ("600002", 20.0)]),
    )

    # Publication now succeeds covering both symbols
    result2 = publish_post_close_stock_quotes(
        db,
        store,
        watchlist,
        provider_name="source1",
        trade_date=date.fromisoformat(_TRADE_DATE),
        calendar_evidence_refs=refs,
        captured_at=_CAPTURED_AT,
    )
    assert result2.published is True
    assert result2.error_message is None
    assert result2.symbols == ("600001", "600002")
