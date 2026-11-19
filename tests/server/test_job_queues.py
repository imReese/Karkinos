"""Queue controls isolate scheduling without rewriting execution history."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest

from server.db import AppDatabase
from server.persistence.jobs import JobQueuePaused, SQLiteJobStore
from server.workers.data_worker import execute_verified_daily_market_job

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]
QUEUE = "bk_recovery"


@pytest.fixture
def store(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    return SQLiteJobStore(db.path)


def change(store, paused, revision, jobs=()):
    return store.set_queue_paused(
        QUEUE,
        paused=paused,
        expected_revision=revision,
        now=NOW,
        actor="operator",
        reason="Bounded recovery control",
        job_ids=jobs,
    )


def raw(store, identity):
    with sqlite3.connect(store.path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(
            conn.execute(
                "SELECT * FROM job_runs WHERE job_id=?", (identity,)
            ).fetchone()
        )


def test_pause_and_resume_survive_process_restart_without_reviving_terminal_jobs(store):
    failed = store.enqueue("market_daily_verified", {"case": "old-failure"}, now=NOW)
    claimed = store.claim(failed.kind, "first", now=NOW)
    store.fail(
        claimed.lease,
        now=NOW,
        error="quality_conflict",
        retryable=False,
        failure_evidence_ref="quality:original",
    )
    old = raw(store, failed.job_id)
    waiting = store.enqueue(failed.kind, {"case": "waiting"}, now=NOW)
    ordinary = store.enqueue(failed.kind, {"case": "ordinary"}, now=NOW)
    change(store, True, 0, (failed.job_id, waiting.job_id))
    parent = store.get(failed.job_id)
    recovery = store.enqueue(
        failed.kind, {"case": "new-recovery"}, now=NOW, queue_name=parent.queue_name
    )
    later = NOW + timedelta(days=1)
    program = """
import json, sys
from datetime import datetime
from server.persistence.jobs import SQLiteJobStore
store = SQLiteJobStore(sys.argv[1])
now = datetime.fromisoformat(sys.argv[2])
assert store.claim('market_daily_verified', 'restart', now=now, job_id=sys.argv[3]) is None
assert store.claim('market_daily_verified', 'restart', now=now, job_id=sys.argv[4]) is None
job = store.claim('market_daily_verified', 'restart', now=now)
store.finish(job.lease, now=now, result_ref='test:ordinary-task')
print(json.dumps({'job_id': job.job_id, 'queue': store.queue_status('bk_recovery')}))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(store.path),
            later.isoformat(),
            waiting.job_id,
            recovery.job_id,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    state = json.loads(result.stdout)
    assert state["job_id"] == ordinary.job_id
    assert state["queue"]["paused"] is True
    assert all(
        store.get(identity).attempt == 0
        for identity in (waiting.job_id, recovery.job_id)
    )
    change(store, False, 1)
    restarted = SQLiteJobStore(store.path)
    assert (
        restarted.claim(failed.kind, "restart", now=later, job_id=failed.job_id) is None
    )
    assert restarted.enqueue(failed.kind, failed.payload, now=later).status == "failed"
    assert raw(store, failed.job_id) == old
    for identity in (waiting.job_id, recovery.job_id):
        job = restarted.claim(failed.kind, "restart", now=later, job_id=identity)
        assert job.job_id == identity and job.attempt == 1
    with sqlite3.connect(store.path) as conn:
        events = conn.execute(
            "SELECT event_type,payload_json FROM event_log WHERE entity_type='job_queue' ORDER BY id"
        ).fetchall()
    assert [row[0] for row in events] == [
        "jobs.queue_paused",
        "jobs.queue_job_enqueued",
        "jobs.queue_resumed",
    ]
    assert json.loads(events[0][1])["assigned_job_ids"] == sorted(
        (failed.job_id, waiting.job_id)
    )
    assert json.loads(events[-1][1])["actor"] == "operator"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "{",
        '{"paused":"false","revision":1}',
        '{"paused":false}',
        '{"paused":false,"revision":0}',
    ],
)
def test_missing_or_invalid_control_blocks_only_the_assigned_queue(store, value):
    held = store.enqueue("data", {"case": "held"}, now=NOW)
    ordinary = store.enqueue("data", {"case": "ordinary"}, now=NOW)
    change(store, True, 0, (held.job_id,))
    with sqlite3.connect(store.path) as conn:
        if value is None:
            conn.execute(
                "DELETE FROM runtime_controls WHERE key=?", ("job_queue:" + QUEUE,)
            )
        else:
            conn.execute(
                "UPDATE runtime_controls SET value_json=? WHERE key=?",
                (value, "job_queue:" + QUEUE),
            )
    assert store.queue_status(QUEUE)["paused"] is True
    with pytest.raises(JobQueuePaused):
        store.require_queue_active(held.job_id)
    assert store.claim("data", "worker", now=NOW).job_id == ordinary.job_id
    assert store.claim("data", "worker", now=NOW, job_id=held.job_id) is None
    assert store.get(held.job_id).attempt == 0


