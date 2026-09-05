from datetime import datetime, timedelta, timezone

import pytest

from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore


def test_claim_takeover_fences_old_worker_and_replays_result(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    second = SQLiteJobStore(db.path)
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    queued = store.enqueue("calendar", {"year": 2026}, now=now)
    assert second.enqueue("calendar", {"year": 2026}, now=now) == queued
    first = store.claim("calendar", "first", now=now)
    assert first.attempt == 1
    assert second.claim("calendar", "second", now=now) is None
    later = now + timedelta(seconds=61)
    takeover = second.claim("calendar", "second", now=later)
    assert takeover.attempt == 2
    with pytest.raises(ValueError, match="job_lease_lost"):
        store.finish(first.lease, now=later, result_ref="stale")
    with pytest.raises(ValueError, match="job_lease_lost"):
        store.heartbeat(first.lease, now=later)
    second.finish(takeover.lease, now=later, result_ref="calendar:2026")
    assert store.claim("calendar", "third", now=later) is None
    replay = store.enqueue("calendar", {"year": 2026}, now=later)
    assert replay.status == "succeeded"
    assert replay.result_ref == "calendar:2026"


def test_retry_backoff_and_attempt_budget_survive_restart(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    store = SQLiteJobStore(db.path)
    store.enqueue("calendar", {"year": 2026}, now=now)
    for attempt in range(1, 4):
        job = store.claim("calendar", "worker", now=now)
        assert job.attempt == attempt
        store.fail(job.lease, now=now, error="timeout", retry_seconds=60)
        store = SQLiteJobStore(db.path)
        assert store.claim("calendar", "worker", now=now) is None
        now += timedelta(seconds=60)
    assert store.claim("calendar", "worker", now=now) is None
    assert store.enqueue("calendar", {"year": 2026}, now=now).status == "failed"
