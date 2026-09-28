from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.http.backtest_endpoints.datasets import create_router
from server.persistence.jobs import SQLiteJobStore
from server.services.daily_market_collection import DAILY_MARKET_COLLECTION_JOB
from server.services.verified_daily_market_jobs import (
    VERIFIED_DAILY_MARKET_JOB,
    VerifiedDailyMarketJobPlanningError,
    enqueue_latest_daily_market_collection_jobs,
    enqueue_latest_verified_daily_market_jobs,
    enqueue_verified_daily_market_jobs_for_range,
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


def _verified_jobs_api(tmp_path, *, trading_dates: set[date], verified: bool = True):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    calendar = _calendar(trading_dates=trading_dates)
    stored = db.upsert_market_calendar_snapshot_sync(calendar)
    if verified:
        db.update_market_calendar_verification_sync(
            exchange="SSE",
            year=2026,
            source_fingerprint=stored["source_fingerprint"],
            verification_status="verified",
            official_source_url="https://example.test/calendar",
            official_source_fingerprint="b" * 64,
            verified_by="fixture",
        )
    state = AppState()
    state.db, state.config = db, _config()
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(create_router())
    return TestClient(app), SQLiteJobStore(db.path)


def test_verified_jobs_http_enqueues_only_verified_closed_sessions_and_is_idempotent(
    tmp_path,
):
    client, store = _verified_jobs_api(
        tmp_path,
        trading_dates={date(2026, 9, 16), date(2026, 9, 18)},
    )
    request = {
        "symbol": "510300",
        "instrument_type": "etf",
        "start_date": "2026-09-16",
        "end_date": "2026-09-18",
    }

    with client:
        first = client.post("/api/backtest/datasets/verified-jobs", json=request)
        repeated = client.post("/api/backtest/datasets/verified-jobs", json=request)
        status = client.get(
            f"/api/backtest/datasets/verified-jobs/{first.json()['jobs'][0]['job_id']}"
        )

    assert first.status_code == 200, first.text
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == first.json()
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "queued"
    assert status.json()["trade_date"] == "2026-09-16"
    jobs = first.json()["jobs"]
    assert [job["trade_date"] for job in jobs] == ["2026-09-16", "2026-09-18"]
    assert len({job["job_id"] for job in jobs}) == 2
    assert all(job["status"] == "queued" and job["result_ref"] is None for job in jobs)
    persisted = store.list_recent(VERIFIED_DAILY_MARKET_JOB)
    assert {row["job_id"] for row in persisted} == {job["job_id"] for job in jobs}
    payloads = [json.loads(row["payload_json"]) for row in persisted]
    assert all(
        payload["instruments"] == [{"symbol": "510300", "instrument_type": "etf"}]
        and payload["calendar_evidence_refs"]
        and payload["source_policy_id"] == "karkinos.market.source.free_cn_research.v1"
        for payload in payloads
    )
    assert store.list_recent(DAILY_MARKET_COLLECTION_JOB) == []
    assert not DatasetCatalog(tmp_path / "research").path.exists()


def test_verified_jobs_http_rejects_unverified_calendar_without_partial_enqueue(
    tmp_path,
):
    client, store = _verified_jobs_api(
        tmp_path,
        trading_dates={date(2026, 9, 16)},
        verified=False,
    )
    with client:
        response = client.post(
            "/api/backtest/datasets/verified-jobs",
            json={
                "symbol": "600000",
                "instrument_type": "stock",
                "start_date": "2026-09-16",
                "end_date": "2026-09-18",
            },
        )
    assert response.status_code == 409
    assert (
        response.json()["detail"] == "verified_daily_market_trading_dates_unavailable"
    )
    assert store.list_recent(VERIFIED_DAILY_MARKET_JOB) == []


def test_verified_jobs_http_enqueue_rolls_back_when_later_day_write_fails(tmp_path):
    client, store = _verified_jobs_api(
        tmp_path,
        trading_dates={date(2026, 9, 16), date(2026, 9, 18)},
    )
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_second_verified_job BEFORE INSERT ON job_runs "
            "WHEN NEW.kind='market_daily_verified' AND "
            "instr(NEW.payload_json, '2026-09-18') > 0 "
            "BEGIN SELECT RAISE(ABORT, 'fixture_second_day_write_failed'); END"
        )

    with client:
        response = client.post(
            "/api/backtest/datasets/verified-jobs",
            json={
                "symbol": "600000",
                "instrument_type": "stock",
                "start_date": "2026-09-16",
                "end_date": "2026-09-18",
            },
        )

    assert response.status_code == 503
    assert store.list_recent(VERIFIED_DAILY_MARKET_JOB) == []


