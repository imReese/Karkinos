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
from server.services.market.market_universe_automation import (
    MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION,
    MarketUniverseAutomationService,
    validate_market_universe_automation_payload,
    verified_trading_dates,
)
from server.services.market.market_universe_truth import (
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


def test_failed_run_records_source_bound_master_and_does_not_bypass_backoff(
    tmp_path, monkeypatch
):
    from server.services.market.market_universe_truth import MarketUniversePolicy
    from tests.data.providers.test_official_stock_master import _bound
    from tests.server.test_verified_interval_dataset import DAYS, NOW

    _, _, master = _bound(tmp_path)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market = DataStore(tmp_path)
    monkeypatch.setattr(
        "server.services.market.market_universe_automation.latest_verified_closed_trading_date",
        lambda *_a, **_kw: DAYS[-1].isoformat(),
    )
    monkeypatch.setattr(
        "server.services.market.market_universe_automation.verified_trading_dates",
        lambda *_a, **_kw: [day.isoformat() for day in DAYS],
    )
    attempts = []

    def rejected(**kwargs):
        attempts.append(kwargs)
        raise ValueError("stock_master_fixture_invalid")

    monkeypatch.setattr(market, "get_market_daily_ingestion_receipt", rejected)
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="akshare", tushare_token="", start_date=DAYS[0].isoformat()
        ),
        data_store=market,
        source=_Source(),
        policy=MarketUniversePolicy(
            minimum_master_member_count=8, minimum_history_rows=2
        ),
        throttle_seconds=0,
    )
    first = service.run_due(now=NOW)
    assert first["status"] == "failed"
    payload = json.loads(first["payload_json"])
    assert payload["market_universe_snapshot_id"] == master["snapshot_id"]
    assert payload["retryable"] is False
    assert service.run_due(now=NOW + timedelta(hours=2)) == first
    assert len(attempts) == 1


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


def test_internal_partial_receipt_cannot_freeze_full_market_history(tmp_path):
    """Enough rows and a full final day do not prove internal daily coverage."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    partial_day = dates[20]
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
        if day == partial_day:
            frame = frame.iloc[:1]
        store.ingest_market_daily_batch(
            trade_date=day, provider_name="unit_fixture", bars=frame
        )
    original = store.get_market_daily_ingestion_receipt(
        trade_date=partial_day, provider_name="unit_fixture"
    )
    source.daily_calls.clear()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store,
        source=source,
    )
    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    payload = json.loads(result["payload_json"])
    assert result["status"] == "failed"
    assert payload["full_market_history_frozen"] is False
    assert payload["full_market_missing_receipt_date_count"] == 0
    assert payload["full_market_partial_receipt_dates"] == [partial_day]
    assert payload["full_market_uncovered_symbol_session_count"] == 999
    assert payload["persisted_bar_ready_count"] == 1000
    assert payload["latest_cross_section_row_count"] == 1000
    assert payload["history_repair_entrypoint"] == "market_sync.full-market"
    assert source.daily_calls == []  # Legacy receipt bytes must remain immutable.
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date=partial_day, provider_name="unit_fixture"
        )
        == original
    )


def test_subtle_single_symbol_omission_cannot_freeze_full_market_history(tmp_path):
    """Omitting even 1 of 1000 symbols (99.9% coverage) fails closed under strict identity."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    partial_day = dates[20]
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
        if day == partial_day:
            frame = frame.iloc[:999]  # 999 out of 1000 symbols present
        store.ingest_market_daily_batch(
            trade_date=day, provider_name="unit_fixture", bars=frame
        )
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store,
        source=source,
    )
    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    payload = json.loads(result["payload_json"])
    assert result["status"] == "failed"
    assert payload["full_market_history_frozen"] is False
    assert payload["full_market_partial_receipt_dates"] == [partial_day]
    assert payload["full_market_uncovered_symbol_session_count"] == 1
    assert "full_market_daily_symbol_coverage_unverified" in payload["blockers"]


