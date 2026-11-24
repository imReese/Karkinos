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
            frame = frame.iloc[:999]
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

    # Run 1: 23:30 fails closed
    t1 = datetime(2026, 8, 23, 23, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    res1 = service.run_due(now=t1)
    assert res1["status"] == "failed"
    run_1_id = res1["run_id"]
    assert res1["run_date"] == "2026-08-23"

    # Backoff check: 00:15 (45 minutes later, across calendar midnight)
    # 1-hour backoff is still active, so scheduler must return run_1_id under same-task backoff!
    t_backoff = datetime(2026, 8, 24, 0, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    res_backoff = service.run_due(now=t_backoff)
    assert res_backoff["run_id"] == run_1_id
    assert res_backoff["status"] == "failed"

    # Run 2 on next calendar day: 2026-08-24 00:45 (after midnight and after 1-hour backoff)
    # The verified closed trading date is still 2026-08-21, but calendar run_date is 2026-08-24!
    t2 = datetime(2026, 8, 24, 0, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
    res2 = service.run_due(now=t2)
    assert res2["status"] == "failed"
    assert res2["run_date"] == "2026-08-24"

    # Production run_due correctly resolves the prior-day attempt across midnight
    assert res2["run_id"] != run_1_id
    payload2 = json.loads(res2["payload_json"])
    assert payload2["supersedes_run_id"] == run_1_id
    assert payload2["supersedes_run_id"] != res2["run_id"]
    assert res2["source_ref"] == run_1_id

    # Predecessor on day 1 remains completely intact
    pred = db.get_automation_run_sync(run_1_id)
    assert pred is not None
    assert pred["run_date"] == "2026-08-23"
    assert pred["finished_at"] == t1.isoformat()
    assert pred["status"] == "failed"


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
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
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

    members = [str(m.get("symbol") or "") for m in snapshot.get("members") or []]
    member_metadata = snapshot.get("member_metadata") or []
    ev_fp = compute_market_coverage_evidence_fingerprint(
        snapshot_id=snapshot["snapshot_id"],
        trading_dates=dates,
        receipts=receipts,
        members=members,
        member_metadata=member_metadata,
    )
    assert ev_fp is not None
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

    # Seed an unqualified completed run with matching exact execution run_id (missing validation_policy_id)
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
    # Production run_due computed exact target_run_id, found it unqualified,
    # completed fresh execution, allocated distinct successor, and preserved target_run_id!
    assert result["status"] == "completed"
    assert result["run_id"] != target_run_id
    assert result["source_ref"] == target_run_id

    # Original unqualified row remains in DB intact
    seeded = db.get_automation_run_sync(target_run_id)
    assert seeded is not None
    assert seeded["status"] == "completed"
    payload_seeded = json.loads(seeded["payload_json"])
    assert payload_seeded["validation_policy_id"] == "legacy.loose.v0"


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


def test_snapshot_retained_with_zero_receipts_cannot_reuse_completed_run(tmp_path):
    """When a snapshot exists on disk but zero receipts exist for the verified trading dates,

    run_due MUST NOT compute a valid fingerprint and MUST NOT reuse an existing completed run.
    """
    import shutil

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    source = _Source()
    dates = [
        day.date().isoformat() for day in pd.bdate_range(end="2026-08-21", periods=80)
    ]
    for day in dates:
        frame = source.fetch_market_daily_bars(day)
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
    t1 = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    res1 = service.run_due(now=t1)
    assert res1["status"] == "completed"
    completed_run_id = res1["run_id"]

    # Create store2 with snapshot retained but zero receipts in meta.db
    store2 = DataStore(tmp_path / "market2")
    snapshot = store.get_market_universe_snapshot(
        trade_date="2026-08-21", provider_name="unit_fixture"
    )
    store2.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        members=snapshot["members"],
    )

    class _FailingBarsSource(_Source):
        def fetch_market_daily_bars(self, trade_date: str) -> pd.DataFrame:
            raise RuntimeError("upstream_outage")

    failing_service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store2,
        source=_FailingBarsSource(),
    )
    t2 = datetime(2026, 8, 23, 11, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    res2 = failing_service.run_due(now=t2)

    # Must NOT reuse completed_run_id!
    assert res2["run_id"] != completed_run_id
    assert res2["status"] == "failed"


def test_calendar_blocked_repeated_calls_preserve_record_without_rewriting(tmp_path):
    """Repeated calendar-blocked calls return existing blocked run without rewriting timestamps."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    # Calendar is empty, so verified closed trading date is unavailable
    store = DataStore(tmp_path / "market")
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store,
        source=_Source(),
    )
    t1 = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    res1 = service.run_due(now=t1)
    assert res1["status"] == "blocked"
    pending_id = res1["run_id"]

    row_after_first = db.get_automation_run_sync(pending_id)
    assert row_after_first is not None
    t1_started = row_after_first["started_at"]
    t1_updated = row_after_first["updated_at"]

    # Second call at 11:00 on the same date
    t2 = datetime(2026, 8, 23, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    res2 = service.run_due(now=t2)
    assert res2["run_id"] == pending_id
    assert res2["status"] == "blocked"

    row_after_second = db.get_automation_run_sync(pending_id)
    assert row_after_second is not None
    # Timestamps are completely preserved; no overwrite occurred
    assert row_after_second["started_at"] == t1_started
    assert row_after_second["updated_at"] == t1_updated


def test_find_prior_run_handles_malformed_json_and_conflicting_task_key(tmp_path):
    """find_prior_market_universe_run skips malformed JSON and rejects conflicting explicit task_key."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"

    # 1. Candidate with malformed JSON
    db.upsert_automation_run_sync(
        {
            "run_id": "run_malformed_json",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-23T10:00:00+08:00",
            "finished_at": "2026-08-23T10:01:00+08:00",
            "payload": None,
        }
    )
    # Manually corrupt payload_json to simulate disk/store corruption
    import sqlite3

    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE automation_runs SET payload_json = '{' WHERE run_id = 'run_malformed_json'"
        )
        conn.commit()

    # 2. Candidate with identical trade date and provider, but conflicting explicit task_key
    db.upsert_automation_run_sync(
        {
            "run_id": "run_conflicting_key",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-23T10:05:00+08:00",
            "finished_at": "2026-08-23T10:06:00+08:00",
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "task_key": "market_universe_sync:other:other:2026-08-21",
            },
        }
    )

    # 3. Target candidate with matching task_key
    db.upsert_automation_run_sync(
        {
            "run_id": "run_target_valid",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "completed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-23T09:00:00+08:00",
            "finished_at": "2026-08-23T09:05:00+08:00",
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "task_key": task_key,
            },
        }
    )

    prior = find_prior_market_universe_run(
        db,
        task_key=task_key,
        trade_date="2026-08-21",
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert prior is not None
    assert prior["run_id"] == "run_target_valid"


def test_evidence_fingerprint_requires_snapshot_and_complete_date_receipts():
    """compute_market_coverage_evidence_fingerprint returns None on incomplete or empty coverage."""
    from server.services.market.market_universe_automation import (
        compute_market_coverage_evidence_fingerprint,
    )

    dates = ["2026-08-19", "2026-08-20", "2026-08-21"]
    receipts_complete = [
        {"trade_date": d, "provider_name": "fix", "row_count": 100} for d in dates
    ]
    receipts_missing_one = [
        {"trade_date": d, "provider_name": "fix", "row_count": 100} for d in dates[:2]
    ]
    receipts_zero_rows = [
        {"trade_date": d, "provider_name": "fix", "row_count": 0} for d in dates
    ]

    # Valid complete coverage produces non-empty fingerprint
    fp_valid = compute_market_coverage_evidence_fingerprint(
        snapshot_id="snap_1", trading_dates=dates, receipts=receipts_complete
    )
    assert fp_valid is not None and len(fp_valid) > 0

    # Incomplete: missing one date
    assert (
        compute_market_coverage_evidence_fingerprint(
            snapshot_id="snap_1", trading_dates=dates, receipts=receipts_missing_one
        )
        is None
    )

    # Incomplete: zero row count
    assert (
        compute_market_coverage_evidence_fingerprint(
            snapshot_id="snap_1", trading_dates=dates, receipts=receipts_zero_rows
        )
        is None
    )

    # Incomplete: empty receipts
    assert (
        compute_market_coverage_evidence_fingerprint(
            snapshot_id="snap_1", trading_dates=dates, receipts=[]
        )
        is None
    )

    # Incomplete: absent snapshot_id
    assert (
        compute_market_coverage_evidence_fingerprint(
            snapshot_id=None, trading_dates=dates, receipts=receipts_complete
        )
        is None
    )


def test_atomic_record_run_preserves_colliding_terminal_runs(tmp_path):
    """_record_run atomically preserves existing terminal runs and allocates distinct successor."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=DataStore(tmp_path / "market"),
        source=_Source(),
    )
    t1 = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    initial_run_id = "market_universe_sync:2026-08-21:initial_attempt"

    # Seed terminal row in database
    db.upsert_automation_run_sync(
        {
            "run_id": initial_run_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t1.isoformat(),
            "finished_at": t1.isoformat(),
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "trade_date": "2026-08-21",
                "attempt": 1,
            },
        }
    )

    # Attempt to record with same run_id but attempt 2 at t2
    t2 = datetime(2026, 8, 23, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    recorded = service._record_run(
        run_id=initial_run_id,
        run_date="2026-08-23",
        status="failed",
        now=t2,
        payload={
            "schema_version": "karkinos.market_universe_automation.v7",
            "trade_date": "2026-08-21",
            "attempt": 2,
        },
    )

    # Successor must have distinct run_id and point to initial_run_id
    assert recorded["run_id"] != initial_run_id
    assert recorded["source_ref"] == initial_run_id
    payload_recorded = json.loads(recorded["payload_json"])
    assert payload_recorded["supersedes_run_id"] == initial_run_id

    # Original terminal row in database remains completely intact and unmodified
    original_row = db.get_automation_run_sync(initial_run_id)
    assert original_row is not None
    assert original_row["started_at"] == t1.isoformat()
    original_payload = json.loads(original_row["payload_json"])
    assert original_payload["attempt"] == 1


def test_find_prior_run_pages_beyond_first_page_when_unrelated_runs_precede(tmp_path):
    """find_prior_market_universe_run pages beyond the 100-limit when matching row is deeper in history."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"

    # Seed the matching target predecessor FIRST so its created_at / updated_at is older
    db.upsert_automation_run_sync(
        {
            "run_id": "target_predecessor_at_pos_106",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-19",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-19T09:00:00+08:00",
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
            },
        }
    )

    # Seed 105 unrelated runs of market_universe_sync AFTER the target run
    for i in range(105):
        db.upsert_automation_run_sync(
            {
                "run_id": f"unrelated_run_{i:03d}",
                "run_type": "market_universe_sync",
                "run_date": "2026-08-20",
                "status": "failed",
                "execution_mode": "market_data_ingestion",
                "started_at": f"2026-08-20T{10 + i // 60:02d}:{i % 60:02d}:00+08:00",
                "payload": {"task_key": f"other_task_{i}"},
            }
        )

    # Verify target predecessor is NOT on page 1 (limit 100)
    page1 = db.list_automation_runs_sync(run_type="market_universe_sync", limit=100)
    assert not any(r["run_id"] == "target_predecessor_at_pos_106" for r in page1)

    prior = find_prior_market_universe_run(
        db,
        task_key=task_key,
        trade_date="2026-08-21",
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert prior is not None
    assert prior["run_id"] == "target_predecessor_at_pos_106"


def test_find_prior_run_ignores_falsy_task_key_and_does_not_admit_via_fallback(
    tmp_path,
):
    """find_prior_market_universe_run ignores falsy task keys and does not fall back to them."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    valid_task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"

    # Seed row with falsy empty string task_key matching trade_date and providers
    db.upsert_automation_run_sync(
        {
            "run_id": "malformed_falsy_task_key_run",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-20",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-20T10:00:00+08:00",
            "payload": {
                "task_key": "",
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
            },
        }
    )

    # When querying for valid_task_key, it must NOT match the falsy row via legacy fallback
    assert (
        find_prior_market_universe_run(
            db,
            task_key=valid_task_key,
            trade_date="2026-08-21",
            master_provider_name="unit_fixture",
            daily_provider_name="unit_fixture",
        )
        is None
    )

    # Seed row with None task_key matching trade_date and providers
    db.upsert_automation_run_sync(
        {
            "run_id": "none_task_key_run",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-20",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-20T10:05:00+08:00",
            "payload": {
                "task_key": None,
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
            },
        }
    )

    assert (
        find_prior_market_universe_run(
            db,
            task_key=valid_task_key,
            trade_date="2026-08-21",
            master_provider_name="unit_fixture",
            daily_provider_name="unit_fixture",
        )
        is None
    )

    # Now seed a valid predecessor with matching task_key
    db.upsert_automation_run_sync(
        {
            "run_id": "valid_predecessor_run",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-20",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-20T10:10:00+08:00",
            "payload": {
                "task_key": valid_task_key,
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
            },
        }
    )

    matched = find_prior_market_universe_run(
        db,
        task_key=valid_task_key,
        trade_date="2026-08-21",
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert matched is not None
    assert matched["run_id"] == "valid_predecessor_run"


def test_calendar_blocked_concurrent_conflict_reuses_pending_row(tmp_path):
    """When concurrent callers write a calendar-blocked pending run, the loser reuses the existing pending row."""
    import concurrent.futures

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=DataStore(tmp_path / "market"),
        source=_Source(),
    )
    t = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    pending_id = "market_universe_sync:pending:2026-08-23"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(
            service._record_run,
            run_id=pending_id,
            run_date="2026-08-23",
            status="blocked",
            now=t,
            payload={"blockers": ["verified_closed_trading_date_unavailable"]},
        )
        f2 = executor.submit(
            service._record_run,
            run_id=pending_id,
            run_date="2026-08-23",
            status="blocked",
            now=t,
            payload={"blockers": ["verified_closed_trading_date_unavailable"]},
        )
        res1 = f1.result()
        res2 = f2.result()

    assert res1["run_id"] == pending_id
    assert res2["run_id"] == pending_id
    runs = db.list_automation_runs_sync(run_type="market_universe_sync")
    assert len(runs) == 1


def test_collision_exhaustion_raises_and_never_overwrites_terminal_rows(tmp_path):
    """When candidate successor IDs are exhausted, _record_run fails with RuntimeError rather than overwriting."""
    from server.ai_runtime.contracts import content_fingerprint

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=DataStore(tmp_path / "market"),
        source=_Source(),
    )
    t = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    base_id = "market_universe_sync:2026-08-21:collision_exhaustion_base"

    # Compute and pre-seed all 10 candidate collision IDs into real database
    candidates = [base_id]
    curr_colliding = base_id
    for att in range(10):
        attempt_fp = content_fingerprint(
            {
                "initial_run_id": base_id,
                "colliding_run_id": curr_colliding,
                "target_predecessor": curr_colliding,
                "attempt": att + 1,
                "started_at": t.isoformat(),
            }
        )
        next_id = f"market_universe_sync:2026-08-21:{attempt_fp[:16]}"
        candidates.append(next_id)
        curr_colliding = next_id

    pred = None
    for cand_id in candidates:
        payload = {"attempt": "seed", "candidate_id": cand_id}
        if pred is not None:
            payload["supersedes_run_id"] = pred
        db.upsert_automation_run_sync(
            {
                "run_id": cand_id,
                "run_type": "market_universe_sync",
                "run_date": "2026-08-23",
                "status": "failed",
                "execution_mode": "market_data_ingestion",
                "started_at": t.isoformat(),
                "finished_at": t.isoformat(),
                "source_ref": pred,
                "payload": payload,
            }
        )
        pred = cand_id

    with pytest.raises(RuntimeError, match="automation_run_collision_exhaustion"):
        service._record_run(
            run_id=base_id,
            run_date="2026-08-23",
            status="failed",
            now=t,
            payload={
                "schema_version": "karkinos.market_universe_automation.v7",
                "trade_date": "2026-08-21",
                "attempt": "overwrite_attempt",
            },
        )

    # Verify all pre-seeded terminal rows remain completely untouched
    rows = db.list_automation_runs_sync(run_type="market_universe_sync", limit=100)
    assert len(rows) == len(candidates)
    for r in rows:
        payload = json.loads(r["payload_json"])
        assert payload.get("attempt") == "seed"


def test_collision_routing_preserves_latest_retry_predecessor(tmp_path):
    """Production run_due preserves lineage across multiple attempts, linking each retry to its latest predecessor."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")

    class _FailingDailySource(_Source):
        def fetch_market_daily_bars(self, trade_date: str) -> pd.DataFrame:
            raise ValueError("simulated_provider_bar_failure")

    failing_source = _FailingDailySource()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=store,
        source=failing_source,
    )

    t1 = datetime(2026, 8, 21, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    t2 = t1 + timedelta(hours=2)
    t3 = t2 + timedelta(hours=2)

    # Attempt 1 through production run_due: records initial terminal failure
    run_1 = service.run_due(now=t1)
    assert run_1["status"] == "failed"
    run_1_id = run_1["run_id"]
    p1 = json.loads(run_1["payload_json"])
    assert p1.get("supersedes_run_id") is None

    # Attempt 2 through production run_due: discovers run_1 as predecessor and attaches to it
    run_2 = service.run_due(now=t2)
    assert run_2["status"] == "failed"
    run_2_id = run_2["run_id"]
    assert run_2_id != run_1_id
    assert run_2["source_ref"] == run_1_id
    p2 = json.loads(run_2["payload_json"])
    assert p2["supersedes_run_id"] == run_1_id
    assert p2["prior_run_id"] == run_1_id

    # Attempt 3 through production run_due: discovers run_2 as latest retry and attaches to run_2, NOT run_1!
    run_3 = service.run_due(now=t3)
    assert run_3["status"] == "failed"
    run_3_id = run_3["run_id"]
    assert run_3_id != run_2_id
    assert run_3_id != run_1_id
    assert run_3["source_ref"] == run_2_id
    p3 = json.loads(run_3["payload_json"])
    assert p3["supersedes_run_id"] == run_2_id
    assert p3["prior_run_id"] == run_2_id

    # In real SQLite database: all 3 attempts are preserved immutably with exact predecessor links
    runs = db.list_automation_runs_sync(run_type="market_universe_sync", limit=10)
    assert len(runs) == 3
    run_map = {r["run_id"]: r for r in runs}
    assert (
        json.loads(run_map[run_1_id]["payload_json"]).get("supersedes_run_id") is None
    )
    assert (
        json.loads(run_map[run_2_id]["payload_json"])["supersedes_run_id"] == run_1_id
    )
    assert (
        json.loads(run_map[run_3_id]["payload_json"])["supersedes_run_id"] == run_2_id
    )
    assert run_map[run_2_id]["source_ref"] == run_1_id
    assert run_map[run_3_id]["source_ref"] == run_2_id


def test_allocation_after_second_collision_preserves_lineage(tmp_path):
    """When attempt 0 and attempt 1 both collide, attempt 2 allocates and links to the latest same-task retry."""
    from server.ai_runtime.contracts import content_fingerprint

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=DataStore(tmp_path / "market"),
        source=_Source(),
    )
    t = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    base_id = "market_universe_sync:2026-08-21:second_collision_base"
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"

    # Pre-seed base_id (Run 1)
    db.upsert_automation_run_sync(
        {
            "run_id": base_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "attempt": 1,
            },
        }
    )

    # Compute candidate 1 ID (which collides on attempt 0 conflict)
    cand_1_fp = content_fingerprint(
        {
            "initial_run_id": base_id,
            "colliding_run_id": base_id,
            "target_predecessor": base_id,
            "attempt": 1,
            "started_at": t.isoformat(),
        }
    )
    cand_1_id = f"market_universe_sync:2026-08-21:{cand_1_fp[:16]}"

    # Pre-seed candidate 1 (Run 2)
    db.upsert_automation_run_sync(
        {
            "run_id": cand_1_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "source_ref": base_id,
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "attempt": 2,
                "supersedes_run_id": base_id,
                "prior_run_id": base_id,
            },
        }
    )

    # Now call _record_run with base_id:
    # Attempt 0: collides with base_id.
    # Attempt 1: collides with cand_1_id.
    # Attempt 2: allocates cand_2_id, which successfully inserts!
    run_3 = service._record_run(
        run_id=base_id,
        run_date="2026-08-23",
        status="failed",
        now=t,
        payload={
            "task_key": task_key,
            "trade_date": "2026-08-21",
            "attempt": 3,
        },
    )

    assert run_3["run_id"] != base_id
    assert run_3["run_id"] != cand_1_id
    assert run_3["source_ref"] == cand_1_id
    p3 = json.loads(run_3["payload_json"])
    assert p3["supersedes_run_id"] == cand_1_id
    assert p3["prior_run_id"] == cand_1_id

    # Also verify task-identity isolation: a collision with an unrelated task key
    # does NOT replace the target predecessor.
    unrelated_task_key = "market_universe_sync:other:other:2026-08-21"
    known_pred = "market_universe_sync:2026-08-21:my_pred"

    # Pre-compute exact candidate 1 ID generated when colliding at base_id with known_pred
    unrelated_cand_fp = content_fingerprint(
        {
            "initial_run_id": base_id,
            "colliding_run_id": base_id,
            "target_predecessor": known_pred,
            "attempt": 1,
            "started_at": t.isoformat(),
        }
    )
    unrelated_cand_id = f"market_universe_sync:2026-08-21:{unrelated_cand_fp[:16]}"

    db.upsert_automation_run_sync(
        {
            "run_id": unrelated_cand_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "source_ref": "other_ref",
            "payload": {
                "task_key": unrelated_task_key,
                "trade_date": "2026-08-21",
            },
        }
    )
    run_isolated = service._record_run(
        run_id=base_id,
        run_date="2026-08-23",
        status="failed",
        source_ref=known_pred,
        now=t,
        payload={
            "task_key": task_key,
            "trade_date": "2026-08-21",
            "supersedes_run_id": known_pred,
            "prior_run_id": known_pred,
        },
    )
    assert run_isolated["run_id"] != base_id
    assert run_isolated["run_id"] != unrelated_cand_id
    assert run_isolated["source_ref"] == known_pred
    p_iso = json.loads(run_isolated["payload_json"])
    assert p_iso["supersedes_run_id"] == known_pred
    assert p_iso["prior_run_id"] == known_pred


