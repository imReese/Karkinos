import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from server.contracts.jobs import job_time
from server.db import AppDatabase
from server.persistence.jobs import JobIdentityConflictError, SQLiteJobStore


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


@pytest.mark.parametrize("retryable,preserve", [(False, True), (True, 1)])
def test_invalid_deferral_flags_leave_current_lease_and_allowance_unchanged(
    tmp_path, retryable, preserve
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    queued = store.enqueue("verified", {"fixture": "validation"}, now=now)
    job = store.claim("verified", "worker", now=now)
    with pytest.raises(ValueError, match="job_retry_invalid"):
        store.fail(
            job.lease,
            now=now,
            error="unavailable",
            retryable=retryable,
            preserve_retry_allowance=preserve,
        )
    assert store.get(queued.job_id) == job


def test_exact_claim_preserves_legacy_backlog_and_unrelated_leases(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    old = datetime(2026, 9, 5, tzinfo=timezone.utc)
    expired = store.enqueue("calendar", {"scheduled_at": old.isoformat()}, now=old)
    leased = store.claim("calendar", "old-worker", now=old)
    queued = store.enqueue("calendar", {"legacy": True}, now=old)
    now = old + timedelta(hours=1)
    daily = store.enqueue("calendar", {"cadence": "daily"}, now=now)
    other = store.enqueue("other-kind", {"cadence": "daily"}, now=now)

    restarted = SQLiteJobStore(db.path)
    assert (
        restarted.claim("calendar", "new-worker", now=now, job_id=other.job_id) is None
    )
    job = restarted.claim("calendar", "new-worker", now=now, job_id=daily.job_id)
    assert job.job_id == daily.job_id
    assert job.attempt == 1
    assert restarted.get(expired.job_id) == leased
    assert restarted.get(queued.job_id) == queued
    assert restarted.get(other.job_id) == other
    assert (
        restarted.claim("calendar", "second-worker", now=now, job_id=daily.job_id)
        is None
    )


def test_nonretryable_failure_is_terminal_after_restart_without_consuming_attempts(
    tmp_path,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    payload = {"cadence": "daily", "date": "2026-09-05"}
    store = SQLiteJobStore(db.path)
    queued = store.enqueue("calendar", payload, now=now)
    job = store.claim("calendar", "worker", now=now, job_id=queued.job_id)
    store.fail(job.lease, now=now, error="provider_rate_limited", retryable=False)

    restarted = SQLiteJobStore(db.path)
    replay = restarted.enqueue("calendar", payload, now=now + timedelta(days=1))
    assert replay.status == "failed"
    assert replay.attempt == 1
    assert replay.error == "provider_rate_limited"
    assert (
        restarted.claim(
            "calendar", "worker", now=now + timedelta(days=1), job_id=job.job_id
        )
        is None
    )
    with pytest.raises(ValueError, match="job_lease_lost"):
        restarted.finish(job.lease, now=now, result_ref="invalid-success")


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


@pytest.fixture
def unleased_queued_job(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc)
    queued = store.enqueue("verified", {"fixture": "obsolete-range"}, now=now)
    return store, queued, now


def _raw_job(store, job_id):
    with sqlite3.connect(store.path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(
            conn.execute("SELECT * FROM job_runs WHERE job_id=?", (job_id,)).fetchone()
        )


def test_stop_future_queued_retry_preserves_evidence_budget_and_other_jobs(
    unleased_queued_job,
):
    store, queued, now = unleased_queued_job
    claimed = store.claim("verified", "worker", now=now, job_id=queued.job_id)
    store.fail(
        claimed.lease,
        now=now,
        error="market_daily_provider_call_budget_exhausted",
        retry_seconds=86400,
        failure_evidence_ref="capture:sha256:" + "a" * 64,
        preserve_retry_allowance=True,
    )
    other = store.enqueue("verified", {"fixture": "still-needed"}, now=now)
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE job_runs SET result_ref=? WHERE job_id=?",
            ("retained-partial-result", queued.job_id),
        )
        conn.execute(
            "INSERT INTO market_daily_provider_call_reservations "
            "(shanghai_date, upstream_group, job_id, job_attempt, reserved_at) "
            "VALUES (?,?,?,?,?)",
            ("2026-10-23", "tushare", queued.job_id, claimed.attempt, job_time(now)),
        )
        reservations = conn.execute(
            "SELECT * FROM market_daily_provider_call_reservations"
        ).fetchall()
    before = _raw_job(store, queued.job_id)
    unrelated = _raw_job(store, other.job_id)
    stopped_at = now + timedelta(seconds=1)
    stopped = store.stop_queued(
        queued.job_id,
        expected_input_fingerprint=queued.input_fingerprint,
        now=stopped_at,
        reason=" obsolete_short_range ",
    )
    assert stopped.status == "failed"
    assert stopped.error == "operator_stopped_queued_retry:obsolete_short_range"
    after = _raw_job(store, queued.job_id)
    assert after == {
        **before,
        "status": "failed",
        "error": stopped.error,
        "updated_at": job_time(stopped_at),
    }
    assert after["available_at"] > job_time(stopped_at)
    assert after["attempt"] == 1 and after["max_attempts"] == 4
    assert _raw_job(store, other.job_id) == unrelated
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT * FROM market_daily_provider_call_reservations"
            ).fetchall()
            == reservations
        )
    restarted = SQLiteJobStore(store.path)
    later = now + timedelta(days=2)
    assert (
        restarted.claim("verified", "worker", now=later, job_id=queued.job_id) is None
    )
    assert (
        restarted.claim("verified", "worker", now=later, job_id=other.job_id).job_id
        == other.job_id
    )


@pytest.mark.parametrize(
    "state", ["running", "expired_running", "queued_owner", "queued_expiry"]
)
def test_stop_queued_refuses_every_lease_even_if_expired(unleased_queued_job, state):
    store, queued, now = unleased_queued_job
    if state in {"running", "expired_running"}:
        store.claim("verified", "worker", now=now, job_id=queued.job_id)
    else:
        column, value = (
            ("lease_owner", "worker")
            if state == "queued_owner"
            else ("lease_expires_at", job_time(now - timedelta(seconds=1)))
        )
        with sqlite3.connect(store.path) as conn:
            conn.execute(
                f"UPDATE job_runs SET {column}=? WHERE job_id=?", (value, queued.job_id)
            )
    before = _raw_job(store, queued.job_id)
    with pytest.raises(ValueError, match="job_not_unleased_queued"):
        store.stop_queued(
            queued.job_id,
            expected_input_fingerprint=queued.input_fingerprint,
            now=now + timedelta(seconds=61 if state == "expired_running" else 1),
            reason="obsolete_short_range",
        )
    assert _raw_job(store, queued.job_id) == before


@pytest.mark.parametrize("terminal", ["failed", "succeeded"])
def test_stop_queued_terminal_is_idempotent_after_identity_check(
    unleased_queued_job, terminal
):
    store, queued, now = unleased_queued_job
    claimed = store.claim("verified", "worker", now=now, job_id=queued.job_id)
    if terminal == "failed":
        store.fail(claimed.lease, now=now, error="original_failure", retryable=False)
    else:
        store.finish(claimed.lease, now=now, result_ref="original_result")
    before = _raw_job(store, queued.job_id)
    returned = store.stop_queued(
        queued.job_id,
        expected_input_fingerprint=queued.input_fingerprint,
        now=now + timedelta(days=1),
        reason="obsolete_short_range",
    )
    assert returned == store.get(queued.job_id)
    assert _raw_job(store, queued.job_id) == before
    with pytest.raises(JobIdentityConflictError, match="job_identity_conflict"):
        store.stop_queued(
            queued.job_id,
            expected_input_fingerprint="f" * 64,
            now=now + timedelta(days=1),
            reason="obsolete_short_range",
        )
    assert _raw_job(store, queued.job_id) == before


@pytest.mark.parametrize(
    "drift",
    [
        "expected_fingerprint",
        "payload",
        "fingerprint",
        "kind",
        "invalid_json",
        "nonobject_payload",
        "invalid_kind",
    ],
)
def test_stop_queued_rejects_wrong_or_corrupt_identity(unleased_queued_job, drift):
    store, queued, now = unleased_queued_job
    job_id, fingerprint = queued.job_id, queued.input_fingerprint
    with sqlite3.connect(store.path) as conn:
        if drift == "payload":
            conn.execute(
                "UPDATE job_runs SET payload_json='{}' WHERE job_id=?", (job_id,)
            )
        elif drift == "fingerprint":
            conn.execute(
                "UPDATE job_runs SET input_fingerprint=? WHERE job_id=?",
                ("f" * 64, job_id),
            )
        elif drift == "kind":
            conn.execute("UPDATE job_runs SET kind='other' WHERE job_id=?", (job_id,))
        elif drift in {"invalid_json", "nonobject_payload", "invalid_kind"}:
            encoded = {
                "invalid_json": "{",
                "nonobject_payload": "[]",
                "invalid_kind": json.dumps(queued.payload),
            }[drift]
            kind = "" if drift == "invalid_kind" else queued.kind
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            replacement_id = hashlib.sha256(
                f"{kind}:{fingerprint}".encode()
            ).hexdigest()
            conn.execute(
                "UPDATE job_runs SET job_id=?, kind=?, payload_json=?, input_fingerprint=? WHERE job_id=?",
                (replacement_id, kind, encoded, fingerprint, job_id),
            )
            job_id = replacement_id
    before = _raw_job(store, job_id)
    with pytest.raises(JobIdentityConflictError, match="job_identity_conflict"):
        store.stop_queued(
            job_id,
            expected_input_fingerprint="f" * 64
            if drift == "expected_fingerprint"
            else fingerprint,
            now=now,
            reason="obsolete_short_range",
        )
    assert _raw_job(store, job_id) == before


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("job_id", "short", "job_id_invalid"),
        ("job_id", "A" * 64, "job_id_invalid"),
        ("expected_input_fingerprint", "short", "job_input_fingerprint_invalid"),
        ("expected_input_fingerprint", "A" * 64, "job_input_fingerprint_invalid"),
        ("now", datetime(2026, 10, 23), "job clock must include a timezone"),
        ("reason", " ", "job_stop_reason_invalid"),
        ("reason", None, "job_stop_reason_invalid"),
    ],
)
def test_stop_queued_invalid_arguments_do_not_mutate(
    unleased_queued_job, field, value, error
):
    store, queued, now = unleased_queued_job
    arguments = {
        "job_id": queued.job_id,
        "expected_input_fingerprint": queued.input_fingerprint,
        "now": now,
        "reason": "obsolete_short_range",
    }
    arguments[field] = value
    before = _raw_job(store, queued.job_id)
    with pytest.raises(ValueError, match=error):
        store.stop_queued(**arguments)
    assert _raw_job(store, queued.job_id) == before


