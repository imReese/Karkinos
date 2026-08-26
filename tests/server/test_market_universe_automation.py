from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import BarFrequency
from data.store import DataStore
from server.db import AppDatabase
from server.services.market_universe_automation import (
    MarketUniverseAutomationService,
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


class _PersistingManager:
    def __init__(self, store: DataStore) -> None:
        self._store = store
        self.calls = 0

    def get_bars(self, symbol, *args, **kwargs):
        self.calls += 1
        dates = pd.bdate_range(end="2026-08-21", periods=80)
        frame = pd.DataFrame(
            {
                "timestamp": dates,
                "open": [10.0] * len(dates),
                "high": [10.1] * len(dates),
                "low": [9.9] * len(dates),
                "close": [10.0] * len(dates),
                "volume": [1_000_000] * len(dates),
                "amount": [10_000_000] * len(dates),
            }
        )
        self._store.save_bars(
            symbol,
            BarFrequency.DAILY,
            frame,
            provider_name="unit_fixture",
            data_source="unit_fixture",
            adjustment_mode="none",
        )
        return SimpleNamespace(total_bars=len(frame))


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
    manager = _PersistingManager(store)
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
        data_manager=manager,
        source=source,
        sleep_fn=sleeps.append,
    )
    now = datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = service.run_due(now=now)
    second = service.run_due(now=now)

    assert first["status"] == "completed"
    assert second["run_id"] == first["run_id"]
    assert source.calls == 1
    assert manager.calls == 0
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
    assert payload["changes_account_truth"] is False
    assert payload["changes_strategy_promotion"] is False
    assert payload["creates_order"] is False
    assert payload["changes_execution_authority"] is False
    assert payload["changes_capital_authority"] is False


def test_market_universe_automation_blocks_without_verified_calendar(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = _Source()
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(data_source="unit_fixture", tushare_token=""),
        data_store=DataStore(tmp_path / "market"),
        data_manager=SimpleNamespace(),
        source=source,
    )

    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert result["status"] == "blocked"
    assert source.calls == 0
    payload = json.loads(result["payload_json"])
    assert payload["blockers"] == ["verified_closed_trading_date_unavailable"]


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
    manager = _PersistingManager(store)
    service = MarketUniverseAutomationService(
        db=db,
        config=SimpleNamespace(
            data_source="unit_fixture",
            tushare_token="",
            start_date="2026-04-01",
            initial_cash=100_000,
        ),
        data_store=store,
        data_manager=manager,
        source=source,
    )

    result = service.run_due(
        now=datetime(2026, 8, 23, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert result["status"] == "completed"
    assert manager.calls == 0
    assert source.daily_calls == trading_dates[10:]
    payload = json.loads(result["payload_json"])
    assert payload["persisted_receipt_skipped_count"] == 10
    assert payload["remote_bar_refresh_attempt_count"] == 70
