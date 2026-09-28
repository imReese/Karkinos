import json
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
        store.fail(
            job.lease,
            now=now,
            error="timeout",
            retry_seconds=60,
            failure_evidence_ref=(
                "capture:sha256:" + "a" * 64 if attempt == 1 else None
            ),
        )
        store = SQLiteJobStore(db.path)
        assert (
            store.enqueue("calendar", {"year": 2026}, now=now).failure_evidence_ref
            == "capture:sha256:" + "a" * 64
        )
        assert store.claim("calendar", "worker", now=now) is None
        now += timedelta(seconds=60)
    assert store.claim("calendar", "worker", now=now) is None
    assert store.enqueue("calendar", {"year": 2026}, now=now).status == "failed"


def test_list_recent_reads_only_requested_kind_in_update_order(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    first = store.enqueue("market_daily_collection", {"symbol": "600000"}, now=now)
    second = store.enqueue("market_daily_collection", {"symbol": "000001"}, now=now)
    store.enqueue("market_daily_verified", {"symbol": "300001"}, now=now)

    tied = store.list_recent("market_daily_collection")
    assert [row["job_id"] for row in tied] == sorted(
        (first.job_id, second.job_id), reverse=True
    )

    claimed = store.claim("market_daily_collection", "worker", now=now)
    assert claimed is not None
    store.finish(
        claimed.lease,
        now=now + timedelta(seconds=1),
        result_ref="quality:sha256:" + "a" * 64,
    )
    rows = store.list_recent("market_daily_collection")
    assert [row["job_id"] for row in rows] == [
        claimed.job_id,
        second.job_id if claimed.job_id == first.job_id else first.job_id,
    ]
    assert set(rows[0]) == {
        "job_id",
        "kind",
        "payload_json",
        "status",
        "attempt",
        "result_ref",
        "error",
        "failure_evidence_ref",
        "created_at",
        "updated_at",
    }
    assert all(row["kind"] == "market_daily_collection" for row in rows)
    assert json.loads(rows[0]["payload_json"]) == claimed.payload
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["attempt"] == 1
    assert rows[0]["result_ref"] == "quality:sha256:" + "a" * 64
    assert rows[0]["error"] is None
    assert rows[0]["updated_at"] > rows[0]["created_at"]
    assert [
        row["job_id"] for row in store.list_recent("market_daily_collection", limit=1)
    ] == [claimed.job_id]


@pytest.mark.parametrize(
    "kind,limit",
    [("", 1), (" ", 1), ("calendar", 0), ("calendar", 101), ("calendar", True)],
)
def test_list_recent_rejects_invalid_query(tmp_path, kind, limit):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    with pytest.raises(ValueError, match="job_kind_invalid|job_limit_invalid"):
        store.list_recent(kind, limit=limit)
