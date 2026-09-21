from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.types import BarFrequency, InstrumentType
from data.store import DataStore
from server.db import AppDatabase
from server.services.market_universe_automation import (
    MarketUniverseAutomationService,
    verified_trading_dates,
)
from server.services.market_universe_truth import (
    normalize_a_share_members,
)


class _Source:
    def __init__(self) -> None:
        self.calls = 0
        self.daily_calls: list[str] = []

    def list_symbols(self):
        self.calls += 1
        return [f"{600000 + index:06d}" for index in range(1_000)]

    def list_symbol_metadata(self):
        self.calls += 1
        return [
            {
                "symbol": symbol,
                "display_name": f"示例股票{symbol}",
                "provider_symbol": f"{symbol}.SH",
                "provider_name": "unit_fixture",
                "source": "stock_master",
            }
            for symbol in [f"{600000 + index:06d}" for index in range(1_000)]
        ]

    def fetch_market_daily_bars(self, trade_date: str) -> pd.DataFrame:
        self.daily_calls.append(trade_date)
        symbols = self.list_symbols()
        self.calls -= 1
        return pd.DataFrame(
            {
                "symbol": symbols,
                "timestamp": [pd.Timestamp(trade_date)] * len(symbols),
                "open": [10.0] * len(symbols),
                "high": [10.1] * len(symbols),
                "low": [9.9] * len(symbols),
                "close": [10.0] * len(symbols),
                "volume": [1_000_000] * len(symbols),
                "amount": [10_000_000] * len(symbols),
            }
        )


def _verified_calendar(db: AppDatabase) -> None:
    trading_dates = pd.bdate_range(end="2026-08-21", periods=80)
    trading_date_values = {
        market_date.date().isoformat() for market_date in trading_dates
    }
    current = date(2026, 1, 1)
    calendar_days = []
    while current.year == 2026:
        market_date = current.isoformat()
        is_trading_day = market_date in trading_date_values
        calendar_days.append(
            {
                "date": market_date,
                "is_trading_day": is_trading_day,
                "day_type": "trading" if is_trading_day else "closed",
                "reason_code": (
                    "scheduled_trading_day" if is_trading_day else "scheduled_closed"
                ),
            }
        )
        current += timedelta(days=1)
    source_fingerprint = "c" * 64
    db.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": 2026,
            "provider": "unit_fixture",
            "status": "available",
            "trading_day_count": len(trading_date_values),
            "closed_day_count": len(calendar_days) - len(trading_date_values),
            "source_fingerprint": source_fingerprint,
            "days": calendar_days,
            "limitations": [],
        }
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=source_fingerprint,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="d" * 64,
        verified_by="unit-test",
    )


def test_market_universe_automation_ingests_once_and_never_changes_authority(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    sleeps = []
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="tushare",
            tushare_token="",
            start_date="2026-04-01",
            initial_cash=100_000,
        ),
        data_store=store,
        source=source,
        sleep_fn=sleeps.append,
    )
    now = datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = service.run_due(now=now)
    second = service.run_due(now=now)

    assert first["status"] == "completed"
    assert second["run_id"] == first["run_id"]
    assert source.calls == 1
    assert len(source.daily_calls) == 80
    assert sleeps == [2.0] * 80
    payload = json.loads(first["payload_json"])
    assert payload["trade_date"] == "2026-08-21"
    assert payload["market_universe_member_count"] == 1_000
    assert payload["persisted_bar_ready_count"] == 1_000
    assert payload["full_market_daily_receipt_count"] == 80
    assert payload["full_market_history_frozen"] is True
    assert payload["remote_bar_refresh_attempt_count"] == 80
    assert payload["provider_request_interval_seconds"] == 2.0
    assert payload["stock_master_metadata_fetched"] is True
    assert payload["stock_master_useful_name_count"] == 1_000
    assert payload["instrument_metadata_persisted_count"] == 1_000
    assert payload["changes_account_truth"] is False
    assert payload["changes_strategy_promotion"] is False
    assert payload["creates_order"] is False
    assert payload["changes_execution_authority"] is False
    assert payload["changes_capital_authority"] is False
    metadata = db.get_instrument_metadata_batch_sync(["600000", "600001"])
    assert [row["display_name"] for row in metadata] == [
        "示例股票600000",
        "示例股票600001",
    ]
    assert all(row["source"] == "market_universe_stock_master" for row in metadata)


def test_market_universe_automation_blocks_without_verified_calendar(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = _Source()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(data_source="unit_fixture", tushare_token=""),
        data_store=DataStore(tmp_path / "market"),
        source=source,
    )

    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert result["status"] == "blocked"
    assert source.calls == 0
    payload = json.loads(result["payload_json"])
    assert payload["blockers"] == ["verified_closed_trading_date_unavailable"]


def test_market_universe_does_not_freeze_snapshot_before_name_batch_persists(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()

    def reject_metadata_batch(items):
        raise RuntimeError("fixture metadata persistence rejected")

    db.upsert_instrument_metadata_batch_sync = reject_metadata_batch
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture",
            tushare_token="",
            start_date="2026-04-01",
        ),
        data_store=store,
        source=source,
    )

    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert result["status"] == "failed"
    assert source.calls == 1
    assert store.get_market_universe_snapshot(trade_date="2026-08-21") is None
    payload = json.loads(result["payload_json"])
    assert payload["error"]["message"] == "fixture metadata persistence rejected"


