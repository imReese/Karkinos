"""Managed daily-bar calls share a restart-safe, lease-fenced upstream budget."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.providers.tencent import (
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
    TENCENT_DAILY_BAR_DESCRIPTOR,
)
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_daily_call_budget import (
    BUDGET_DEFERRED_CODE,
    MarketDailyProviderBudgetDeferred,
    market_daily_provider_call_budget_status,
    reserve_market_daily_provider_call,
)

NOW = datetime(2026, 9, 18, 8, 10, tzinfo=timezone.utc)
NEXT_SHANGHAI_DAY = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)


def _store(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    return SQLiteJobStore(db.path)


def _claimed(store, index: int):
    payload = {"instrument": f"fixture-{index}"}
    store.enqueue("market_daily_collection", payload, now=NOW)
    job = store.claim("market_daily_collection", f"worker-{index}", now=NOW)
    assert job is not None
    return job


def test_budget_deferral_is_atomic_and_preserves_failure_allowance(tmp_path):
    store = _store(tmp_path)
    job = _claimed(store, 1)
    second_connection = SQLiteJobStore(store.path)

    for _ in range(2):
        reserve_market_daily_provider_call(
            second_connection.path,
            job.lease,
            BAOSTOCK_DAILY_BAR_DESCRIPTOR,
            now=NOW,
            daily_limit=2,
        )
    with pytest.raises(MarketDailyProviderBudgetDeferred) as exc_info:
        reserve_market_daily_provider_call(
            store.path,
            job.lease,
            BAOSTOCK_DAILY_BAR_DESCRIPTOR,
            now=NOW,
            daily_limit=2,
        )
    assert exc_info.value.available_at == NEXT_SHANGHAI_DAY

    status = market_daily_provider_call_budget_status(
        store.path, now=NOW, daily_limit=2
    )
    assert status["scope"] == "managed_daily_market_jobs"
    assert status["groups"]["baostock"] == {
        "used": 2,
        "limit": 2,
        "remaining": 0,
    }
    assert status["groups"]["tencent"]["used"] == 0
    persisted = store.get(job.job_id)
    assert persisted is not None
    assert persisted.status == "queued"
    assert persisted.attempt == 1
    assert persisted.error == BUDGET_DEFERRED_CODE
    with sqlite3.connect(store.path) as conn:
        max_attempts = conn.execute(
            "SELECT max_attempts FROM job_runs WHERE job_id=?", (job.job_id,)
        ).fetchone()[0]
    assert max_attempts == 4

    with pytest.raises(ValueError, match="job_lease_lost"):
        reserve_market_daily_provider_call(
            store.path,
            job.lease,
            BAOSTOCK_DAILY_BAR_DESCRIPTOR,
            now=NOW,
            daily_limit=2,
        )
    reclaimed = store.claim(
        "market_daily_collection", "worker-1", now=NEXT_SHANGHAI_DAY
    )
    assert reclaimed is not None and reclaimed.attempt == 2
    reserve_market_daily_provider_call(
        store.path,
        reclaimed.lease,
        BAOSTOCK_DAILY_BAR_DESCRIPTOR,
        now=NEXT_SHANGHAI_DAY,
        daily_limit=2,
    )
    assert (
        market_daily_provider_call_budget_status(
            store.path, now=NEXT_SHANGHAI_DAY, daily_limit=2
        )["groups"]["baostock"]["used"]
        == 1
    )
    for expected_attempt in (2, 3, 4):
        store.fail(
            reclaimed.lease,
            now=NEXT_SHANGHAI_DAY,
            error="provider_failed",
            retry_seconds=0,
        )
        if expected_attempt < 4:
            reclaimed = store.claim(
                "market_daily_collection", "worker-1", now=NEXT_SHANGHAI_DAY
            )
            assert reclaimed is not None and reclaimed.attempt == expected_attempt + 1
    assert store.get(job.job_id).status == "failed"


def test_budget_reservations_are_atomic_across_workers(tmp_path):
    store = _store(tmp_path)
    jobs = [_claimed(store, index) for index in range(8)]

    def reserve(job):
        try:
            reserve_market_daily_provider_call(
                store.path,
                job.lease,
                BAOSTOCK_DAILY_BAR_DESCRIPTOR,
                now=NOW,
                daily_limit=3,
            )
            return "reserved"
        except MarketDailyProviderBudgetDeferred:
            return "deferred"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, jobs))
    assert outcomes.count("reserved") == 3
    assert outcomes.count("deferred") == 5
    assert (
        market_daily_provider_call_budget_status(store.path, now=NOW, daily_limit=3)[
            "groups"
        ]["baostock"]["used"]
        == 3
    )


def test_automatic_and_explicit_jobs_share_actual_upstream_group(tmp_path):
    store = _store(tmp_path)
    collected = _claimed(store, 1)
    store.enqueue("market_daily_verified", {"fixture": "verified"}, now=NOW)
    verified = store.claim("market_daily_verified", "verified-worker", now=NOW)
    assert verified is not None

    reserve_market_daily_provider_call(
        store.path,
        collected.lease,
        TENCENT_DAILY_BAR_DESCRIPTOR,
        now=NOW,
        daily_limit=1,
    )
    with pytest.raises(MarketDailyProviderBudgetDeferred):
        reserve_market_daily_provider_call(
            store.path,
            verified.lease,
            AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
            now=NOW,
            daily_limit=1,
        )
    status = market_daily_provider_call_budget_status(
        store.path, now=NOW, daily_limit=1
    )
    assert status["groups"]["tencent"]["used"] == 1
    assert store.get(verified.job_id).status == "queued"


def test_unknown_upstream_and_unreadable_budget_fail_closed(tmp_path):
    store = _store(tmp_path)
    job = _claimed(store, 1)
    with pytest.raises(ValueError, match="upstream_unreviewed"):
        reserve_market_daily_provider_call(
            store.path,
            job.lease,
            replace(BAOSTOCK_DAILY_BAR_DESCRIPTOR, upstream_group="unknown"),
            now=NOW,
        )
    assert store.get(job.job_id).status == "running"
    with pytest.raises(OSError, match="budget_unreadable"):
        market_daily_provider_call_budget_status(tmp_path / "missing.db", now=NOW)
