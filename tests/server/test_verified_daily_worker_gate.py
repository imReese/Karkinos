"""A queued verified job must retain current authority through publication."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.types import InstrumentKey, InstrumentType
from data.source_policy import CN_RESEARCH_V1, FREE_CN_RESEARCH_V1
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.verified_daily_market_data import VerifiedDailyMarketJobRequest
from server.services.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB
from server.workers.data_worker import (
    VerifiedDailyMarketJobNotCurrent,
    _require_current_verified_daily_market_job,
    execute_verified_daily_market_job,
)

DAY = date(2025, 9, 18)


def _calendar(year: int = DAY.year, trading_day: date = DAY) -> dict:
    days = []
    day = date(year, 1, 1)
    while day.year == year:
        days.append({"date": day.isoformat(), "is_trading_day": day == trading_day})
        day += timedelta(days=1)
    return {
        "year": year,
        "exchange": "SSE",
        "days": days,
        "trading_day_count": 1,
        "closed_day_count": len(days) - 1,
        "source_fingerprint": "a" * 64,
        "verification_source_fingerprint": "a" * 64,
        "official_source_fingerprint": "b" * 64,
        "official_source_url": "https://example.test/calendar",
        "official_verified_at": "2025-09-19T08:00:00Z",
        "official_verified_by": "fixture",
        "official_verification_status": "verified",
    }


def _job(tmp_path, *, policy_id: str = FREE_CN_RESEARCH_V1.policy_id):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    row = _calendar()
    evidence_ref = validate_verified_market_calendar(row).evidence_ref
    assert evidence_ref is not None
    payload = VerifiedDailyMarketJobRequest(
        trade_date=DAY,
        instruments=(InstrumentKey("600000", InstrumentType.STOCK),),
        source_policy_id=policy_id,
        calendar_evidence_refs=(evidence_ref,),
    ).to_payload()
    now = datetime.now(timezone.utc)
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)
    assert job is not None
    calendar_db = SimpleNamespace(
        get_market_calendar_snapshot_sync=lambda *, exchange, year: (
            row if exchange == "SSE" and year == DAY.year else None
        )
    )
    config = SimpleNamespace(
        market_data_source_policy=CN_RESEARCH_V1.policy_id,
        market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id,
    )
    return store, job, calendar_db, config, row


def _invalidate(config, row: dict, kind: str) -> None:
    if kind == "policy":
        config.market_data_verification_source_policy = CN_RESEARCH_V1.policy_id
    else:
        row["official_source_fingerprint"] = "c" * 64


def test_legacy_cross_year_job_requires_each_current_calendar_ref(tmp_path) -> None:
    _store, job, _calendar_db, config, day_row = _job(tmp_path)
    following_row = _calendar(DAY.year + 1, date(DAY.year + 1, 1, 2))
    following_ref = validate_verified_market_calendar(following_row).evidence_ref
    assert following_ref is not None
    calendar_db = SimpleNamespace(
        get_market_calendar_snapshot_sync=lambda *, exchange, year: (
            day_row if year == DAY.year else following_row
        )
    )
    legacy = replace(
        job,
        payload={
            **job.payload,
            "calendar_evidence_refs": [
                following_ref,
                *job.payload["calendar_evidence_refs"],
            ],
        },
    )
    _require_current_verified_daily_market_job(calendar_db, config, legacy)

    following_row["official_source_fingerprint"] = "c" * 64
    with pytest.raises(
        VerifiedDailyMarketJobNotCurrent,
        match="verified_daily_market_calendar_evidence_stale",
    ):
        _require_current_verified_daily_market_job(calendar_db, config, legacy)


def test_extra_following_year_ref_is_not_accepted_for_nonfinal_session(
    tmp_path,
) -> None:
    _store, job, _calendar_db, config, day_row = _job(tmp_path)
    later = date(DAY.year, 12, 31).isoformat()
    next(item for item in day_row["days"] if item["date"] == later)[
        "is_trading_day"
    ] = True
    day_row["trading_day_count"] += 1
    day_row["closed_day_count"] -= 1
    current_ref = validate_verified_market_calendar(day_row).evidence_ref
    following_row = _calendar(DAY.year + 1, date(DAY.year + 1, 1, 2))
    following_ref = validate_verified_market_calendar(following_row).evidence_ref
    assert current_ref is not None and following_ref is not None
    calendar_db = SimpleNamespace(
        get_market_calendar_snapshot_sync=lambda *, exchange, year: (
            day_row if year == DAY.year else following_row
        )
    )
    extra_ref_job = replace(
        job,
        payload={
            **job.payload,
            "calendar_evidence_refs": [following_ref, current_ref],
        },
    )
    with pytest.raises(
        VerifiedDailyMarketJobNotCurrent,
        match="verified_daily_market_calendar_evidence_stale",
    ):
        _require_current_verified_daily_market_job(calendar_db, config, extra_ref_job)


def test_collection_policy_change_does_not_stale_explicit_verification(
    tmp_path,
) -> None:
    _store, job, calendar_db, config, _row = _job(tmp_path)
    config.market_data_source_policy = FREE_CN_RESEARCH_V1.policy_id
    _require_current_verified_daily_market_job(calendar_db, config, job)


def _range_job(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    row = _calendar()
    sessions = (DAY, date(2025, 9, 19), date(2025, 9, 22))
    for item in row["days"]:
        item["is_trading_day"] = date.fromisoformat(item["date"]) in sessions
    row["trading_day_count"] = len(sessions)
    row["closed_day_count"] = len(row["days"]) - len(sessions)
    row = db.upsert_market_calendar_snapshot_sync(row)
    row = db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=DAY.year,
        source_fingerprint=row["source_fingerprint"],
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )
    ref = validate_verified_market_calendar(row).evidence_ref
    assert ref is not None
    instruments = (InstrumentKey("600000", InstrumentType.STOCK),)
    request = VerifiedDailyMarketJobRequest(
        sessions[-1],
        instruments,
        FREE_CN_RESEARCH_V1.policy_id,
        (ref,),
        range_start_date=sessions[0],
        range_end_date=sessions[-1],
        session_memberships=tuple(
            (day, () if index == 1 else instruments, (ref,))
            for index, day in enumerate(sessions)
        ),
    )
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, request.to_payload(), now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)
    assert job is not None
    config = SimpleNamespace(
        market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id
    )
    return db, store, job, config


def test_range_worker_requires_every_closed_session_even_for_empty_membership(tmp_path):
    db, _store, job, config = _range_job(tmp_path)
    _require_current_verified_daily_market_job(db, config, job)
    omitted = replace(
        job,
        payload={
            **job.payload,
            "session_memberships": [
                job.payload["session_memberships"][0],
                job.payload["session_memberships"][-1],
            ],
        },
    )
    with pytest.raises(
        VerifiedDailyMarketJobNotCurrent,
        match="verified_daily_market_range_calendar_mismatch",
    ):
        _require_current_verified_daily_market_job(db, config, omitted)


def test_range_worker_rejects_unclosed_tail_before_io(tmp_path, monkeypatch):
    db, _store, job, config = _range_job(tmp_path)
    monkeypatch.setattr(
        "server.workers.data_worker.datetime",
        SimpleNamespace(now=lambda tz: datetime(2025, 9, 19, 8, tzinfo=timezone.utc)),
    )
    with pytest.raises(
        VerifiedDailyMarketJobNotCurrent,
        match="verified_daily_market_(range_calendar_mismatch|session_not_closed)",
    ):
        _require_current_verified_daily_market_job(db, config, job)


@pytest.mark.asyncio
async def test_range_worker_rechecks_calendar_before_each_provider_entry(tmp_path):
    db, store, job, config = _range_job(tmp_path)
    calls = []

    class Service:
        def run(self, payload, *, before_publish, before_provider_fetch):
            before_provider_fetch(None)
            calls.append("primary")
            row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=DAY.year)
            db.update_market_calendar_verification_sync(
                exchange="SSE",
                year=DAY.year,
                source_fingerprint=row["source_fingerprint"],
                verification_status="verified",
                official_source_url="https://example.test/revised-calendar",
                official_source_fingerprint="c" * 64,
                verified_by="fixture",
            )
            before_provider_fetch(None)
            calls.append("comparison")
            before_publish()
            return "dataset:sha256:" + "a" * 64

    await execute_verified_daily_market_job(
        store,
        job,
        Service(),
        request_validator=lambda: _require_current_verified_daily_market_job(
            db, config, job
        ),
        before_provider_fetch=lambda _: _require_current_verified_daily_market_job(
            db, config, job
        ),
    )
    assert calls == ["primary"]
    assert store.get(job.job_id).result_ref is None
    assert store.get(job.job_id).status == "queued"


@pytest.mark.asyncio
async def test_queued_cn_verification_is_stale_before_provider_io(tmp_path) -> None:
    store, job, calendar_db, config, _row = _job(
        tmp_path, policy_id=CN_RESEARCH_V1.policy_id
    )
    service = Mock()

    await execute_verified_daily_market_job(
        store,
        job,
        service,
        request_validator=lambda: _require_current_verified_daily_market_job(
            calendar_db, config, job
        ),
    )

    service.run.assert_not_called()
    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.error == "VerifiedDailyMarketJobNotCurrent"
    assert persisted.result_ref is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_fact", ["policy", "calendar"])
async def test_stale_queued_verification_never_calls_provider(
    tmp_path, stale_fact: str
) -> None:
    store, job, calendar_db, config, row = _job(tmp_path)
    _invalidate(config, row, stale_fact)
    service = Mock()

    await execute_verified_daily_market_job(
        store,
        job,
        service,
        request_validator=lambda: _require_current_verified_daily_market_job(
            calendar_db, config, job
        ),
    )

    service.run.assert_not_called()
    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.status == "queued"
    assert persisted.result_ref is None
    assert persisted.error == "VerifiedDailyMarketJobNotCurrent"


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_fact", ["policy", "calendar"])
async def test_verification_that_becomes_stale_after_capture_cannot_publish(
    tmp_path, stale_fact: str
) -> None:
    store, job, calendar_db, config, row = _job(tmp_path)
    published: list[str] = []
    service = Mock()

    def run(_payload, *, before_publish):
        _invalidate(config, row, stale_fact)
        before_publish()
        published.append("dataset")
        return "dataset:sha256:" + "a" * 64

    service.run.side_effect = run
    await execute_verified_daily_market_job(
        store,
        job,
        service,
        request_validator=lambda: _require_current_verified_daily_market_job(
            calendar_db, config, job
        ),
    )

    service.run.assert_called_once()
    assert published == []
    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.status == "queued"
    assert persisted.result_ref is None
    assert persisted.error == "VerifiedDailyMarketJobNotCurrent"