def test_market_universe_automation_resumes_without_refetching_frozen_dates(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    snapshot = store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        members=normalize_a_share_members(source.list_symbols()),
    )
    trading_dates = [
        market_date.date().isoformat()
        for market_date in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    for market_date in trading_dates[:10]:
        store.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name="unit_fixture",
            bars=source.fetch_market_daily_bars(market_date),
        )
    source.daily_calls.clear()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture",
            tushare_token="",
            start_date="2026-04-01",
            initial_cash=100_000,
        ),
        data_store=store,
        source=source,
    )

    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert result["status"] == "completed"
    assert source.daily_calls == trading_dates[10:]
    payload = json.loads(result["payload_json"])
    assert payload["persisted_receipt_skipped_count"] == 10
    assert payload["remote_bar_refresh_attempt_count"] == 70


def test_market_universe_routes_security_master_and_daily_bars_separately(
    monkeypatch,
    tmp_path,
) -> None:
    from data.source_policy import MarketDataUseCase
    from server.services import market_universe_automation

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    symbols = [f"{600000 + index:06d}" for index in range(1_000)]

    class MasterSource:
        def __init__(self) -> None:
            self.calls = 0

        def list_symbol_metadata(self):
            self.calls += 1
            return [
                {
                    "symbol": symbol,
                    "display_name": f"主数据{symbol}",
                    "provider_symbol": f"{symbol}.SH",
                }
                for symbol in symbols
            ]

    class DailySource:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch_market_daily_bars(self, trade_date: str) -> pd.DataFrame:
            self.calls.append(trade_date)
            return pd.DataFrame(
                {
                    "symbol": symbols,
                    "timestamp": [pd.Timestamp(trade_date)] * len(symbols),
                    "open": [10.0] * len(symbols),
                    "high": [10.1] * len(symbols),
                    "low": [9.9] * len(symbols),
                    "close": [10.0] * len(symbols),
                    "volume": [1_000_000] * len(symbols),
                    "amount": [10_000_000] * len(symbols),
                }
            )

    master = MasterSource()
    daily = DailySource()
    monkeypatch.setattr(
        market_universe_automation,
        "build_sources_for_config",
        lambda config: {"akshare": master, "tushare": daily},
    )

    def route_names(config, use_case):
        if use_case is MarketDataUseCase.SECURITY_MASTER:
            return ("akshare",)
        if use_case is MarketDataUseCase.DAILY_BARS:
            return ("tushare", "akshare")
        raise AssertionError(use_case)

    monkeypatch.setattr(
        market_universe_automation,
        "configured_legacy_provider_names",
        route_names,
    )

    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            market_data_source_policy="karkinos.market.source.cn_research.v1",
            tushare_token="fixture",
            start_date="2026-04-01",
        ),
        data_store=store,
        throttle_seconds=0,
    )
    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert result["status"] == "completed"
    assert master.calls == 1
    assert len(daily.calls) == 80

    snapshot = store.get_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="akshare",
    )
    assert snapshot is not None
    assert snapshot["provider_name"] == "akshare"
    assert (
        store.get_market_universe_snapshot(
            trade_date="2026-08-21",
            provider_name="tushare",
        )
        is None
    )

    receipts = store.list_market_daily_ingestion_receipts(
        start_date=daily.calls[0],
        end_date=daily.calls[-1],
        provider_name="tushare",
    )
    assert len(receipts) == 80

    payload = json.loads(result["payload_json"])
    assert payload["schema_version"] == "karkinos.market_universe_automation.v3"
    assert payload["security_master_provider"] == "akshare"
    assert payload["daily_bar_provider"] == "tushare"
    assert payload["market_universe_snapshot_id"] == snapshot["snapshot_id"]


def test_research_calendar_rejects_missing_year_and_broken_verification(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    with pytest.raises(ValueError, match="research_calendar_incomplete:2025"):
        verified_trading_dates(db, start_date="2025-01-02", end_date="2026-08-21")
    assert (
        len(verified_trading_dates(db, start_date="2026-01-01", end_date="2026-08-21"))
        == 80
    )
    read_calendar = db.get_market_calendar_snapshot_sync

    def stale_verification(**kwargs):
        row = read_calendar(**kwargs)
        return {**row, "verification_source_fingerprint": "a" * 64}

    monkeypatch.setattr(db, "get_market_calendar_snapshot_sync", stale_verification)
    with pytest.raises(
        ValueError, match="market_calendar_verification_binding_invalid"
    ):
        verified_trading_dates(db, start_date="2026-01-01", end_date="2026-08-21")


def test_per_symbol_ingestion_never_relabels_existing_cache_as_provider_evidence(
    tmp_path,
):
    from server.services.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    calls = []

    class Source:
        def list_symbols(self):
            return [f"{600000 + i:06d}" for i in range(41)]

        def fetch_bars(self, symbol, **kwargs):
            calls.append(symbol)
            frame = pd.DataFrame(
                {
                    "timestamp": pd.bdate_range(end="2026-08-21", periods=80),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.0,
                    "volume": 10000.0,
                    "amount": 100000.0,
                }
            )
            frame.attrs.update(
                volume_unit="shares", amount_unit="CNY", adjustment_mode="none"
            )
            # One newly listed member has no bars in this historical window.
            return frame.iloc[:0] if symbol == "600040" else frame

    # A complete-looking cache is not a source-bound observation.
    source = Source()
    stale = source.fetch_bars("600000")
    stale["volume"] = 100
    store.save_bars("600000", BarFrequency.DAILY, stale, instrument_type="stock")
    calls.clear()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(data_source="fixture", start_date="2026-01-01"),
        data_store=store,
        source=source,
        policy=MarketUniversePolicy(minimum_master_member_count=40),
        throttle_seconds=0,
    )
    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert result["status"] == "completed"
    assert len(calls) == 41
    assert store.load_bars("600000", instrument_type="stock")["volume"].eq(10000).all()
    service.run_due(now=datetime(2026, 8, 23, 11, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert len(calls) == 41