def test_collision_handling_rejects_contradictory_and_snapshot_predecessors(tmp_path):
    """Collision routing rejects colliding rows with conflicting predecessor fields or snapshot source_ref."""
    from server.ai_runtime.contracts import content_fingerprint

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-04-01"
        ),
        data_store=DataStore(tmp_path / "market"),
        source=_Source(),
    )
    t = datetime(2026, 8, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    base_id = "market_universe_sync:2026-08-21:predecessor_defense_base"
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"
    initial_pred = "market_universe_sync:2026-08-21:verified_pred"

    # Pre-seed base_id (Run 1)
    db.upsert_automation_run_sync(
        {
            "run_id": base_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "attempt": 1,
            },
        }
    )

    # Compute candidate 1 ID (collides when target_predecessor is initial_pred)
    cand_1_fp = content_fingerprint(
        {
            "initial_run_id": base_id,
            "colliding_run_id": base_id,
            "target_predecessor": initial_pred,
            "attempt": 1,
            "started_at": t.isoformat(),
        }
    )
    cand_1_id = f"market_universe_sync:2026-08-21:{cand_1_fp[:16]}"

    # Scenario 1: Seed candidate 1 with contradictory predecessor fields
    db.upsert_automation_run_sync(
        {
            "run_id": cand_1_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "supersedes_run_id": initial_pred,
                "prior_run_id": "contradictory_other_run",
            },
        }
    )

    # Calling _record_run should collide with base_id (attempt 0), then collide with cand_1_id (attempt 1).
    # Since cand_1_id has contradictory fields, target_predecessor must NOT advance to cand_1_id.
    run_res = service._record_run(
        run_id=base_id,
        run_date="2026-08-23",
        status="failed",
        source_ref=initial_pred,
        now=t,
        payload={
            "task_key": task_key,
            "trade_date": "2026-08-21",
            "supersedes_run_id": initial_pred,
            "prior_run_id": initial_pred,
        },
    )
    assert run_res["run_id"] != base_id
    assert run_res["run_id"] != cand_1_id
    # Verified predecessor must remain initial_pred, NOT advance to contradictory cand_1_id!
    assert run_res["source_ref"] == initial_pred
    p_res = json.loads(run_res["payload_json"])
    assert p_res["supersedes_run_id"] == initial_pred
    assert p_res["prior_run_id"] == initial_pred

    # Scenario 2: Colliding row has explicit None for payload predecessor fields but snapshot in source_ref
    snapshot_id = "market_universe:snapshot:2026-08-21:sha256_mock"
    snap_cand_fp = content_fingerprint(
        {
            "initial_run_id": base_id,
            "colliding_run_id": base_id,
            "target_predecessor": base_id,
            "attempt": 1,
            "started_at": t.isoformat(),
        }
    )
    snap_cand_id = f"market_universe_sync:2026-08-21:{snap_cand_fp[:16]}"
    db.upsert_automation_run_sync(
        {
            "run_id": snap_cand_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "source_ref": snapshot_id,
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "supersedes_run_id": None,
                "prior_run_id": None,
                "market_universe_snapshot_id": snapshot_id,
            },
        }
    )
    run_snap_res = service._record_run(
        run_id=base_id,
        run_date="2026-08-23",
        status="failed",
        now=t,
        payload={
            "task_key": task_key,
            "trade_date": "2026-08-21",
            "market_universe_snapshot_id": snapshot_id,
        },
    )
    # Must NOT adopt snap_cand_id or snapshot_id as predecessor
    assert run_snap_res["source_ref"] == base_id
    p_snap = json.loads(run_snap_res["payload_json"])
    assert p_snap["supersedes_run_id"] == base_id
    assert p_snap["prior_run_id"] == base_id
    assert run_snap_res["source_ref"] != snap_cand_id
    assert p_snap["supersedes_run_id"] != snap_cand_id
    assert run_snap_res["source_ref"] != snapshot_id
    assert p_snap["supersedes_run_id"] != snapshot_id

    # Scenario 3: Initial collision with row having contradictory ancestry when caller has NO predecessor
    corrupt_base_id = "market_universe_sync:2026-08-21:corrupt_base"
    db.upsert_automation_run_sync(
        {
            "run_id": corrupt_base_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "supersedes_run_id": "run_X",
                "prior_run_id": "run_Y_contradicts",
            },
        }
    )
    run_corrupt = service._record_run(
        run_id=corrupt_base_id,
        run_date="2026-08-23",
        status="failed",
        now=t,
        payload={
            "task_key": task_key,
            "trade_date": "2026-08-21",
        },
    )
    # The allocator must NOT adopt the corrupt row as its target predecessor
    p_corrupt = json.loads(run_corrupt["payload_json"])
    assert p_corrupt.get("supersedes_run_id") is None
    assert p_corrupt.get("prior_run_id") is None
    assert run_corrupt["source_ref"] is None