def test_stale_operator_or_partial_assignment_rolls_back_with_no_audit(store):
    job = store.enqueue("data", {"case": "existing"}, now=NOW)
    change(store, True, 0)
    before = raw(store, job.job_id)
    with pytest.raises(ValueError, match="revision_changed"):
        change(store, False, 0, (job.job_id,))
    with pytest.raises(ValueError, match="not_found"):
        change(store, False, 1, (job.job_id, "f" * 64))
    assert raw(store, job.job_id) == before
    assert store.queue_status(QUEUE)["revision"] == 1
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE entity_type='job_queue'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("value", ["{", '{"queue_name":null}', '{"queue_name":123}'])
def test_invalid_assignment_blocks_its_job_without_blocking_normal_work(store, value):
    held = store.enqueue("data", {"case": "held-assignment"}, now=NOW)
    normal = store.enqueue("data", {"case": "normal-assignment"}, now=NOW)
    change(store, False, 0, (held.job_id,))
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE runtime_controls SET value_json=? WHERE key=?",
            (value, "job_queue_member:" + held.job_id),
        )
    assert store.claim("data", "worker", now=NOW).job_id == normal.job_id
    assert store.claim("data", "worker", now=NOW, job_id=held.job_id) is None
    with pytest.raises(JobQueuePaused):
        store.require_queue_active(held.job_id)


def test_pause_and_claim_share_the_write_transaction(store, monkeypatch):
    import server.persistence.jobs as jobs

    job = store.enqueue("data", {"case": "race"}, now=NOW)
    change(store, False, 0, (job.job_id,))
    writing, release = Event(), Event()
    insert = jobs.insert_event_sync

    def insert_while_locked(*args, **kwargs):
        result = insert(*args, **kwargs)
        writing.set()
        assert release.wait(2)
        return result

    monkeypatch.setattr(jobs, "insert_event_sync", insert_while_locked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pausing = pool.submit(change, store, True, 1)
        assert writing.wait(2)
        claiming = pool.submit(store.claim, "data", "worker", now=NOW)
        release.set()
        pausing.result()
        assert claiming.result() is None
    assert store.get(job.job_id).attempt == 0


@pytest.mark.asyncio
async def test_pause_after_claim_stops_provider_entry_without_killing_worker(store):
    now = datetime.now(timezone.utc)
    queued = store.enqueue(
        "market_daily_verified", {"case": "pause-before-entry"}, now=now
    )
    job = store.claim(queued.kind, "worker", now=now)
    change(store, True, 0, (job.job_id,))

    class MustNotFetch:
        def run(self, *_args, **_kwargs):
            pytest.fail("paused work reached a Provider")

    await execute_verified_daily_market_job(store, job, MustNotFetch(), timeout=2)
    held = store.get(job.job_id)
    assert held.status == "queued" and held.attempt == 1
    assert held.error == "job_queue_paused"
    assert store.claim(job.kind, "worker", now=now + timedelta(days=1)) is None
    ordinary = store.enqueue("market_calendar_sync", {"case": "unrelated"}, now=now)
    current = store.claim(ordinary.kind, "worker", now=now)
    store.finish(current.lease, now=now, result_ref="test:calendar")
    assert store.get(ordinary.job_id).status == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("next_action", ["provider", "publication"])
async def test_inflight_pause_fences_the_next_provider_or_publication(
    store, next_action
):
    now = datetime.now(timezone.utc)
    change(store, False, 0)
    queued = store.enqueue(
        "market_daily_verified", {"case": "inflight-pause"}, now=now, queue_name=QUEUE
    )
    job = store.claim(queued.kind, "worker", now=now)
    entries = []

    class PauseBetweenActions:
        def run(self, _payload, *, before_publish, before_provider_fetch):
            before_provider_fetch(None)
            change(store, True, 1)
            if next_action == "provider":
                before_provider_fetch(None)
            else:
                before_publish()
            raise AssertionError("paused action was admitted")

    await execute_verified_daily_market_job(
        store,
        job,
        PauseBetweenActions(),
        timeout=2,
        before_provider_fetch=lambda _descriptor: entries.append("admitted"),
    )
    assert entries == ["admitted"]
    assert store.get(job.job_id).status == "queued"
    assert store.get(job.job_id).error == "job_queue_paused"
    assert store.get(job.job_id).result_ref is None


def test_paused_inflight_job_cannot_finish_and_expired_lease_stays_held(store):
    job = store.enqueue("data", {"case": "inflight"}, now=NOW)
    claimed = store.claim(job.kind, "worker", now=NOW)
    change(store, True, 0, (job.job_id,))
    with pytest.raises(JobQueuePaused):
        store.finish(claimed.lease, now=NOW, result_ref="test:must-not-publish")
    before = raw(store, job.job_id)
    assert store.claim(job.kind, "new-worker", now=NOW + timedelta(days=1)) is None
    assert raw(store, job.job_id) == before
    change(store, False, 1)
    assert store.claim(job.kind, "new-worker", now=NOW + timedelta(days=1)).attempt == 2


def test_cli_changes_only_scheduling_and_reports_persisted_status(store, tmp_path):
    job = store.enqueue("data", {"case": "cli"}, now=NOW)
    manifest = tmp_path / "jobs.json"
    manifest.write_text(json.dumps({"jobs": [job.job_id]}))
    base = [sys.executable, str(ROOT / "scripts/data/job_queue.py")]
    common = ["--db", str(store.path), "--queue", QUEUE]
    subprocess.run(
        base
        + [
            "pause",
            *common,
            "--expected-revision",
            "0",
            "--actor",
            "operator",
            "--reason",
            "pilot wait",
            "--job-ids-file",
            str(manifest),
        ],
        check=True,
        capture_output=True,
    )
    status = subprocess.run(
        base + ["status", *common], check=True, capture_output=True, text=True
    )
    assert json.loads(status.stdout)["paused"] is True
    subprocess.run(
        base
        + [
            "resume",
            *common,
            "--expected-revision",
            "1",
            "--actor",
            "operator",
            "--reason",
            "fixture resume",
        ],
        check=True,
        capture_output=True,
    )
    assert store.queue_status(QUEUE)["paused"] is False
    assert store.get(job.job_id).status == "queued"
    assert store.get(job.job_id).attempt == 0
