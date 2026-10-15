"""Actual SQLite reservations must meet every opening, not just a weekly sum."""

import sqlite3
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core.types import InstrumentKey, InstrumentType
from data.providers.eastmoney import AKSHARE_DAILY_BAR_DESCRIPTOR
from data.providers.tushare import TUSHARE_DAILY_BAR_DESCRIPTOR
from data.source_policy import CN_RESEARCH_V1
from server.persistence.market_daily_call_budget import (
    MarketDailyProviderBudgetDeferred,
    market_daily_provider_call_budget_status,
    reserve_market_daily_provider_call,
)
from server.services.research_corporate_action_jobs import CORPORATE_ACTION_DAY_JOB
from server.services.verified_daily_market_data import VerifiedDailyMarketJobRequest
from server.services.verified_daily_market_jobs import (
    VERIFIED_DAILY_MARKET_JOB,
    enqueue_verified_daily_market_jobs_for_range,
)
from tests.server.test_verified_daily_market_jobs import _calendar, _store

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize("instrument_count", [5000, 10_000])
def test_two_weeks_of_full_scope_and_dividends_meet_each_next_opening(
    tmp_path, instrument_count
):
    """No provider latency is modeled; this protects the real quota boundary."""
    store = _store(tmp_path)
    monday = date(2026, 9, 7)
    trading_days = {
        monday + timedelta(days=index)
        for index in range(15)
        if (monday + timedelta(days=index)).weekday() < 5
    }
    calendar = _calendar(trading_dates=trading_days)
    calendar["official_verified_at"] = "2026-09-01T00:00:00Z"
    db = SimpleNamespace(get_market_calendar_snapshot_sync=lambda **_kwargs: calendar)
    config = SimpleNamespace(
        market_data_verification_source_policy=CN_RESEARCH_V1.policy_id
    )
    instruments = tuple(
        InstrumentKey(str(600000 + index), InstrumentType.STOCK)
        for index in range(instrument_count)
    )
    descriptors = (TUSHARE_DAILY_BAR_DESCRIPTOR, AKSHARE_DAILY_BAR_DESCRIPTOR)
    bars = {}
    action_jobs = {}
    pending = {CORPORATE_ACTION_DAY_JOB: [], VERIFIED_DAILY_MARKET_JOB: []}
    deferred_count = 0

    def drain(now):
        nonlocal deferred_count
        # Same priority as the actual worker: already queued CA before bars.
        for kind in (CORPORATE_ACTION_DAY_JOB, VERIFIED_DAILY_MARKET_JOB):
            for identity in tuple(pending[kind]):
                job = store.claim(kind, "capacity-fixture", now=now, job_id=identity)
                if job is None:
                    continue
                try:
                    attempts = (
                        (TUSHARE_DAILY_BAR_DESCRIPTOR,) * 4
                        if kind == CORPORATE_ACTION_DAY_JOB
                        else descriptors
                    )
                    for descriptor in attempts:
                        # Intentionally use the production default, never an
                        # increased or fake test quota. Failures/retries also cost.
                        reserve_market_daily_provider_call(
                            store.path, job.lease, descriptor, now=now
                        )
                except MarketDailyProviderBudgetDeferred:
                    deferred_count += 1
                    break
                store.finish(job.lease, now=now, result_ref="fixture:reserved")
                pending[kind].remove(identity)
        status = market_daily_provider_call_budget_status(store.path, now=now)
        assert all(
            group["limit"] == 100 and group["used"] <= 100
            for group in status["groups"].values()
        )

    for offset in range(15):
        day = monday + timedelta(days=offset)
        midnight = datetime.combine(day, time.min, SHANGHAI)
        drain(midnight)
        if day in trading_days and offset:
            # Every earlier trading session, including Friday after a weekend,
            # and every due calendar-date dividend job must precede 09:30.
            before_open = datetime.combine(day, time(9, 29, 59), SHANGHAI)
            drain(before_open)
            with sqlite3.connect(store.path) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM job_runs WHERE kind IN (?,?) "
                        "AND status != 'succeeded'",
                        (VERIFIED_DAILY_MARKET_JOB, CORPORATE_ACTION_DAY_JOB),
                    ).fetchone()[0]
                    == 0
                )
        if offset == 14:
            break
        if day in trading_days:
            after_close = datetime.combine(day, time(16, 10), SHANGHAI)
            jobs = enqueue_verified_daily_market_jobs_for_range(
                db,
                config,
                store,
                instruments=instruments,
                start_date=day,
                end_date=day,
                now=after_close,
            )
            assert len(jobs) == (instrument_count + 99) // 100
            requests = [
                VerifiedDailyMarketJobRequest.from_payload(job.payload) for job in jobs
            ]
            assert all(
                not request.is_range and len(request.instruments) == 100
                for request in requests
            )
            assert (
                tuple(key for request in requests for key in request.instruments)
                == instruments
            )
            bars[day] = tuple(job.job_id for job in jobs)
            pending[VERIFIED_DAILY_MARKET_JOB].extend(bars[day])
            drain(after_close)
        # The provider's daily window is ready only after 21:00. The four
        # reservations are on the same upstream used by every stock shard.
        after_update = datetime.combine(day, time(21), SHANGHAI)
        action = store.enqueue(
            CORPORATE_ACTION_DAY_JOB, {"date": day.isoformat()}, now=after_update
        )
        action_jobs[day] = action.job_id
        pending[CORPORATE_ACTION_DAY_JOB].append(action.job_id)
        drain(after_update)
        if day.weekday() >= 5:
            # Non-trading-day spare capacity may be spent by background work;
            # it is not silently banked for the next trading week.
            background = store.enqueue(
                "capacity_background", {"date": day.isoformat()}, now=after_update
            )
            leased = store.claim(
                "capacity_background",
                "capacity-fixture",
                now=after_update,
                job_id=background.job_id,
            )
            assert leased is not None
            while True:
                try:
                    reserve_market_daily_provider_call(
                        store.path,
                        leased.lease,
                        TUSHARE_DAILY_BAR_DESCRIPTOR,
                        now=after_update,
                    )
                except MarketDailyProviderBudgetDeferred:
                    break
    assert len(bars) == 10 and len(action_jobs) == 14
    assert deferred_count > 0 if instrument_count == 10_000 else deferred_count == 0