def test_unqualified_completed_market_run_disqualified_and_reverified_under_strict_policy(
    tmp_path,
):
    """A completed run lacking strict validation policy identity is disqualified and re-evaluated strictly."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    partial_day = dates[20]
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
        if day == partial_day:
            frame = frame.iloc[:999]  # 999 out of 1000 symbols present
        store.ingest_market_daily_batch(
            trade_date=day, provider_name="unit_fixture", bars=frame
        )

    # Seed stale completed run in db that lacks strict validation policy identity
    sync_run_id = "market_universe_sync:v7:unit_fixture:unit_fixture:2026-08-21"
    stale_payload = {
        "schema_version": "karkinos.market_universe_automation.v7",
        "trigger": "scheduled_after_close",
        "security_master_provider": "unit_fixture",
        "daily_bar_provider": "unit_fixture",
        "policy": {"schema_version": "karkinos.market_universe_policy.v2"},
        "asset_scope": "a_share",
        "full_market_history_frozen": True,
        "full_market_partial_receipt_dates": [],
        "full_market_uncovered_symbol_session_count": 0,
        "blockers": [],
    }
    db.upsert_automation_run_sync(
        {
            "run_id": sync_run_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "completed",
            "execution_mode": "read_only_research",
            "started_at": "2026-08-23T10:00:00+08:00",
            "finished_at": "2026-08-23T10:05:00+08:00",
            "payload": stale_payload,
        }
    )

    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store,
        source=source,
    )

    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    payload = json.loads(result["payload_json"])

    # 1. Existing completed run disqualified due to missing strict policy identity; re-evaluates and fails
    assert result["run_id"] != sync_run_id
    assert result["run_id"].startswith("market_universe_sync:2026-08-21:")
    assert result["source_ref"] == sync_run_id
    assert (
        payload["task_key"]
        == "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"
    )
    assert payload["supersedes_run_id"] == sync_run_id
    assert payload["prior_run_id"] == sync_run_id
    assert (
        payload["validation_policy_id"]
        == "karkinos.market_universe_coverage.strict_per_symbol.v1"
    )
    assert payload["schema_version"] == "karkinos.market_universe_automation.v7"
    assert result["status"] == "failed"
    assert payload["full_market_history_frozen"] is False
    assert payload["full_market_partial_receipt_dates"] == [partial_day]
    assert payload["full_market_uncovered_symbol_session_count"] == 1
    assert "full_market_daily_symbol_coverage_unverified" in payload["blockers"]

    # Historical legacy record in DB remains preserved immutably
    preserved_legacy = db.get_automation_run_sync(sync_run_id)
    assert preserved_legacy is not None
    assert preserved_legacy["status"] == "completed"

    # 2. Test valid completion with policy identity and idempotency on complete data store
    complete_db = AppDatabase(tmp_path / "complete_app.db")
    complete_db.init_sync()
    _verified_calendar(complete_db)
    complete_store = DataStore(tmp_path / "complete_market")
    complete_source = _Source()
    for day in dates:
        complete_frame = complete_source.fetch_market_daily_bars(day)
        complete_store.ingest_market_daily_batch(
            trade_date=day, provider_name="unit_fixture", bars=complete_frame
        )
    complete_service = MarketUniverseAutomationService(
        db=complete_db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=complete_store,
        source=complete_source,
    )
    res1 = complete_service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert res1["status"] == "completed"
    assert res1["run_id"].startswith("market_universe_sync:2026-08-21:")
    res1_payload = json.loads(res1["payload_json"])
    assert res1_payload["schema_version"] == "karkinos.market_universe_automation.v7"
    assert (
        res1_payload["validation_policy_id"]
        == "karkinos.market_universe_coverage.strict_per_symbol.v1"
    )
    assert (
        res1_payload["task_key"]
        == "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"
    )
    assert res1_payload["full_market_history_frozen"] is True
    assert bool(res1_payload.get("evidence_fingerprint")) is True

    # Subsequent run_due returns the completed run idempotently via evidence qualification
    res2 = complete_service.run_due(
        now=datetime(2026, 8, 23, 11, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert res2["run_id"] == res1["run_id"]
    assert res2["status"] == "completed"


def test_market_universe_routes_security_master_and_daily_bars_separately(
    monkeypatch,
    tmp_path,
) -> None:
    from data.source_policy import MarketDataUseCase
    from server.services.market import market_universe_automation

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
    validate_market_universe_automation_payload(payload)
    assert payload["schema_version"] == MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION
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
    from server.services.market.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    calls = []

    class Source:
        def list_symbols(self):
            return [f"{600000 + i:06d}" for i in range(41)]

        def list_symbol_metadata(self):
            return [
                {
                    "symbol": symbol,
                    "display_name": f"示例股票{symbol}",
                    "list_date": "2026-08-24" if symbol == "600040" else "2020-01-01",
                }
                for symbol in self.list_symbols()
            ]

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


def test_failed_retry_on_unchanged_evidence_creates_distinct_successor_without_overwriting_or_self_link(
    tmp_path,
):
    """When a failed run is retried after backoff with unchanged broken inputs,

    it produces a distinct successor run, preserves the original terminal run immutably,
    and never creates a self-referencing supersedes_run_id.
    """
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    partial_day = dates[20]
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
        if day == partial_day:
            frame = frame.iloc[:999]  # 999 out of 1000 symbols present
        store.ingest_market_daily_batch(
            trade_date=day, provider_name="unit_fixture", bars=frame
        )

    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store,
        source=source,
    )

    # Run 1: 10:00 fails closed
    t1 = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    res1 = service.run_due(now=t1)
    assert res1["status"] == "failed"
    run_1_id = res1["run_id"]
    assert res1["finished_at"] == t1.isoformat()

    # Verify Run 1 persisted in DB
    persisted_1 = db.get_automation_run_sync(run_1_id)
    assert persisted_1 is not None
    assert persisted_1["finished_at"] == t1.isoformat()
    assert persisted_1["status"] == "failed"

    # Run 2: 11:01 (after 1-hour backoff) retries with unchanged broken data
    t2 = datetime(2026, 8, 23, 11, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    res2 = service.run_due(now=t2)
    assert res2["status"] == "failed"
    run_2_id = res2["run_id"]

    # 1. Distinct successor run ID (not overwritten)
    assert run_2_id != run_1_id
    assert res2["finished_at"] == t2.isoformat()

    # 2. Source ref & supersedes point to Run 1, with NO self-link
    payload2 = json.loads(res2["payload_json"])
    assert payload2["supersedes_run_id"] == run_1_id
    assert payload2["supersedes_run_id"] != run_2_id
    assert res2["source_ref"] == run_1_id
    assert res2["source_ref"] != run_2_id

    # 3. Run 1 remains immutable in DB with original finished_at
    orig_check = db.get_automation_run_sync(run_1_id)
    assert orig_check is not None
    assert orig_check["finished_at"] == t1.isoformat()
    assert orig_check["status"] == "failed"

    # Run 3: 11:02 (within 1-hour backoff of Run 2) throttles and returns Run 2 without writing
    t3 = datetime(2026, 8, 23, 11, 2, tzinfo=ZoneInfo("Asia/Shanghai"))
    res3 = service.run_due(now=t3)
    assert res3["run_id"] == run_2_id
    assert res3["finished_at"] == t2.isoformat()


def test_cross_day_prior_resolution_finds_previous_day_run_by_task_key(tmp_path):
    """find_prior_market_universe_run resolves across natural dates by stable task_key."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-11-24"
    run_id_1124 = "market_universe_sync:2026-11-24:ab24fbe3755a1a21"
    payload_1124 = {
        "schema_version": "karkinos.market_universe_automation.v7",
        "task_key": task_key,
        "trade_date": "2026-11-24",
        "security_master_provider": "unit_fixture",
        "daily_bar_provider": "unit_fixture",
        "status": "failed",
    }
    db.upsert_automation_run_sync(
        {
            "run_id": run_id_1124,
            "run_type": "market_universe_sync",
            "run_date": "2026-11-24",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-11-24T19:07:00+08:00",
            "finished_at": "2026-11-24T19:07:05+08:00",
            "source_ref": None,
            "payload": payload_1124,
        }
    )

    # On next calendar day (11-25), look up prior run for task_key with run_date="2026-11-25"
    prior_on_next_day = find_prior_market_universe_run(
        db,
        task_key=task_key,
        trade_date="2026-11-24",
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
        run_date="2026-11-25",
    )
    assert prior_on_next_day is not None
    assert prior_on_next_day["run_id"] == run_id_1124

    # Seed a successor on 11-25
    run_id_1125 = "market_universe_sync:2026-11-24:fedcba9876543210"
    payload_1125 = {
        **payload_1124,
        "prior_run_id": run_id_1124,
        "supersedes_run_id": run_id_1124,
    }
    db.upsert_automation_run_sync(
        {
            "run_id": run_id_1125,
            "run_type": "market_universe_sync",
            "run_date": "2026-11-25",
            "status": "completed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-11-25T08:00:00+08:00",
            "finished_at": "2026-11-25T08:05:00+08:00",
            "source_ref": run_id_1124,
            "payload": payload_1125,
        }
    )

    # Lookup returns latest successor
    latest_prior = find_prior_market_universe_run(
        db,
        task_key=task_key,
        trade_date="2026-11-24",
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
        run_date="2026-11-25",
    )
    assert latest_prior is not None
    assert latest_prior["run_id"] == run_id_1125


