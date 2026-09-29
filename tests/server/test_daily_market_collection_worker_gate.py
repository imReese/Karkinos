"""Persisted automatic collection must retain its planning authority at execution."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from data.source_policy import CN_RESEARCH_V1, FREE_CN_RESEARCH_V1
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.services.daily_market_collection import DailyMarketCollectionFailure
from server.services.verified_daily_market_jobs import (
    DAILY_MARKET_COLLECTION_JOB,
    enqueue_latest_daily_market_collection_jobs,
)
from server.workers.data_worker import (
    _require_current_daily_market_collection_job,
    execute_daily_market_collection_job,
)

DAY = date(2025, 9, 18)
PLAN_NOW = datetime(2025, 9, 18, 8, 30, tzinfo=timezone.utc)


def _calendar(*, source_fingerprint: str = "a" * 64) -> dict:
    days = []
    current = date(DAY.year, 1, 1)
    while current.year == DAY.year:
        days.append({"date": current.isoformat(), "is_trading_day": current == DAY})
        current += timedelta(days=1)
    return {
        "year": DAY.year,
        "exchange": "SSE",
        "days": days,
        "trading_day_count": 1,
        "closed_day_count": len(days) - 1,
        "source_fingerprint": source_fingerprint,
    }


def _verified_calendar(db: AppDatabase, *, fingerprint: str = "a" * 64) -> None:
    stored = db.upsert_market_calendar_snapshot_sync(
        _calendar(source_fingerprint=fingerprint)
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=DAY.year,
        source_fingerprint=stored["source_fingerprint"],
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )


def _claimed_collection(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _verified_calendar(db)
    db.upsert_watchlist_asset_sync(symbol="600000", instrument_type="stock")
    config = SimpleNamespace(market_data_source_policy=CN_RESEARCH_V1.policy_id)
    store = SQLiteJobStore(db.path)
    plan = enqueue_latest_daily_market_collection_jobs(db, config, store, now=PLAN_NOW)
    assert plan.planned_count == 1
    job = store.claim(
        DAILY_MARKET_COLLECTION_JOB, "worker", now=datetime.now(timezone.utc)
    )
    assert job is not None
    return db, config, store, job


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stale_fact", "expected_error"),
    [
        ("deleted_watchlist", "daily_market_collection_watchlist_stale"),
        ("changed_identity", "daily_market_collection_watchlist_stale"),
        ("changed_policy", "daily_market_collection_source_policy_stale"),
        ("changed_calendar", "daily_market_collection_calendar_evidence_stale"),
    ],
)
async def test_stale_queued_collection_never_enters_provider(
    tmp_path, stale_fact: str, expected_error: str
) -> None:
    db, config, store, job = _claimed_collection(tmp_path)
    if stale_fact == "deleted_watchlist":
        assert db.delete_watchlist_asset_sync("600000")
    elif stale_fact == "changed_identity":
        db.upsert_watchlist_asset_sync(symbol="600000", instrument_type="open_end_fund")
    elif stale_fact == "changed_policy":
        config.market_data_source_policy = FREE_CN_RESEARCH_V1.policy_id
    else:
        _verified_calendar(db, fingerprint="c" * 64)

    service = Mock()
    await execute_daily_market_collection_job(
        store,
        job,
        service,
        request_validator=lambda: _require_current_daily_market_collection_job(
            db, config, job
        ),
    )

    service.run.assert_not_called()
    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.status == "queued"
    assert persisted.error == expected_error
    assert persisted.result_ref is None


@pytest.mark.asyncio
async def test_collection_rechecks_watchlist_before_quality_publication(
    tmp_path,
) -> None:
    db, config, store, job = _claimed_collection(tmp_path)
    published: list[str] = []
    service = Mock()

    def run(_payload, *, before_publish):
        assert db.delete_watchlist_asset_sync("600000")
        before_publish()
        published.append("quality")
        return "quality:sha256:" + "a" * 64

    service.run.side_effect = run
    await execute_daily_market_collection_job(
        store,
        job,
        service,
        request_validator=lambda: _require_current_daily_market_collection_job(
            db, config, job
        ),
    )

    service.run.assert_called_once()
    assert published == []
    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.error == "daily_market_collection_watchlist_stale"
    assert persisted.result_ref is None


@pytest.mark.asyncio
async def test_current_collection_can_publish_quality_evidence(tmp_path) -> None:
    db, config, store, job = _claimed_collection(tmp_path)
    service = Mock()

    def run(_payload, *, before_publish):
        before_publish()
        return "quality:sha256:" + "a" * 64

    service.run.side_effect = run
    await execute_daily_market_collection_job(
        store,
        job,
        service,
        request_validator=lambda: _require_current_daily_market_collection_job(
            db, config, job
        ),
    )

    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.status == "succeeded"
    assert persisted.result_ref == "quality:sha256:" + "a" * 64


@pytest.mark.asyncio
async def test_invalid_queued_collection_payload_has_stable_failure_code(
    tmp_path,
) -> None:
    db, config, store, job = _claimed_collection(tmp_path)
    invalid_job = replace(job, payload={**job.payload, "instrument": {}})
    service = Mock()

    await execute_daily_market_collection_job(
        store,
        invalid_job,
        service,
        request_validator=lambda: _require_current_daily_market_collection_job(
            db, config, invalid_job
        ),
    )

    service.run.assert_not_called()
    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.error == "daily_market_collection_payload_invalid"
    assert persisted.result_ref is None


def test_collection_requires_session_to_have_closed(tmp_path, monkeypatch) -> None:
    db, config, _store, job = _claimed_collection(tmp_path)

    class BeforeClose(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 9, 18, 7, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("server.workers.data_worker.datetime", BeforeClose)
    with pytest.raises(
        DailyMarketCollectionFailure,
        match="daily_market_collection_session_not_closed",
    ):
        _require_current_daily_market_collection_job(db, config, job)
