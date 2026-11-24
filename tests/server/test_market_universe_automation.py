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
                "target_predecessor": base_id,
                "attempt": att + 1,
                "started_at": t.isoformat(),
            }
        )
        next_id = f"market_universe_sync:2026-08-21:{attempt_fp[:16]}"
        candidates.append(next_id)
        curr_colliding = next_id

    for cand_id in candidates:
        db.upsert_automation_run_sync(
            {
                "run_id": cand_id,
                "run_type": "market_universe_sync",
                "run_date": "2026-08-23",
                "status": "failed",
                "execution_mode": "market_data_ingestion",
                "started_at": t.isoformat(),
                "finished_at": t.isoformat(),
                "payload": {"attempt": "seed", "candidate_id": cand_id},
            }
        )

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
    """When a task has retried, collision on base ID attaches the new attempt to the latest retry, not the base ID."""
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
    t2 = datetime(2026, 8, 23, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    t3 = datetime(2026, 8, 23, 10, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

    base_id = "market_universe_sync:2026-08-21:deterministic_base"
    retry_1_id = "market_universe_sync:2026-08-21:retry_attempt_1"

    # Seed Run 1 (base attempt, failed)
    db.upsert_automation_run_sync(
        {
            "run_id": base_id,
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

    # Seed Run 2 (retry 1, supersedes base_id)
    db.upsert_automation_run_sync(
        {
            "run_id": retry_1_id,
            "run_type": "market_universe_sync",
            "run_date": "2026-08-23",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": t2.isoformat(),
            "finished_at": t2.isoformat(),
            "source_ref": base_id,
            "payload": {
                "schema_version": "karkinos.market_universe_automation.v7",
                "trade_date": "2026-08-21",
                "attempt": 2,
                "supersedes_run_id": base_id,
                "prior_run_id": base_id,
            },
        }
    )

    # Now Run 3 executes. Caller knows retry_1_id was the prior run,
    # but the deterministic target identity resolves to base_id.
    run_3 = service._record_run(
        run_id=base_id,
        run_date="2026-08-23",
        status="failed",
        source_ref=retry_1_id,
        now=t3,
        payload={
            "schema_version": "karkinos.market_universe_automation.v7",
            "trade_date": "2026-08-21",
            "attempt": 3,
            "supersedes_run_id": retry_1_id,
            "prior_run_id": retry_1_id,
        },
    )

    # Run 3 must allocate a distinct run_id and point to retry_1_id (the latest retry), NOT base_id!
    assert run_3["run_id"] != base_id
    assert run_3["run_id"] != retry_1_id
    assert run_3["source_ref"] == retry_1_id
    p3 = json.loads(run_3["payload_json"])
    assert p3["supersedes_run_id"] == retry_1_id
    assert p3["prior_run_id"] == retry_1_id


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

    # Disqualify if validation policy aliases contradict each other
    p_bad_policy_alias = dict(
        base_payload,
        validation_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        coverage_validation_policy_id="contradictory_policy",
    )
    assert not is_qualified_market_universe_coverage_run(
        _make_run(p_bad_policy_alias),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
    )

    # Disqualify if evidence fingerprint aliases contradict each other
    p_bad_fp_alias = dict(
        base_payload,
        evidence_fingerprint="ev_fp",
        coverage_evidence_fingerprint="contradictory_fp",
    )
    assert not is_qualified_market_universe_coverage_run(
        _make_run(p_bad_fp_alias),
        expected_snapshot_id="snap_1",
        expected_fingerprint="ev_fp",
        expected_policy_id=MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        expected_policy_fingerprint="p_fp",
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