def test_stop_queued_missing_identity_does_not_stop_another_job(unleased_queued_job):
    store, queued, now = unleased_queued_job
    before = _raw_job(store, queued.job_id)
    assert (
        store.stop_queued(
            "0" * 64,
            expected_input_fingerprint=queued.input_fingerprint,
            now=now,
            reason="obsolete_short_range",
        )
        is None
    )
    assert _raw_job(store, queued.job_id) == before


def test_stop_queued_serializes_with_worker_claim(unleased_queued_job, monkeypatch):
    store, queued, now = unleased_queued_job
    worker = SQLiteJobStore(store.path)
    entered, release = Event(), Event()
    transaction = store._transaction

    @contextmanager
    def paused_transaction():
        with transaction() as conn:
            entered.set()
            assert release.wait(2)
            yield conn

    monkeypatch.setattr(store, "_transaction", paused_transaction)
    with ThreadPoolExecutor(max_workers=2) as executor:
        stopped = executor.submit(
            store.stop_queued,
            queued.job_id,
            expected_input_fingerprint=queued.input_fingerprint,
            now=now,
            reason="obsolete_short_range",
        )
        assert entered.wait(2)
        claimed = executor.submit(
            worker.claim, "verified", "worker", now=now, job_id=queued.job_id
        )
        try:
            assert not claimed.done()
        finally:
            release.set()
        assert stopped.result(timeout=3).status == "failed"
        assert claimed.result(timeout=3) is None