def test_verified_job_http_distinguishes_malformed_id_from_corrupt_stored_job(tmp_path):
    client, store = _verified_jobs_api(
        tmp_path,
        trading_dates={date(2026, 9, 18)},
    )
    with client:
        submitted = client.post(
            "/api/backtest/datasets/verified-jobs",
            json={
                "symbol": "600000",
                "instrument_type": "stock",
                "start_date": "2026-09-18",
                "end_date": "2026-09-18",
            },
        )
        malformed = client.get("/api/backtest/datasets/verified-jobs/bad-id")
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["jobs"][0]["job_id"]
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE job_runs SET input_fingerprint=? WHERE job_id=?",
            ("f" * 64, job_id),
        )
    with client:
        corrupt = client.get(f"/api/backtest/datasets/verified-jobs/{job_id}")

    assert malformed.status_code == 422
    assert malformed.json()["detail"] == "verified_market_job_id_invalid"
    assert corrupt.status_code == 409
    assert corrupt.json()["detail"] == "verified_market_job_identity_conflict"


@pytest.mark.parametrize(
    "start_date,end_date",
    [
        ("2026-09-19", "2026-09-18"),
        ("2025-01-01", "2026-09-18"),
        ("2099-01-01", "2099-01-02"),
    ],
)
def test_verified_jobs_http_rejects_invalid_or_unclosed_range(
    tmp_path, start_date, end_date
):
    client, store = _verified_jobs_api(
        tmp_path,
        trading_dates={date(2026, 9, 18)},
    )
    with client:
        response = client.post(
            "/api/backtest/datasets/verified-jobs",
            json={
                "symbol": "600000",
                "instrument_type": "stock",
                "start_date": start_date,
                "end_date": end_date,
            },
        )
    assert response.status_code == 422
    assert store.list_recent(VERIFIED_DAILY_MARKET_JOB) == []


def test_verified_jobs_do_not_enqueue_todays_session_before_post_close(tmp_path):
    store = _store(tmp_path)
    db = _planner_db([])
    with pytest.raises(ValueError, match="verified_trading_date_not_closed"):
        enqueue_verified_daily_market_jobs_for_range(
            db,
            _config(),
            store,
            instrument=InstrumentKey("600000", InstrumentType.STOCK),
            start_date=TRADE_DATE,
            end_date=TRADE_DATE,
            now=datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc),
        )
    assert store.list_recent(VERIFIED_DAILY_MARKET_JOB) == []


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


def test_default_collection_and_explicit_verification_have_distinct_job_identity(
    tmp_path,
):
    db = _planner_db([{"symbol": "600000", "instrument_type": "stock"}])
    store = _store(tmp_path)

    collected = enqueue_latest_daily_market_collection_jobs(
        db, _config(), store, now=NOW
    )
    verified = enqueue_latest_verified_daily_market_jobs(db, _config(), store, now=NOW)

    assert collected.jobs[0].kind == DAILY_MARKET_COLLECTION_JOB
    assert collected.jobs[0].payload["instrument"] == {
        "symbol": "600000",
        "instrument_type": "stock",
    }
    assert verified.jobs[0].kind == VERIFIED_DAILY_MARKET_JOB
    assert collected.jobs[0].job_id != verified.jobs[0].job_id


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
