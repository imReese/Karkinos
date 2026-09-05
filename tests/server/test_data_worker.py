from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock

import pytest

from server.contracts.market_calendar import MarketCalendarAutomationPublication
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_calendar_publication_uow import (
    MarketCalendarPublicationUnitOfWork,
)
from server.workers.data_worker import WorkerExecutionAborted, execute_calendar_job
from server.workers.presence import run_with_presence
from server.workers.supervisor import supervised_data_worker


def test_expired_worker_cannot_publish_even_before_replacement_claims(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    store = SQLiteJobStore(db.path)
    store.enqueue("calendar", {"year": 2026}, now=now)
    first = store.claim("calendar", "first", now=now)
    later = now + timedelta(seconds=61)
    uow = MarketCalendarPublicationUnitOfWork(db.path, now=lambda tz=None: later)
    command = MarketCalendarAutomationPublication(
        run={"run_id": "calendar:fixture"}, job_lease=first.lease
    )
    with pytest.raises(ValueError, match="job_lease_lost"):
        uow.publish_sync(command)
    assert db.get_automation_run_sync("calendar:fixture") is None
    store.claim("calendar", "replacement", now=later)
    with pytest.raises(ValueError, match="job_lease_lost"):
        uow.publish_sync(command)


@pytest.mark.asyncio
async def test_worker_publishes_result_ref_and_retries_failed_evidence(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    for status in ("completed", "failed"):
        payload = {"scheduled_at": now.isoformat(), "fixture": status}
        store.enqueue("calendar", payload, now=now)
        job = store.claim("calendar", "worker", now=now)
        service = Mock()
        service.run_due.return_value = [
            {"status": status, "run_id": "calendar:fixture"}
        ]
        await execute_calendar_job(store, job, service)
        result = store.enqueue("calendar", payload, now=now)
        assert result.status == ("succeeded" if status == "completed" else "queued")
        assert result.result_ref == (
            "automation_runs:calendar:fixture" if status == "completed" else None
        )


@pytest.mark.asyncio
async def test_presence_stops_when_worker_exits_and_does_not_claim_job_success():
    controls = Mock()

    async def work():
        return None

    await run_with_presence(controls, "data_worker_heartbeat", "worker", work())
    statuses = [call.args[1]["status"] for call in controls.set_value.call_args_list]
    assert statuses == ["ready", "stopped"]


def test_supervisor_restarts_exited_child_and_reaps_child_on_shutdown(monkeypatch):
    first, replacement = Mock(), Mock()
    first.poll.return_value = 1
    replacement.poll.return_value = None
    started = Event()

    def start(command, **kwargs):
        assert command[-1] == "--data-worker"
        if not started.is_set():
            started.set()
            return first
        replaced.set()
        return replacement

    replaced = Event()
    monkeypatch.setattr("server.workers.supervisor.subprocess.Popen", start)
    with supervised_data_worker(enabled=True):
        assert replaced.wait(timeout=3)
    replacement.terminate.assert_called_once()
    replacement.wait.assert_called_once_with(timeout=10)


def test_initial_worker_spawn_failure_does_not_prevent_api_and_is_retried(monkeypatch):
    replacement = Mock()
    replacement.poll.return_value = None
    started = Event()
    calls = []

    def start(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("injected spawn failure")
        started.set()
        return replacement

    monkeypatch.setattr("server.workers.supervisor.subprocess.Popen", start)
    with supervised_data_worker(enabled=True):
        assert started.wait(3)
    replacement.terminate.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["heartbeat", "timeout", "activation"])
async def test_worker_fences_and_exits_when_provider_cannot_complete(
    tmp_path, monkeypatch, failure
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    store.enqueue("calendar", {"scheduled_at": now.isoformat()}, now=now)
    job = store.claim("calendar", "worker", now=now)
    if failure == "heartbeat":
        monkeypatch.setattr(
            store, "heartbeat", Mock(side_effect=ValueError("job_lease_lost"))
        )
    monkeypatch.setattr(
        "server.workers.data_worker.is_release_activation_guarded",
        lambda: failure == "activation",
    )
    blocked = Event()
    service = Mock()
    service.run_due.side_effect = lambda **kwargs: blocked.wait(5)
    try:
        with pytest.raises(WorkerExecutionAborted):
            await execute_calendar_job(
                store, job, service, timeout=0.1, heartbeat_interval=0.01
            )
        uow = MarketCalendarPublicationUnitOfWork(db.path)
        with pytest.raises(ValueError, match="job_lease_lost"):
            uow.publish_sync(
                MarketCalendarAutomationPublication(
                    run={"run_id": "late-publication"}, job_lease=job.lease
                )
            )
    finally:
        blocked.set()


def test_worker_lifetime_ends_after_parent_sigkill(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time

    pid_file = tmp_path / "worker.pid"
    child_code = "from server.workers.supervisor import watch_supervisor_lifetime; import time; watch_supervisor_lifetime(); time.sleep(30)"
    parent_code = f"""
import subprocess, sys, time
from pathlib import Path
from server.workers.supervisor import supervised_data_worker
original = subprocess.Popen
def spawn(command, **kwargs):
    child = original([sys.executable, '-c', {child_code!r}], **kwargs)
    Path({str(pid_file)!r}).write_text(str(child.pid))
    return child
subprocess.Popen = spawn
with supervised_data_worker(enabled=True):
    time.sleep(30)
"""
    parent = subprocess.Popen([sys.executable, "-c", parent_code])
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            Event().wait(0.02)
        child_pid = int(pid_file.read_text())
        parent.kill()
        parent.wait(timeout=3)
        while time.monotonic() < deadline:
            state = subprocess.run(
                ["ps", "-p", str(child_pid), "-o", "stat="],
                capture_output=True,
                text=True,
            )
            if state.returncode or state.stdout.strip().startswith("Z"):
                break
            Event().wait(0.02)
        else:
            pytest.fail("worker survived parent SIGKILL")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