def test_validate_run_predecessor_ancestry_rejects_malformed_and_conflicting_aliases(
    tmp_path,
):
    """validate_run_predecessor_ancestry strictly enforces consistency across aliases, source_ref, and chain."""
    from server.services.market.market_universe_automation import (
        validate_run_predecessor_ancestry,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    # Malformed explicit empty string alias
    is_valid, pred = validate_run_predecessor_ancestry(
        {"payload": {"supersedes_run_id": ""}}
    )
    assert not is_valid and pred is None

    # Malformed explicit whitespace alias
    is_valid, pred = validate_run_predecessor_ancestry(
        {"payload": {"prior_run_id": "   "}}
    )
    assert not is_valid and pred is None

    # Space-padded alias
    is_valid, pred = validate_run_predecessor_ancestry(
        {"payload": {"supersedes_run_id": "  padded_id  "}}
    )
    assert not is_valid and pred is None

    # Contradictory payload aliases
    is_valid, pred = validate_run_predecessor_ancestry(
        {"payload": {"supersedes_run_id": "run_A", "prior_run_id": "run_B"}}
    )
    assert not is_valid and pred is None

    # Conflicting source_ref with payload alias
    is_valid, pred = validate_run_predecessor_ancestry(
        {
            "payload": {"supersedes_run_id": "run_A", "prior_run_id": "run_A"},
            "source_ref": "run_B",
        }
    )
    assert not is_valid and pred is None

    # Explicit None in payload but conflicting source_ref naming a run
    is_valid, pred = validate_run_predecessor_ancestry(
        {
            "payload": {
                "supersedes_run_id": None,
                "prior_run_id": None,
                "market_universe_snapshot_id": "snap_1",
            },
            "source_ref": "run_other",
        }
    )
    assert not is_valid and pred is None

    # One explicit string alias and one explicit None (null)
    is_valid, pred = validate_run_predecessor_ancestry(
        {"payload": {"supersedes_run_id": "attempt_A", "prior_run_id": None}}
    )
    assert not is_valid and pred is None

    # Aliases naming the snapshot ID
    is_valid, pred = validate_run_predecessor_ancestry(
        {
            "payload": {
                "supersedes_run_id": "snap_1",
                "prior_run_id": "snap_1",
                "market_universe_snapshot_id": "snap_1",
            }
        }
    )
    assert not is_valid and pred is None

    # Numeric source_ref
    is_valid, pred = validate_run_predecessor_ancestry({"source_ref": 123})
    assert not is_valid and pred is None

    # Self-reference using persisted run_id without passing current_run_id
    is_valid, pred = validate_run_predecessor_ancestry(
        {
            "run_id": "persisted_run_1",
            "payload": {"supersedes_run_id": "persisted_run_1"},
        }
    )
    assert not is_valid and pred is None

    # Self-reference with explicit current_run_id
    is_valid, pred = validate_run_predecessor_ancestry(
        {"payload": {"supersedes_run_id": "self_run"}},
        current_run_id="self_run",
    )
    assert not is_valid and pred is None

    # Space-padded self-reference
    is_valid, pred = validate_run_predecessor_ancestry(
        {"run_id": "  padded_self  ", "payload": {"supersedes_run_id": "padded_self"}},
        current_run_id="  padded_self  ",
    )
    assert not is_valid and pred is None

    # Valid matching aliases and source_ref
    is_valid, pred = validate_run_predecessor_ancestry(
        {
            "payload": {"supersedes_run_id": "valid_run", "prior_run_id": "valid_run"},
            "source_ref": "valid_run",
        }
    )
    assert is_valid and pred == "valid_run"

    # Deep chain cycle detection through db: B -> A -> B
    db.upsert_automation_run_sync(
        {
            "run_id": "cycle_A",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-21T10:00:00+08:00",
            "payload": {"supersedes_run_id": "cycle_B", "prior_run_id": "cycle_B"},
        }
    )
    db.upsert_automation_run_sync(
        {
            "run_id": "cycle_B",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-21T10:05:00+08:00",
            "payload": {"supersedes_run_id": "cycle_A", "prior_run_id": "cycle_A"},
        }
    )
    is_valid, _ = validate_run_predecessor_ancestry(
        db.get_automation_run_sync("cycle_B"), db=db
    )
    assert not is_valid

    # Deep chain contradictory ancestor: B -> A where A has contradictory aliases
    db.upsert_automation_run_sync(
        {
            "run_id": "corrupt_ancestor_A",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-21T10:00:00+08:00",
            "payload": {
                "supersedes_run_id": "root_1",
                "prior_run_id": "root_2_contradicts",
            },
        }
    )
    db.upsert_automation_run_sync(
        {
            "run_id": "child_B",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-21T10:05:00+08:00",
            "payload": {
                "supersedes_run_id": "corrupt_ancestor_A",
                "prior_run_id": "corrupt_ancestor_A",
            },
        }
    )
    is_valid, _ = validate_run_predecessor_ancestry(
        db.get_automation_run_sync("child_B"), db=db
    )
    assert not is_valid

    # Valid root run with snapshot source_ref
    is_valid, pred = validate_run_predecessor_ancestry(
        {
            "payload": {
                "supersedes_run_id": None,
                "prior_run_id": None,
                "market_universe_snapshot_id": "snap_1",
            },
            "source_ref": "snap_1",
        }
    )
    assert is_valid and pred is None


def test_find_prior_run_and_run_due_rejects_contradictory_historical_predecessor(
    tmp_path,
):
    """find_prior_market_universe_run skips rows with contradictory ancestry."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"

    # Seed corrupt row with contradictory predecessor aliases
    db.upsert_automation_run_sync(
        {
            "run_id": "corrupt_predecessor_run",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-20",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-20T10:00:00+08:00",
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "supersedes_run_id": "run_1",
                "prior_run_id": "run_2_contradicts",
            },
        }
    )

    # find_prior_market_universe_run must skip the corrupt row
    assert (
        find_prior_market_universe_run(
            db,
            task_key=task_key,
            trade_date="2026-08-21",
            master_provider_name="unit_fixture",
            daily_provider_name="unit_fixture",
        )
        is None
    )

    # Seed valid root run and older valid successor
    db.upsert_automation_run_sync(
        {
            "run_id": "root_run",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-18",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-18T10:00:00+08:00",
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "supersedes_run_id": None,
                "prior_run_id": None,
            },
        }
    )
    db.upsert_automation_run_sync(
        {
            "run_id": "valid_older_predecessor",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-19",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-19T10:00:00+08:00",
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-21",
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "supersedes_run_id": "root_run",
                "prior_run_id": "root_run",
            },
        }
    )

    found = find_prior_market_universe_run(
        db,
        task_key=task_key,
        trade_date="2026-08-21",
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert found is not None
    assert found["run_id"] == "valid_older_predecessor"


def test_ancestor_chain_traversal_supports_deep_acyclic_chains_beyond_ten_links(
    tmp_path,
):
    """validate_run_predecessor_ancestry traverses acyclic predecessor chains beyond ten links without artificial limits."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
        validate_run_predecessor_ancestry,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"
    trade_date = "2026-08-21"

    # Chain 13 runs: run_00 (root) through run_12 (depth 12 > 10)
    for i in range(13):
        pred_id = f"run_{i - 1:02d}" if i > 0 else None
        db.upsert_automation_run_sync(
            {
                "run_id": f"run_{i:02d}",
                "run_type": "market_universe_sync",
                "run_date": "2026-08-21",
                "status": "failed",
                "execution_mode": "market_data_ingestion",
                "started_at": f"2026-08-21T10:{i:02d}:00+08:00",
                "payload": {
                    "task_key": task_key,
                    "trade_date": trade_date,
                    "security_master_provider": "unit_fixture",
                    "daily_bar_provider": "unit_fixture",
                    "supersedes_run_id": pred_id,
                    "prior_run_id": pred_id,
                },
            }
        )

    row_12 = db.get_automation_run_sync("run_12")
    assert row_12 is not None
    is_valid, pred = validate_run_predecessor_ancestry(
        row_12,
        db=db,
        task_key=task_key,
        trade_date=trade_date,
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert is_valid is True
    assert pred == "run_11"

    prior = find_prior_market_universe_run(
        db,
        task_key=task_key,
        trade_date=trade_date,
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert prior is not None
    assert prior["run_id"] == "run_12"


def test_production_run_due_rejects_contradictory_completed_and_recovers_from_self_linked_failure(
    tmp_path,
):
    """Production run_due refuses to reuse contradictory completed rows and recovers from self-linked failures."""
    from server.services.market.market_universe_truth import (
        MarketUniversePolicy,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    policy = MarketUniversePolicy(minimum_history_rows=2)
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-08-01"
        ),
        data_store=store,
        source=_Source(),
        policy=policy,
    )
    t = datetime(2026, 8, 21, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    trade_date = "2026-08-21"
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"

    # Part 1: Real production run_due produces legitimate qualified completed run
    run_1 = service.run_due(now=t)
    assert run_1["status"] == "completed"
    p1 = json.loads(run_1["payload_json"])
    run_1_id = run_1["run_id"]
    val_policy_id = p1["validation_policy_id"]
    policy_fp = p1["policy_fingerprint"]

    # Corrupt run_1 in DB so its only defect is contradictory ancestry
    p1_corrupt = dict(p1)
    p1_corrupt["supersedes_run_id"] = "attempt_A"
    p1_corrupt["prior_run_id"] = "attempt_B_contradicts"
    db.upsert_automation_run_sync(
        {
            **run_1,
            "payload": p1_corrupt,
        }
    )

    # Production run_due must NOT reuse the exact-ID row because of contradictory ancestry!
    # Instead, it must re-execute, collide in _record_run, reject collision reuse, and insert a new completed run!
    run_2 = service.run_due(now=t + timedelta(minutes=5))
    assert run_2["status"] == "completed"
    assert run_2["run_id"] != run_1_id
    assert run_2["source_ref"] != run_1_id
    p2 = json.loads(run_2["payload_json"])
    assert p2["supersedes_run_id"] == p2["prior_run_id"]
    # The original corrupted row in DB remains completely intact and unchanged
    orig_in_db = db.get_automation_run_sync(run_1_id)
    assert orig_in_db is not None
    p_orig = json.loads(orig_in_db["payload_json"])
    assert p_orig["supersedes_run_id"] == "attempt_A"
    assert p_orig["prior_run_id"] == "attempt_B_contradicts"

    # Part 2: Self-linked failure must NOT suppress recovery in run_due
    self_linked_id = "market_universe_sync:2026-08-21:self_linked_failure"
    db.upsert_automation_run_sync(
        {
            "run_id": self_linked_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t.isoformat(),
            "finished_at": t.isoformat(),
            "source_ref": self_linked_id,
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "task_key": task_key,
                "trade_date": trade_date,
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "validation_policy_id": val_policy_id,
                "policy_fingerprint": policy_fp,
                "retryable": False,
                "supersedes_run_id": self_linked_id,
                "prior_run_id": self_linked_id,
            },
        }
    )

    # Production run_due must ignore the self-linked unretryable failure and recover!
    run_result = service.run_due(now=t + timedelta(hours=1))
    assert run_result["status"] == "completed"
    assert run_result["run_id"] != self_linked_id
    assert run_result["source_ref"] != self_linked_id
    p_run = json.loads(run_result["payload_json"])
    assert p_run.get("supersedes_run_id") != self_linked_id
    assert p_run.get("prior_run_id") != self_linked_id

    # Part 3: Failure under identical policy throttles, while superseded policy allows fresh execution
    evidence_fp = p1["evidence_fingerprint"]
    snapshot_id = p1["market_universe_snapshot_id"]
    throttled_fail_id = "market_universe_sync:2026-08-21:matching_policy_fail"
    db.upsert_automation_run_sync(
        {
            "run_id": throttled_fail_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": (t + timedelta(hours=2)).isoformat(),
            "finished_at": (t + timedelta(hours=2)).isoformat(),
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "task_key": task_key,
                "trade_date": trade_date,
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "validation_policy_id": val_policy_id,
                "coverage_validation_policy_id": val_policy_id,
                "policy_fingerprint": policy_fp,
                "evidence_fingerprint": evidence_fp,
                "coverage_evidence_fingerprint": evidence_fp,
                "market_universe_snapshot_id": snapshot_id,
                "retryable": False,
            },
        }
    )
    # When policy and evidence match unretryable failure, run_due is throttled
    run_throttled = service.run_due(now=t + timedelta(hours=2, minutes=1))
    assert run_throttled["status"] == "failed"
    assert run_throttled["run_id"] == throttled_fail_id

    # Part 3b: Conflicting coverage policy alias does NOT suppress retry
    conflicting_policy_fail_id = (
        "market_universe_sync:2026-08-21:conflicting_policy_fail"
    )
    db.upsert_automation_run_sync(
        {
            "run_id": conflicting_policy_fail_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": (t + timedelta(hours=2, minutes=3)).isoformat(),
            "finished_at": (t + timedelta(hours=2, minutes=3)).isoformat(),
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "task_key": task_key,
                "trade_date": trade_date,
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "validation_policy_id": val_policy_id,
                "coverage_validation_policy_id": "conflicting_policy_v0",
                "policy_fingerprint": policy_fp,
                "evidence_fingerprint": evidence_fp,
                "coverage_evidence_fingerprint": evidence_fp,
                "market_universe_snapshot_id": snapshot_id,
                "retryable": False,
            },
        }
    )
    run_conflicting_policy = service.run_due(now=t + timedelta(hours=2, minutes=4))
    assert run_conflicting_policy["status"] == "completed"
    assert run_conflicting_policy["run_id"] != conflicting_policy_fail_id

    # Part 3c: Conflicting coverage evidence alias does NOT suppress retry
    conflicting_ev_fail_id = "market_universe_sync:2026-08-21:conflicting_ev_fail"
    db.upsert_automation_run_sync(
        {
            "run_id": conflicting_ev_fail_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": (t + timedelta(hours=2, minutes=5)).isoformat(),
            "finished_at": (t + timedelta(hours=2, minutes=5)).isoformat(),
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "task_key": task_key,
                "trade_date": trade_date,
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "validation_policy_id": val_policy_id,
                "coverage_validation_policy_id": val_policy_id,
                "policy_fingerprint": policy_fp,
                "evidence_fingerprint": evidence_fp,
                "coverage_evidence_fingerprint": "conflicting_evidence_fingerprint_old",
                "market_universe_snapshot_id": snapshot_id,
                "retryable": False,
            },
        }
    )
    run_conflicting_ev = service.run_due(now=t + timedelta(hours=2, minutes=6))
    assert run_conflicting_ev["status"] == "completed"
    assert run_conflicting_ev["run_id"] != conflicting_ev_fail_id

    # When policy changes, identical evidence does NOT suppress execution
    superseded_fail_id = "market_universe_sync:2026-08-21:superseded_policy_fail"
    db.upsert_automation_run_sync(
        {
            "run_id": superseded_fail_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-21",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": (t + timedelta(hours=2, minutes=7)).isoformat(),
            "finished_at": (t + timedelta(hours=2, minutes=7)).isoformat(),
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "task_key": task_key,
                "trade_date": trade_date,
                "security_master_provider": "unit_fixture",
                "daily_bar_provider": "unit_fixture",
                "validation_policy_id": "superseded_policy_v0",
                "policy_fingerprint": "superseded_fingerprint_00",
                "evidence_fingerprint": evidence_fp,
                "coverage_evidence_fingerprint": evidence_fp,
                "market_universe_snapshot_id": snapshot_id,
                "retryable": False,
            },
        }
    )
    run_policy_change = service.run_due(now=t + timedelta(hours=2, minutes=10))
    assert run_policy_change["status"] == "completed"
    assert run_policy_change["run_id"] != superseded_fail_id


