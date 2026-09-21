from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.services.verified_daily_market_jobs import (
    VERIFIED_DAILY_MARKET_JOB,
    VerifiedDailyMarketJobPlanningError,
    enqueue_latest_verified_daily_market_jobs,
)

NOW = datetime(2026, 9, 18, 8, 30, tzinfo=timezone.utc)
TRADE_DATE = date(2026, 9, 18)


def _calendar(year: int = 2026, *, trading_dates: set[date] | None = None) -> dict:
    trading_dates = {TRADE_DATE} if trading_dates is None else trading_dates
    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    days = []
    current = start
    while current < end:
        trading = current in trading_dates
        days.append(
            {
                "date": current.isoformat(),
                "is_trading_day": trading,
                "day_type": "trading" if trading else "closed",
                "source": "fixture",
            }
        )
        current += timedelta(days=1)
    source = "a" * 64
    official = "b" * 64
    return {
        "year": year,
        "exchange": "SSE",
        "days": days,
        "trading_day_count": sum(day["is_trading_day"] for day in days),
        "closed_day_count": sum(not day["is_trading_day"] for day in days),
        "source_fingerprint": source,
        "verification_source_fingerprint": source,
        "official_source_fingerprint": official,
        "official_source_url": "https://example.test/calendar",
        "official_verified_at": "2026-09-18T08:00:00Z",
        "official_verified_by": "fixture",
        "official_verification_status": "verified",
    }


def _planner_db(rows, *, verified_calendar=True):
    return SimpleNamespace(
        get_market_calendar_snapshot_sync=(
            (lambda *, exchange, year: _calendar(year))
            if verified_calendar
            else (lambda *, exchange, year: None)
        ),
        list_watchlist_assets_sync=lambda: list(rows),
    )


def _store(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    return SQLiteJobStore(db.path)


def _config():
    return SimpleNamespace(
        market_data_source_policy="karkinos.market.source.free_cn_research.v1",
        data_source="free",
        tushare_token="",
    )


def test_planner_enqueues_one_durable_job_per_supported_watchlist_asset(tmp_path):
    db = _planner_db(
        [
            {"symbol": "600000", "instrument_type": "stock"},
            {"symbol": "510300", "instrument_type": "etf"},
            {"symbol": "012999", "instrument_type": "open_end_fund"},
        ]
    )
    plan = enqueue_latest_verified_daily_market_jobs(
        db,
        _config(),
        _store(tmp_path),
        now=NOW,
    )

    assert plan.trade_date == TRADE_DATE
    assert plan.instruments == (
        InstrumentKey("510300", InstrumentType.ETF),
        InstrumentKey("600000", InstrumentType.STOCK),
    )
    assert plan.planned_count == 2
    assert all(job.kind == VERIFIED_DAILY_MARKET_JOB for job in plan.jobs)
    assert [job.payload["instruments"] for job in plan.jobs] == [
        [{"symbol": "510300", "instrument_type": "etf"}],
        [{"symbol": "600000", "instrument_type": "stock"}],
    ]
    assert all(
        job.payload["source_policy_id"] == "karkinos.market.source.free_cn_research.v1"
        for job in plan.jobs
    )
    assert all(job.payload["calendar_evidence_refs"] for job in plan.jobs)


def test_planner_is_idempotent_for_same_market_facts(tmp_path):
    db = _planner_db([{"symbol": "600000", "instrument_type": "stock"}])
    store = _store(tmp_path)

    first = enqueue_latest_verified_daily_market_jobs(db, _config(), store, now=NOW)
    second = enqueue_latest_verified_daily_market_jobs(
        db, _config(), store, now=NOW + timedelta(seconds=5)
    )

    assert first.jobs[0].job_id == second.jobs[0].job_id
    assert first.jobs[0].input_fingerprint == second.jobs[0].input_fingerprint


def test_planner_backfills_verified_days_within_window_without_duplicate_jobs(tmp_path):
    db = _planner_db([{"symbol": "600000", "instrument_type": "stock"}])
    db.get_market_calendar_snapshot_sync = lambda *, exchange, year: _calendar(
        year, trading_dates={date(2026, 9, day) for day in (15, 16, 18)}
    )
    store = _store(tmp_path)
    first = enqueue_latest_verified_daily_market_jobs(
        db, _config(), store, now=NOW, lookback_days=3
    )
    second = enqueue_latest_verified_daily_market_jobs(
        db, _config(), store, now=NOW + timedelta(seconds=5), lookback_days=3
    )
    assert [job.payload["trade_date"] for job in first.jobs] == [
        "2026-09-16",
        "2026-09-18",
    ]
    assert first.trade_date == TRADE_DATE
    assert [job.job_id for job in first.jobs] == [job.job_id for job in second.jobs]
    assert len({job.job_id for job in first.jobs}) == 2


def test_planner_returns_empty_without_verified_closed_calendar(tmp_path):
    db = _planner_db(
        [{"symbol": "600000", "instrument_type": "stock"}],
        verified_calendar=False,
    )
    plan = enqueue_latest_verified_daily_market_jobs(
        db, _config(), _store(tmp_path), now=NOW
    )

    assert plan.trade_date is None
    assert plan.jobs == ()


def test_planner_returns_empty_for_watchlist_without_daily_v1_assets(tmp_path):
    db = _planner_db([{"symbol": "012999", "instrument_type": "open_end_fund"}])
    plan = enqueue_latest_verified_daily_market_jobs(
        db, _config(), _store(tmp_path), now=NOW
    )

    assert plan.trade_date == TRADE_DATE
    assert plan.instruments == ()
    assert plan.jobs == ()


def test_planner_rejects_invalid_persisted_watchlist_identity(tmp_path):
    db = _planner_db([{"symbol": "600000", "instrument_type": "mystery"}])

    with pytest.raises(
        VerifiedDailyMarketJobPlanningError,
        match="verified_daily_market_watchlist_identity_invalid",
    ):
        enqueue_latest_verified_daily_market_jobs(
            db, _config(), _store(tmp_path), now=NOW
        )