def test_exact_completed_run_requires_qualification(tmp_path):
    """An exact matching completed run ID in DB must still satisfy the qualification contract to be returned."""
    from server.services.market.market_universe_automation import (
        MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        compute_market_coverage_evidence_fingerprint,
        content_fingerprint,
    )
    from server.services.market.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    partial_day = dates[20]
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
        if day == partial_day:
            frame = frame.iloc[:999]  # missing 1 symbol
        store.ingest_market_daily_batch(
            trade_date=day, provider_name="unit_fixture", bars=frame
        )

    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store,
        source=source,
    )
    snapshot, _, _, _, _ = service._ensure_market_universe_snapshot(
        trade_date="2026-08-21", master_provider_name="unit_fixture"
    )
    receipts = store.list_market_daily_ingestion_receipts(
        start_date="2026-04-01", end_date="2026-08-21", provider_name="unit_fixture"
    )

    ev_fp = compute_market_coverage_evidence_fingerprint(
        snapshot_id=snapshot["snapshot_id"],
        trading_dates=dates,
        receipts=receipts,
    )
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"
    exec_fp = content_fingerprint(
        {
            "task_key": task_key,
            "validation_policy_id": MARKET_UNIVERSE_COVERAGE_POLICY_ID,
            "policy_fingerprint": content_fingerprint(MarketUniversePolicy().to_dict()),
            "evidence_fingerprint": ev_fp,
        }
    )
    target_run_id = f"market_universe_sync:2026-08-21:{exec_fp[:16]}"

    # Seed an unqualified completed run with matching run_id (missing validation_policy_id in payload)
    db.upsert_automation_run_sync(
        {
            "run_id": target_run_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "completed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-23T10:00:00+08:00",
            "finished_at": "2026-08-23T10:05:00+08:00",
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "task_key": task_key,
                "validation_policy_id": "legacy.loose.v0",
            },
        }
    )

    result = service.run_due(
        now=datetime(2026, 8, 23, 10, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert result["status"] == "failed"
    assert result["run_id"] != target_run_id
    assert result["source_ref"] == target_run_id


def test_absent_current_snapshot_or_receipts_cannot_reuse_completed_run(tmp_path):
    """When a historical run is completed in DB, but the current data store is missing

    the snapshot or daily receipts, run_due MUST NOT reuse the completed run.
    Instead, it must re-verify and execute recovery.
    """
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    intact_store = DataStore(tmp_path / "intact_market")
    source = _Source()
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
        intact_store.ingest_market_daily_batch(
            trade_date=day, provider_name="unit_fixture", bars=frame
        )

    intact_service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=intact_store,
        source=source,
    )
    t1 = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    res1 = intact_service.run_due(now=t1)
    assert res1["status"] == "completed"
    run_1_id = res1["run_id"]

    # 1. Positive case: identical intact data store reuses the completed run idempotently
    source.daily_calls.clear()
    res1_reuse = intact_service.run_due(
        now=datetime(2026, 8, 23, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert res1_reuse["run_id"] == run_1_id
    assert res1_reuse["status"] == "completed"
    assert len(source.daily_calls) == 0  # Zero provider calls on qualified reuse

    # 2. Counterexample case: empty data store (simulating missing snapshot or wiped data directory)
    # Even though DB contains the completed run_1_id, absent current proof must NOT qualify for reuse!
    empty_store = DataStore(tmp_path / "empty_market")

    class _FailingDailySource(_Source):
        def fetch_market_daily_bars(self, trade_date: str) -> pd.DataFrame:
            raise RuntimeError("provider_temporarily_unavailable")

    failing_source = _FailingDailySource()
    empty_service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=empty_store,
        source=failing_source,
    )

    t2 = datetime(2026, 8, 23, 11, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    res2 = empty_service.run_due(now=t2)

    # Must NOT reuse run_1_id!
    assert res2["run_id"] != run_1_id
    # Must fail closed rather than claiming completed
    assert res2["status"] == "failed"
    # Original run_1_id in DB remains preserved immutably
    orig_in_db = db.get_automation_run_sync(run_1_id)
    assert orig_in_db is not None
    assert orig_in_db["status"] == "completed"
    assert orig_in_db["finished_at"] == t1.isoformat()