def test_listing_inside_history_window_produces_fingerprint_and_reuses_completed(
    tmp_path,
):
    """When a stock lists midway through history window, complete coverage produces fingerprint and reuses completed."""
    from server.services.market.market_universe_automation import (
        compute_market_coverage_evidence_fingerprint,
    )
    from server.services.market.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")

    # Day 1: only stock A is listed (1 row). Day 2: stock A and stock B are listed (2 rows).
    dates = ["2026-08-20", "2026-08-21"]
    members = normalize_a_share_members(["600000", "600001"])
    member_metadata = [
        {"symbol": "600000", "list_date": "2026-01-01"},
        {"symbol": "600001", "list_date": "2026-08-21"},  # Lists on Day 2!
    ]
    t_cap = datetime(2026, 8, 21, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="unit_fixture",
        members=members,
        source_metadata=member_metadata,
        capture_started_at=t_cap,
        capture_completed_at=t_cap,
    )

    # Ingest daily bars: Day 1 has 1 bar (600000), Day 2 has 2 bars (600000, 600001)
    df_day1 = pd.DataFrame(
        [
            {
                "symbol": "600000",
                "timestamp": "2026-08-20T15:00:00+08:00",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000,
                "amount": 10200,
            }
        ]
    )
    df_day2 = pd.DataFrame(
        [
            {
                "symbol": "600000",
                "timestamp": "2026-08-21T15:00:00+08:00",
                "open": 10.2,
                "high": 10.6,
                "low": 10.0,
                "close": 10.4,
                "volume": 1000,
                "amount": 10400,
            },
            {
                "symbol": "600001",
                "timestamp": "2026-08-21T15:00:00+08:00",
                "open": 20.0,
                "high": 20.5,
                "low": 19.8,
                "close": 20.2,
                "volume": 500,
                "amount": 10100,
            },
        ]
    )
    store.ingest_market_daily_batch(
        trade_date="2026-08-20", provider_name="unit_fixture", bars=df_day1
    )
    store.ingest_market_daily_batch(
        trade_date="2026-08-21", provider_name="unit_fixture", bars=df_day2
    )

    receipts = store.list_market_daily_ingestion_receipts(
        start_date="2026-08-20", end_date="2026-08-21", provider_name="unit_fixture"
    )

    # 1. Fingerprint is computed properly despite Day 1 having 1 row (< len(members) == 2)
    fp = compute_market_coverage_evidence_fingerprint(
        snapshot_id="test_snap",
        trading_dates=dates,
        receipts=receipts,
        members=["600000", "600001"],
        member_metadata=member_metadata,
    )
    assert fp is not None

    # 2. End-to-end service execution verifies completion and deterministic reuse
    class _IpoSource:
        def __init__(self):
            self.daily_fetch_calls = 0

        def list_symbols(self):
            return ["600000", "600001"]

        def list_symbol_metadata(self):
            return [
                {"symbol": "600000", "display_name": "老股", "list_date": "2026-01-01"},
                {"symbol": "600001", "display_name": "新股", "list_date": "2026-08-21"},
            ]

        def fetch_market_daily_bars(self, trade_date: str):
            self.daily_fetch_calls += 1
            return pd.DataFrame()

    ipo_source = _IpoSource()
    policy = MarketUniversePolicy(
        panel_size=1,
        allocation_slots=1,
        minimum_master_member_count=2,
        minimum_history_rows=2,
    )
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture",
            tushare_token="",
            start_date="2026-08-20",
        ),
        data_store=store,
        source=ipo_source,
        policy=policy,
    )

    t_run = datetime(2026, 8, 21, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    res1 = service.run_due(now=t_run)
    assert res1["status"] == "completed"
    payload1 = json.loads(res1["payload_json"])
    assert payload1.get("evidence_fingerprint") is not None
    assert payload1.get("full_market_uncovered_symbol_session_count") == 0

    daily_calls_prior = ipo_source.daily_fetch_calls

    # Second call must reuse res1 identically with 0 additional provider calls
    res2 = service.run_due(now=t_run)
    assert res2["run_id"] == res1["run_id"]
    assert res2["status"] == "completed"
    assert ipo_source.daily_fetch_calls == daily_calls_prior


def test_is_qualified_market_universe_coverage_run_strict_types():
    """is_qualified_market_universe_coverage_run strictly validates types and rejects malformed values."""
    from server.services.market.market_universe_automation import (
        MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        is_qualified_market_universe_coverage_run,
    )

    base_payload = {
        "validation_policy_id": MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        "policy_fingerprint": "p_fp",
        "market_universe_snapshot_id": "snap_1",
        "evidence_fingerprint": "ev_fp",
        "full_market_history_frozen": True,
        "blockers": [],
        "full_market_partial_receipt_dates": [],
        "full_market_missing_receipt_dates": [],
        "full_market_uncovered_symbol_session_count": 0,
        "full_market_missing_receipt_date_count": 0,
        "full_market_partial_receipt_date_count": 0,
        "full_market_daily_receipt_count": 10,
    }

    def _make_run(payload):
        return {
            "status": "completed",
            "payload_json": json.dumps(payload),
        }

    # Baseline valid run qualifies
    assert is_qualified_market_universe_coverage_run(
        _make_run(base_payload),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
    )

    # Disqualify if full_market_history_frozen is a truthy string instead of True boolean
    p_bad_frozen = dict(base_payload, full_market_history_frozen="false")
    assert not is_qualified_market_universe_coverage_run(
        _make_run(p_bad_frozen),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
    )

    # Disqualify if uncovered count is a non-digit string or negative or boolean
    for bad_uncovered in ["broken", -1, True, False, 1]:
        p = dict(base_payload, full_market_uncovered_symbol_session_count=bad_uncovered)
        assert not is_qualified_market_universe_coverage_run(
            _make_run(p),
            expected_snapshot_id="snap_1",
            expected_fingerprint="ev_fp",
            expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
            expected_policy_fingerprint="p_fp",
        )

    # Disqualify if daily receipt count is <= 0 or non-int
    for bad_receipt_count in [0, -5, "broken", False]:
        p = dict(base_payload, full_market_daily_receipt_count=bad_receipt_count)
        assert not is_qualified_market_universe_coverage_run(
            _make_run(p),
            expected_snapshot_id="snap_1",
            expected_fingerprint="ev_fp",
            expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
            expected_policy_fingerprint="p_fp",
        )

    # Disqualify if blockers, partial dates, or missing dates are non-lists or non-empty
    for field in [
        "blockers",
        "full_market_partial_receipt_dates",
        "full_market_missing_receipt_dates",
    ]:
        for bad_val in [None, "", 0, {}, "none", ["item"]]:
            p = dict(base_payload, **{field: bad_val})
            assert not is_qualified_market_universe_coverage_run(
                _make_run(p),
                expected_snapshot_id="snap_1",
                expected_fingerprint="ev_fp",
                expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
                expected_policy_fingerprint="p_fp",
            )

    # Disqualify if policy alias counterpart contains falsy malformed value
    for bad_counterpart in ["", None, False, 0, "wrong"]:
        p_bad_alias = dict(
            base_payload,
            validation_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
            coverage_validation_policy_id=bad_counterpart,
        )
        assert not is_qualified_market_universe_coverage_run(
            _make_run(p_bad_alias),
            expected_snapshot_id="snap_1",
            expected_fingerprint="ev_fp",
            expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
            expected_policy_fingerprint="p_fp",
        )

    # Disqualify if evidence fingerprint alias counterpart contains falsy malformed value
    for bad_counterpart in ["", None, False, 0, "wrong"]:
        p_bad_fp_alias = dict(
            base_payload,
            evidence_fingerprint="ev_fp",
            coverage_evidence_fingerprint=bad_counterpart,
        )
        assert not is_qualified_market_universe_coverage_run(
            _make_run(p_bad_fp_alias),
            expected_snapshot_id="snap_1",
            expected_fingerprint="ev_fp",
            expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
            expected_policy_fingerprint="p_fp",
        )

    # Disqualify if neither policy alias or neither fingerprint alias is present
    p_no_policy = dict(base_payload)
    p_no_policy.pop("validation_policy_id", None)
    p_no_policy.pop("coverage_validation_policy_id", None)
    assert not is_qualified_market_universe_coverage_run(
        _make_run(p_no_policy),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
    )

    p_no_fp = dict(base_payload)
    p_no_fp.pop("evidence_fingerprint", None)
    p_no_fp.pop("coverage_evidence_fingerprint", None)
    assert not is_qualified_market_universe_coverage_run(
        _make_run(p_no_fp),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
    )

    # Disqualify if task_key does not match expected_task_key
    p_bad_task_key = dict(base_payload, task_key="other_task_key")
    assert not is_qualified_market_universe_coverage_run(
        _make_run(p_bad_task_key),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
        expected_task_key="expected_task_key",
    )

    # Qualify if task_key matches expected_task_key
    p_good_task_key = dict(base_payload, task_key="expected_task_key")
    assert is_qualified_market_universe_coverage_run(
        _make_run(p_good_task_key),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
        expected_task_key="expected_task_key",
    )


def test_market_universe_automation_requires_atomic_inserter(tmp_path):
    """MarketUniverseAutomationService raises TypeError when db lacks insert_automation_run_if_absent_sync."""
    dummy_db = SimpleNamespace(
        get_automation_run_sync=lambda rid: None,
        upsert_automation_run_sync=lambda run: run,
    )
    with pytest.raises(
        TypeError,
        match="market_universe_automation_requires_atomic_run_inserter",
    ):
        MarketUniverseAutomationService(
            db=dummy_db,
            config=SimpleNamespace(
                data_source="unit_fixture",
                tushare_token="",
                start_date="2026-04-01",
            ),
            data_store=DataStore(tmp_path / "market"),
            source=_Source(),
        )


def test_historical_legacy_fixture_reuse_and_collision_consistency_preserves_lineage(
    tmp_path,
):
    """Historical keyless legacy runs qualify consistently across discovery, reuse, and collision handling."""
    from server.services.market.market_universe_automation import (
        market_universe_legacy_candidate_ids,
    )
    from server.services.market.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    trade_date = "2026-08-21"
    master_provider = "unit_fixture"
    daily_provider = "unit_fixture"
    task_key = f"market_universe_sync:{master_provider}:{daily_provider}:{trade_date}"
    legacy_ids = market_universe_legacy_candidate_ids(
        master_provider, daily_provider, trade_date, task_key
    )

    # Seed historical v7 keyless root with scope fields
    v7_root_id = (
        f"market_universe_sync:v7:{master_provider}:{daily_provider}:{trade_date}"
    )
    t_v7 = datetime(2026, 8, 20, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    db.upsert_automation_run_sync(
        {
            "run_id": v7_root_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-20",
            "status": "completed",
            "execution_mode": "market_data_ingestion",
            "started_at": t_v7.isoformat(),
            "finished_at": t_v7.isoformat(),
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "trade_date": trade_date,
                "security_master_provider": master_provider,
                "daily_bar_provider": daily_provider,
                "supersedes_run_id": None,
                "prior_run_id": None,
            },
        }
    )

    policy = MarketUniversePolicy(minimum_history_rows=2)
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-08-01"
        ),
        data_store=DataStore(tmp_path / "market"),
        source=_Source(),
        policy=policy,
    )
    t_run = datetime(2026, 8, 21, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    # 1. Derive completion through production run_due; adopts v7_root_id as predecessor
    run_1 = service.run_due(now=t_run)
    assert run_1["status"] == "completed"
    assert run_1["source_ref"] == v7_root_id
    p1 = json.loads(run_1["payload_json"])
    assert p1["supersedes_run_id"] == v7_root_id
    assert p1["prior_run_id"] == v7_root_id
    assert p1["task_key"] == task_key

    # 2. Assert exact-ID reuse on second invocation
    run_2 = service.run_due(now=t_run + timedelta(minutes=5))
    assert run_2["run_id"] == run_1["run_id"]
    assert run_2["status"] == "completed"

    # 3. Verify original historical v7 row remains completely untouched
    orig_v7 = db.get_automation_run_sync(v7_root_id)
    assert orig_v7 is not None
    assert orig_v7["started_at"] == t_v7.isoformat()
    p_v7 = json.loads(orig_v7["payload_json"])
    assert p_v7["schema_version"] == "karkinos.market_universe_automation.v7"
    assert p_v7["supersedes_run_id"] is None


def test_exact_id_and_collision_reuse_reject_scope_and_run_type_conflicts(
    tmp_path,
):
    """Exact-ID reuse and collision reuse reject completions with conflicting provider or run type."""
    from server.services.market.market_universe_automation import (
        _row_matches_market_universe_scope,
    )
    from server.services.market.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    policy = MarketUniversePolicy(minimum_history_rows=2)
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-08-01"
        ),
        data_store=store,
        source=_Source(),
        policy=policy,
    )
    t = datetime(2026, 8, 21, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    run_1 = service.run_due(now=t)
    assert run_1["status"] == "completed"
    run_1_id = run_1["run_id"]
    p1 = json.loads(run_1["payload_json"])

    # 1. Alter daily provider in payload of exact deterministic row in DB
    p1_bad_provider = dict(p1)
    p1_bad_provider["daily_bar_provider"] = "conflicting_provider"
    db.upsert_automation_run_sync(
        {
            **run_1,
            "payload": p1_bad_provider,
        }
    )

    # run_due must reject exact-ID reuse due to scope conflict, and collision reuse must also reject it
    run_2 = service.run_due(now=t + timedelta(minutes=5))
    assert run_2["status"] == "completed"
    assert run_2["run_id"] != run_1_id

    # 2. Alter run_type of the new row in DB
    run_2_id = run_2["run_id"]
    db.upsert_automation_run_sync(
        {
            **run_2,
            "run_type": "other_automation_type",
            "payload": json.loads(run_2["payload_json"]),
        }
    )
    is_valid_scope, _ = _row_matches_market_universe_scope(
        db.get_automation_run_sync(run_2_id),
        run_id=run_2_id,
        task_key=p1["task_key"],
        trade_date="2026-08-21",
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert is_valid_scope is False


def test_collision_predecessor_adoption_rejects_scope_conflicts(
    tmp_path,
):
    """Collision predecessor adoption rejects colliding rows with conflicting daily provider."""
    from server.services.market.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    policy = MarketUniversePolicy(minimum_history_rows=2)
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-08-01"
        ),
        data_store=store,
        source=_Source(),
        policy=policy,
    )
    t = datetime(2026, 8, 21, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    trade_date = "2026-08-21"
    task_key = f"market_universe_sync:unit_fixture:unit_fixture:{trade_date}"
    deterministic_id = f"market_universe_sync:{trade_date}:{task_key}"

    # Seed a failed row at deterministic run ID with matching task_key but conflicting daily provider
    bad_colliding_row = {
        "run_id": deterministic_id,
        "run_type": "market_universe_sync",
        "run_date": trade_date,
        "status": "failed",
        "execution_mode": "market_data_ingestion",
        "started_at": t.isoformat(),
        "finished_at": t.isoformat(),
        "payload": {
            "task_key": task_key,
            "trade_date": trade_date,
            "security_master_provider": "unit_fixture",
            "daily_bar_provider": "conflicting_provider",
            "supersedes_run_id": None,
            "prior_run_id": None,
        },
    }
    db.upsert_automation_run_sync(bad_colliding_row)

    # Execute run_due: collides with deterministic_id, but must NOT adopt it as predecessor
    result = service.run_due(now=t + timedelta(minutes=5))
    assert result["status"] == "completed"
    assert result["run_id"] != deterministic_id
    assert result["source_ref"] != deterministic_id
    p_result = json.loads(result["payload_json"])
    assert p_result.get("supersedes_run_id") != deterministic_id
    assert p_result.get("prior_run_id") != deterministic_id


def test_failed_run_with_null_coverage_fingerprint_throttled_during_backoff(
    tmp_path,
):
    """Failed run with null coverage evidence fingerprint is throttled during backoff window when primary fingerprint matches."""
    from server.services.market.market_universe_truth import MarketUniversePolicy

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    store = DataStore(tmp_path / "market")
    policy = MarketUniversePolicy(minimum_history_rows=2)
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture", tushare_token="", start_date="2026-08-01"
        ),
        data_store=store,
        source=_Source(),
        policy=policy,
    )
    t = datetime(2026, 8, 21, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    trade_date = "2026-08-21"
    task_key = f"market_universe_sync:unit_fixture:unit_fixture:{trade_date}"
    primary_ev_fp = "primary_ev_fp_123"

    failed_row = {
        "run_id": f"market_universe_sync:{trade_date}:{task_key}",
        "run_type": "market_universe_sync",
        "run_date": trade_date,
        "status": "failed",
        "execution_mode": "market_data_ingestion",
        "started_at": t.isoformat(),
        "finished_at": t.isoformat(),
        "payload": {
            "task_key": task_key,
            "trade_date": trade_date,
            "security_master_provider": "unit_fixture",
            "daily_bar_provider": "unit_fixture",
            "validation_policy_id": "market_universe_coverage:v1",
            "policy_fingerprint": "policy_fp_123",
            "evidence_fingerprint": primary_ev_fp,
            "coverage_evidence_fingerprint": None,
            "retryable": True,
        },
    }
    db.upsert_automation_run_sync(failed_row)

    persisted_failed_row = db.get_automation_run_sync(failed_row["run_id"])
    assert persisted_failed_row is not None

    t_check = t + timedelta(minutes=1)
    is_throttled = service._is_failed_run_throttled(
        prior_run=persisted_failed_row,
        current=t_check,
        latest_master={"snapshot_id": "snap_1"},
        evidence_fingerprint=primary_ev_fp,
        validation_policy_id="market_universe_coverage:v1",
        policy_fingerprint="policy_fp_123",
    )
    assert is_throttled is True

    is_throttled_conflict = service._is_failed_run_throttled(
        prior_run=persisted_failed_row,
        current=t_check,
        latest_master={"snapshot_id": "snap_1"},
        evidence_fingerprint="different_ev_fp",
        validation_policy_id="market_universe_coverage:v1",
        policy_fingerprint="policy_fp_123",
    )
    assert is_throttled_conflict is False


def test_ancestor_scope_validation_rejects_explicit_conflicts_and_foreign_run_types(
    tmp_path,
):
    """validate_run_predecessor_ancestry rejects explicit date/provider conflicts and foreign run types."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
        validate_run_predecessor_ancestry,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"
    trade_date = "2026-08-21"
    master_provider = "unit_fixture"
    daily_provider = "unit_fixture"

    # Seed ancestor with matching task key but conflicting trade_date (Aug 20 vs Aug 21)
    db.upsert_automation_run_sync(
        {
            "run_id": "anc_conflict_date",
            "run_type": "market_universe_sync",
            "run_date": "2026-08-20",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-20T10:00:00+08:00",
            "payload": {
                "task_key": task_key,
                "trade_date": "2026-08-20",  # Explicit conflict with 2026-08-21!
                "security_master_provider": master_provider,
                "daily_bar_provider": daily_provider,
            },
        }
    )
    child_bad_date = {
        "run_id": "child_conflict_date",
        "payload": {
            "task_key": task_key,
            "supersedes_run_id": "anc_conflict_date",
            "prior_run_id": "anc_conflict_date",
        },
    }
    is_valid, _ = validate_run_predecessor_ancestry(
        child_bad_date,
        db=db,
        task_key=task_key,
        trade_date=trade_date,
        master_provider_name=master_provider,
        daily_provider_name=daily_provider,
    )
    assert not is_valid

    # Seed foreign run type at legacy ID
    legacy_v7_id = (
        f"market_universe_sync:v7:{master_provider}:{daily_provider}:{trade_date}"
    )
    db.upsert_automation_run_sync(
        {
            "run_id": legacy_v7_id,
            "run_type": "forward_seed_preparation",  # Foreign run type!
            "run_date": "2026-08-21",
            "status": "completed",
            "execution_mode": "market_data_ingestion",
            "started_at": "2026-08-21T10:00:00+08:00",
            "payload": {
                "trade_date": trade_date,
                "security_master_provider": master_provider,
                "daily_bar_provider": daily_provider,
            },
        }
    )
    # find_prior_market_universe_run must reject the foreign run type
    assert (
        find_prior_market_universe_run(
            db,
            task_key=task_key,
            trade_date=trade_date,
            master_provider_name=master_provider,
            daily_provider_name=daily_provider,
        )
        is None
    )


def test_prior_discovery_ancestry_traversal_is_linear_and_scope_filtered(tmp_path):
    """find_prior_market_universe_run filters candidates by scope and caches ancestor validity to avoid quadratic lookups."""
    from server.services.market.market_universe_automation import (
        find_prior_market_universe_run,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    task_key = "market_universe_sync:unit_fixture:unit_fixture:2026-08-21"
    trade_date = "2026-08-21"

    # Seed 50 descendants of a missing root (chain: 49 -> 48 -> ... -> 0 -> missing_root)
    pred = "missing_root_id"
    for i in range(50):
        run_id = f"descendant_run_{i:03d}"
        db.upsert_automation_run_sync(
            {
                "run_id": run_id,
                "run_type": "market_universe_sync",
                "run_date": "2026-08-21",
                "status": "failed",
                "execution_mode": "market_data_ingestion",
                "started_at": f"2026-08-21T10:{i // 60:02d}:{i % 60:02d}+08:00",
                "payload": {
                    "task_key": task_key,
                    "trade_date": trade_date,
                    "security_master_provider": "unit_fixture",
                    "daily_bar_provider": "unit_fixture",
                    "supersedes_run_id": pred,
                    "prior_run_id": pred,
                },
            }
        )
        pred = run_id

    getter_call_count = 0
    orig_getter = db.get_automation_run_sync

    def counted_getter(run_id):
        nonlocal getter_call_count
        getter_call_count += 1
        return orig_getter(run_id)

    db.get_automation_run_sync = counted_getter

    prior = find_prior_market_universe_run(
        db,
        task_key=task_key,
        trade_date=trade_date,
        master_provider_name="unit_fixture",
        daily_provider_name="unit_fixture",
    )
    assert prior is None
    # With ancestry caching, each ancestor is fetched at most once, strictly O(N) (< 60 calls)
    assert getter_call_count <= 60
