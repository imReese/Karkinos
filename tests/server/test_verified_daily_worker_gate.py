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


def _job(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    row = _calendar()
    evidence_ref = validate_verified_market_calendar(row).evidence_ref
    assert evidence_ref is not None
    payload = VerifiedDailyMarketJobRequest(
        trade_date=DAY,
        instruments=(InstrumentKey("600000", InstrumentType.STOCK),),
        source_policy_id=FREE_CN_RESEARCH_V1.policy_id,
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
    config = SimpleNamespace(market_data_source_policy=FREE_CN_RESEARCH_V1.policy_id)
    return store, job, calendar_db, config, row


def _invalidate(config, row: dict, kind: str) -> None:
    if kind == "policy":
        config.market_data_source_policy = CN_RESEARCH_V1.policy_id
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
