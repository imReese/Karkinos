"""An explicit successor fences its immutable parent across claims and restarts."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from server.persistence.jobs import JobIdentityConflictError
from server.persistence.runtime_controls import RuntimeControlRepository
from tests.server.test_job_queues import NOW, ROOT, change, raw, store  # noqa: F401


def recover(store, original, *, payload=None, **kwargs):
    return store.enqueue_successor(
        original,
        payload or {"recovery_of": original.job_id},
        now=NOW,
        actor="operator",
        reason="Explicit recovery",
        **kwargs,
    )


@pytest.mark.parametrize("terminal", [False, True])
def test_replacement_keeps_parent_rows_and_queue_controls_across_restart(
    store, terminal
):
    original = store.enqueue("data", {"case": "original"}, now=NOW)
    if terminal:
        claimed = store.claim(original.kind, "first", now=NOW)
        store.fail(claimed.lease, now=NOW, error="missing", retryable=False)
    change(store, True, 0, (original.job_id,))
    original = store.get(original.job_id)
    before = raw(store, original.job_id)
    successor = recover(store, original)
    assert successor.queue_name == original.queue_name
    assert store.queue_status(original.queue_name)["paused"] is True
    assert store.claim("data", "worker", now=NOW) is None
    change(store, False, 1)
    current = store.claim("data", "worker", now=NOW)
    assert current.job_id == successor.job_id
    store.finish(current.lease, now=NOW, result_ref="test:completed")
    assert recover(store, original) == store.get(successor.job_id)
    ordinary = store.enqueue("data", {"case": "ordinary"}, now=NOW)
    program = """
import json, sys
from datetime import datetime
from server.persistence.jobs import SQLiteJobStore
store = SQLiteJobStore(sys.argv[1])
now = datetime.fromisoformat(sys.argv[2])
successor = store.get_successor(sys.argv[3])
assert successor.status == 'succeeded'
assert store.claim('data', 'restart', now=now, job_id=sys.argv[3]) is None
print(json.dumps({'successor': successor.job_id,
                  'next': store.claim('data', 'restart', now=now).job_id}))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(store.path),
            NOW.isoformat(),
            original.job_id,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "successor": successor.job_id,
        "next": ordinary.job_id,
    }
    assert raw(store, original.job_id) == before
    with sqlite3.connect(store.path) as conn:
        events = conn.execute(
            "SELECT payload_json FROM event_log WHERE event_type='jobs.successor_associated'"
        ).fetchall()
    assert len(events) == 1 and json.loads(events[0][0])["actor"] == "operator"


def test_concurrent_duplicate_creation_is_one_job_and_one_association(store):
    original = store.enqueue("data", {"case": "original"}, now=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(recover, store, original) for _ in range(2)]
        successors = [item.result() for item in pending]
    assert successors[0] == successors[1]
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT count(*) FROM job_runs").fetchone()[0] == 2
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE event_type='jobs.successor_associated'"
            ).fetchone()[0]
            == 1
        )
    with pytest.raises(JobIdentityConflictError, match="successor_conflict"):
        recover(store, original, payload={"different_recovery": True})
    with pytest.raises(JobIdentityConflictError, match="successor_conflict"):
        recover(store, successors[0])


def test_association_and_claim_are_serialized(store, monkeypatch):
    import server.persistence.jobs as module

    original = store.enqueue("data", {"case": "original"}, now=NOW)
    before = raw(store, original.job_id)
    writing, release = Event(), Event()
    insert = module.insert_event_sync

    def hold_transaction(*args, **kwargs):
        result = insert(*args, **kwargs)
        writing.set()
        assert release.wait(2)
        return result

    monkeypatch.setattr(module, "insert_event_sync", hold_transaction)
    with ThreadPoolExecutor(max_workers=2) as pool:
        creating = pool.submit(recover, store, original)
        assert writing.wait(2)
        claiming = pool.submit(
            store.claim, "data", "worker", now=NOW, job_id=original.job_id
        )
        release.set()
        successor = creating.result()
        assert claiming.result() is None
    assert store.claim("data", "worker", now=NOW).job_id == successor.job_id
    assert raw(store, original.job_id) == before


def test_already_claimed_parent_cannot_be_replaced_using_a_stale_snapshot(store):
    original = store.enqueue("data", {"case": "original"}, now=NOW)
    running = store.claim("data", "worker", now=NOW)
    with pytest.raises(ValueError, match="original_changed"):
        recover(store, original)
    with pytest.raises(ValueError, match="request_invalid"):
        recover(store, running)
    assert store.get_successor(original.job_id) is None
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT count(*) FROM job_runs").fetchone()[0] == 1


def test_failed_successor_does_not_revive_parent_or_reset_recovery(store):
    original = store.enqueue("data", {"case": "original"}, now=NOW)
    before = raw(store, original.job_id)
    successor = recover(store, original)
    claimed = store.claim("data", "worker", now=NOW)
    store.fail(claimed.lease, now=NOW, error="conflicting_inputs", retryable=False)
    failed = store.get(successor.job_id)
    assert recover(store, original) == failed
    assert store.claim("data", "worker", now=NOW + timedelta(days=1)) is None
    assert raw(store, original.job_id) == before


def test_queue_assignment_failure_rolls_back_association_and_audit(store):
    original = store.enqueue("data", {"case": "original"}, now=NOW)
    change(store, True, 0, (original.job_id,))
    original = store.get(original.job_id)
    payload = {"recovery_of": original.job_id}
    store.enqueue("data", payload, now=NOW)  # Existing unrelated queue assignment.
    with pytest.raises(ValueError, match="queue_assignment_conflict"):
        recover(store, original, payload=payload)
    assert store.get_successor(original.job_id) is None
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE event_type='jobs.successor_associated'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "value", ["{", "{}", '{"successor_id":null}', '{"successor_id":"missing"}']
)
def test_corrupt_association_fails_closed_only_for_its_parent(store, value):
    original = store.enqueue("data", {"case": "original"}, now=NOW)
    ordinary = store.enqueue("data", {"case": "ordinary"}, now=NOW)
    recover(store, original)
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE runtime_controls SET value_json=? WHERE key=?",
            (value, "job_successor:" + original.job_id),
        )
    with pytest.raises(JobIdentityConflictError, match="successor_invalid"):
        store.get_successor(original.job_id)
    assert store.claim("data", "worker", now=NOW, job_id=original.job_id) is None
    assert store.claim("data", "worker", now=NOW, job_id=ordinary.job_id) is not None


def test_generic_runtime_controls_cannot_overwrite_association(store):
    with pytest.raises(ValueError, match="audited job store"):
        RuntimeControlRepository(store.path).set_value("job_successor:" + "a" * 64, {})
