import asyncio
import json
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.contracts.market_calendar import MarketCalendarAutomationPublication
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_calendar_publication_uow import (
    MarketCalendarPublicationUnitOfWork,
)
from server.services.verified_daily_market_data import (
    VerifiedDailyMarketDataNotPublishable,
    VerifiedDailySourceResolution,
)
from server.workers.data_worker import (
    DAILY_MARKET_COLLECTION_JOB,
    VERIFIED_DAILY_MARKET_JOB,
    WorkerExecutionAborted,
    enqueue_daily_market_calendar_job,
    execute_calendar_job,
    execute_daily_market_collection_job,
    execute_verified_daily_market_job,
    run_data_worker,
)
from server.workers.presence import run_with_presence
from server.workers.supervisor import supervised_worker


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


def test_daily_calendar_identity_survives_hours_restart_and_shanghai_midnight(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    first_at = datetime(2026, 10, 2, 16, tzinfo=timezone.utc)
    store = SQLiteJobStore(db.path)
    first = enqueue_daily_market_calendar_job(store, now=first_at)
    assert first.payload == {
        "scheduled_at": "2026-10-03T00:00:00+08:00",
        "cadence": "daily",
    }
    restarted = SQLiteJobStore(db.path)
    later = enqueue_daily_market_calendar_job(
        restarted, now=first_at + timedelta(hours=23, minutes=59)
    )
    assert later.job_id == first.job_id
    following = enqueue_daily_market_calendar_job(
        restarted, now=first_at + timedelta(days=1)
    )
    assert following.job_id != first.job_id
    assert following.payload["scheduled_at"] == "2026-10-04T00:00:00+08:00"


@pytest.mark.asyncio
async def test_daily_calendar_execution_uses_real_time_and_ignores_old_hourly_jobs(
    tmp_path,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    old = store.enqueue(
        "market_calendar_sync",
        {"scheduled_at": (now - timedelta(days=2)).isoformat()},
        now=now - timedelta(days=2),
    )
    daily = enqueue_daily_market_calendar_job(store, now=now)
    job = store.claim("market_calendar_sync", "worker", now=now, job_id=daily.job_id)
    service = Mock()
    service.run_due.return_value = [{"status": "completed", "run_id": "fixture"}]
    await execute_calendar_job(store, job, service)
    used_time = service.run_due.call_args.kwargs["now"]
    assert now <= used_time <= datetime.now(timezone.utc)
    assert used_time != datetime.fromisoformat(daily.payload["scheduled_at"])
    assert store.get(old.job_id) == old
    assert store.get(daily.job_id).status == "succeeded"


@pytest.mark.asyncio
async def test_old_daily_calendar_job_does_not_fetch_a_different_day(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    store = SQLiteJobStore(db.path)
    old = enqueue_daily_market_calendar_job(store, now=now - timedelta(days=2))
    job = store.claim("market_calendar_sync", "worker", now=now, job_id=old.job_id)
    service = Mock()
    await execute_calendar_job(store, job, service)
    service.run_due.assert_not_called()
    assert store.get(old.job_id).status == "failed"
    assert store.get(old.job_id).error == "calendar_job_day_expired"


@pytest.mark.asyncio
async def test_calendar_worker_honors_persisted_cooldown_after_restart(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    store = SQLiteJobStore(db.path)
    daily = enqueue_daily_market_calendar_job(store, now=now)
    job = store.claim("market_calendar_sync", "worker", now=now, job_id=daily.job_id)
    retry_after = now + timedelta(hours=1)
    service = Mock()
    service.run_due.return_value = [
        {
            "status": "failed",
            "run_id": "fixture",
            "payload_json": json.dumps(
                {
                    "retry_after": retry_after.isoformat(),
                    "retryable": True,
                }
            ),
        }
    ]
    await execute_calendar_job(store, job, service)
    restarted = SQLiteJobStore(db.path)
    assert (
        restarted.claim(
            "market_calendar_sync",
            "worker",
            now=now + timedelta(minutes=2),
            job_id=daily.job_id,
        )
        is None
    )
    assert (
        restarted.claim(
            "market_calendar_sync",
            "worker",
            now=retry_after + timedelta(seconds=2),
            job_id=daily.job_id,
        ).attempt
        == 2
    )


@pytest.mark.asyncio
async def test_calendar_worker_does_not_retry_rate_limited_daily_result(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    store = SQLiteJobStore(db.path)
    daily = enqueue_daily_market_calendar_job(store, now=now)
    job = store.claim("market_calendar_sync", "worker", now=now, job_id=daily.job_id)
    service = Mock()
    service.run_due.return_value = [
        {
            "status": "failed",
            "run_id": "fixture",
            "payload_json": json.dumps(
                {
                    "retry_after": (now + timedelta(days=1)).isoformat(),
                    "retryable": False,
                }
            ),
        }
    ]
    await execute_calendar_job(store, job, service)
    restarted = SQLiteJobStore(db.path)
    assert restarted.get(daily.job_id).status == "failed"
    assert restarted.get(daily.job_id).attempt == 1
    assert (
        restarted.claim(
            "market_calendar_sync",
            "worker",
            now=now + timedelta(hours=2),
            job_id=daily.job_id,
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_has_deadline", [True, False])
async def test_calendar_worker_retries_only_retryable_years(
    tmp_path, retry_has_deadline
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    store = SQLiteJobStore(db.path)
    daily = enqueue_daily_market_calendar_job(store, now=now)
    job = store.claim("market_calendar_sync", "worker", now=now, job_id=daily.job_id)
    retry_payload = {"retryable": True}
    if retry_has_deadline:
        retry_payload["retry_after"] = (now + timedelta(hours=1)).isoformat()
    service = Mock()
    service.run_due.return_value = [
        {
            "status": "failed",
            "run_id": "retryable-year",
            "payload_json": json.dumps(retry_payload),
        },
        {
            "status": "failed",
            "run_id": "terminal-year",
            "payload_json": json.dumps(
                {
                    "retryable": False,
                    "retry_after": (
                        now + timedelta(minutes=2 if retry_has_deadline else 1440)
                    ).isoformat(),
                }
            ),
        },
    ]
    await execute_calendar_job(store, job, service)
    if retry_has_deadline:
        assert (
            store.claim(
                "market_calendar_sync",
                "worker",
                now=now + timedelta(minutes=3),
                job_id=daily.job_id,
            )
            is None
        )
    retry_at = now + timedelta(seconds=3602 if retry_has_deadline else 62)
    assert (
        store.claim(
            "market_calendar_sync", "worker", now=retry_at, job_id=daily.job_id
        ).attempt
        == 2
    )


@pytest.mark.asyncio
async def test_worker_loop_fetches_today_without_consuming_hourly_backlog(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    store = SQLiteJobStore(db.path)
    legacy = store.enqueue(
        "market_calendar_sync",
        {"scheduled_at": (now - timedelta(days=1)).isoformat()},
        now=now - timedelta(days=1),
    )
    service = Mock()
    service.run_due.return_value = [{"status": "completed", "run_id": "fixture"}]

    async def presence(controls, name, owner, work):
        await work

    real_sleep = asyncio.sleep

    async def stop_after_cycle(seconds):
        if seconds == 5:
            raise asyncio.CancelledError
        await real_sleep(seconds)

    monkeypatch.setattr("server.workers.data_worker.AppDatabase", lambda: db)
    monkeypatch.setattr(
        "server.workers.data_worker.MarketCalendarAutomationService",
        lambda **kwargs: service,
    )
    monkeypatch.setattr("server.workers.data_worker.run_with_presence", presence)
    monkeypatch.setattr(
        "server.workers.data_worker.enqueue_latest_daily_market_collection_jobs",
        lambda *args, **kwargs: SimpleNamespace(planned_count=0, trade_date=None),
    )
    monkeypatch.setattr("server.workers.data_worker.asyncio.sleep", stop_after_cycle)
    with pytest.raises(asyncio.CancelledError):
        await run_data_worker(SimpleNamespace(market_calendar_auto_sync=True))
    service.run_due.assert_called_once()
    assert store.get(legacy.job_id) == legacy
    daily = enqueue_daily_market_calendar_job(store, now=now)
    assert daily.status == "succeeded"
    assert daily.attempt == 1


@pytest.mark.asyncio
async def test_presence_stops_when_worker_exits_and_does_not_claim_job_success():
    controls = Mock()

    async def work():
        return None

    await run_with_presence(controls, "data_worker_heartbeat", "worker", work())
    statuses = [call.args[1]["status"] for call in controls.set_value.call_args_list]
    assert statuses == ["ready", "stopped"]


@pytest.mark.parametrize("worker", ["data", "research"])
def test_supervisor_restarts_exited_child_and_reaps_child_on_shutdown(
    monkeypatch, worker
):
    first, replacement = Mock(), Mock()
    first.poll.return_value = 1
    replacement.poll.return_value = None
    started = Event()

    def start(command, **kwargs):
        assert command[-1] == f"--{worker}-worker"
        if not started.is_set():
            started.set()
            return first
        replaced.set()
        return replacement

    replaced = Event()
    monkeypatch.setattr("server.workers.supervisor.subprocess.Popen", start)
    with supervised_worker(worker=worker, enabled=True):
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
    with supervised_worker(worker="data", enabled=True):
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
from server.workers.supervisor import supervised_worker
original = subprocess.Popen
def spawn(command, **kwargs):
    child = original([sys.executable, '-c', {child_code!r}], **kwargs)
    Path({str(pid_file)!r}).write_text(str(child.pid))
    return child
subprocess.Popen = spawn
with supervised_worker(worker="data", enabled=True):
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


@pytest.mark.asyncio
async def test_verified_market_worker_finishes_with_dataset_result_ref(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": "matched"}
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)

    observed: list[str] = []
    service = Mock()

    def run(request, *, before_publish):
        assert request == payload
        before_publish()
        observed.append("published")
        return type(
            "Publication",
            (),
            {"result_ref": "dataset:sha256:" + "a" * 64},
        )()

    service.run.side_effect = run
    await execute_verified_daily_market_job(
        store,
        job,
        service,
        heartbeat_interval=60,
    )

    result = store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    assert observed == ["published"]
    assert result.status == "succeeded"
    assert result.result_ref == "dataset:sha256:" + "a" * 64


@pytest.mark.asyncio
async def test_verified_market_worker_records_source_resolution_event(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": "telemetry"}
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)

    resolution = VerifiedDailySourceResolution(
        source_policy_id="karkinos.market.source.free_cn_research.v1",
        outcome="matched",
        attempted_pairs=(
            ("baostock", "akshare_tencent"),
            ("akshare_tencent", "akshare"),
        ),
        unavailable_providers=("baostock",),
        selected_pair=("akshare_tencent", "akshare"),
    )
    service = Mock()
    service.run.return_value = type(
        "Publication",
        (),
        {
            "result_ref": "dataset:sha256:" + "c" * 64,
            "source_resolution": resolution,
        },
    )()

    def record(event):
        db.append_event_sync(
            event_type="market.daily.source_resolution",
            timestamp=now.isoformat(),
            entity_type="market_daily_job",
            entity_id=job.job_id,
            source="data_worker",
            source_ref=job.job_id,
            payload=event,
        )

    await execute_verified_daily_market_job(
        store,
        job,
        service,
        heartbeat_interval=60,
        source_resolution_recorder=record,
    )

    events = db.list_events_sync(
        event_type="market.daily.source_resolution",
        entity_id=job.job_id,
    )
    assert len(events) == 1
    import json

    saved = json.loads(events[0]["payload_json"])
    assert saved["outcome"] == "matched"
    assert saved["unavailable_providers"] == ["baostock"]
    assert saved["selected_pair"] == {
        "primary": "akshare_tencent",
        "comparison": "akshare",
    }
    assert saved["result_ref"] == "dataset:sha256:" + "c" * 64
    assert saved["error_type"] is None


@pytest.mark.asyncio
async def test_collection_worker_records_quality_result_without_dataset(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": "collected"}
    store.enqueue(DAILY_MARKET_COLLECTION_JOB, payload, now=now)
    job = store.claim(DAILY_MARKET_COLLECTION_JOB, "worker", now=now)
    service = Mock()
    service.run.return_value = "quality:sha256:" + "a" * 64

    await execute_daily_market_collection_job(
        store, job, service, heartbeat_interval=60
    )

    result = store.enqueue(DAILY_MARKET_COLLECTION_JOB, payload, now=now)
    assert result.status == "succeeded"
    assert result.result_ref == "quality:sha256:" + "a" * 64


@pytest.mark.asyncio
async def test_verified_market_worker_records_fail_closed_source_resolution(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": "conflict-telemetry"}
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)

    resolution = VerifiedDailySourceResolution(
        source_policy_id="karkinos.market.source.free_cn_research.v1",
        outcome="conflict",
        attempted_pairs=(("baostock", "akshare_tencent"),),
        selected_pair=("baostock", "akshare_tencent"),
    )
    service = Mock()
    service.run.side_effect = VerifiedDailyMarketDataNotPublishable(
        "verified_daily_market_cross_source_conflict",
        source_resolution=resolution,
    )

    recorded: list[dict[str, object]] = []
    await execute_verified_daily_market_job(
        store,
        job,
        service,
        heartbeat_interval=60,
        source_resolution_recorder=recorded.append,
    )

    assert len(recorded) == 1
    assert recorded[0]["outcome"] == "conflict"
    assert recorded[0]["result_ref"] is None
    assert recorded[0]["error_type"] == "VerifiedDailyMarketDataNotPublishable"

    replay = store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    assert replay.status == "queued"


@pytest.mark.asyncio
async def test_source_resolution_telemetry_failure_never_changes_job_success(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": "telemetry-failure"}
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)

    resolution = VerifiedDailySourceResolution(
        source_policy_id="fixture",
        outcome="matched",
        attempted_pairs=(("baostock", "akshare_tencent"),),
        selected_pair=("baostock", "akshare_tencent"),
    )
    service = Mock()
    service.run.return_value = type(
        "Publication",
        (),
        {
            "result_ref": "dataset:sha256:" + "d" * 64,
            "source_resolution": resolution,
        },
    )()

    def broken_recorder(_payload):
        raise RuntimeError("telemetry unavailable")

    await execute_verified_daily_market_job(
        store,
        job,
        service,
        heartbeat_interval=60,
        source_resolution_recorder=broken_recorder,
    )

    replay = store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    assert replay.status == "succeeded"
    assert replay.result_ref == "dataset:sha256:" + "d" * 64


@pytest.mark.asyncio
async def test_verified_market_worker_retries_failed_publication(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": "conflict"}
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)

    service = Mock()
    service.run.side_effect = RuntimeError("verification_conflict")

    await execute_verified_daily_market_job(
        store,
        job,
        service,
        heartbeat_interval=60,
    )

    result = store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    assert result.status == "queued"
    assert result.result_ref is None
    assert result.error == "RuntimeError"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["heartbeat", "timeout", "activation"])
async def test_verified_market_worker_fences_publication_on_lost_authority(
    tmp_path,
    monkeypatch,
    failure,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": failure}
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)

    monkeypatch.setattr(
        "server.workers.data_worker.is_release_activation_guarded",
        lambda: failure == "activation",
    )
    if failure == "heartbeat":
        monkeypatch.setattr(
            store,
            "heartbeat",
            Mock(side_effect=ValueError("job_lease_lost")),
        )

    blocked = Event()
    service = Mock()

    def run(request, *, before_publish):
        if failure == "timeout":
            blocked.wait(5)
            return type(
                "Publication",
                (),
                {"result_ref": "dataset:sha256:" + "b" * 64},
            )()
        before_publish()
        pytest.fail("publication guard should have fenced this job")

    service.run.side_effect = run
    try:
        with pytest.raises(WorkerExecutionAborted):
            await execute_verified_daily_market_job(
                store,
                job,
                service,
                timeout=0.1,
                heartbeat_interval=0.01,
            )
    finally:
        blocked.set()


@pytest.mark.asyncio
async def test_verified_market_worker_rejects_non_dataset_result_ref(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    payload = {"fixture": "bad-result"}
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "worker", now=now)

    service = Mock()
    service.run.return_value = type(
        "Publication",
        (),
        {"result_ref": "not-a-dataset"},
    )()

    await execute_verified_daily_market_job(
        store,
        job,
        service,
        heartbeat_interval=60,
    )
    result = store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=now)
    assert result.status == "queued"
    assert result.error == "RuntimeError"


@pytest.mark.asyncio
async def test_data_worker_plans_collection_and_still_claims_existing_verified_jobs(
    monkeypatch,
):
    calls: list[tuple[str, object]] = []

    class FakeDb:
        path = __import__("pathlib").Path("/tmp/fake-app.db")

        async def init(self):
            calls.append(("db_init", None))

    class FakeStore:
        def __init__(self, path):
            calls.append(("store_init", path))

        def claim(self, kind, owner, *, now):
            calls.append(("claim", kind))
            return None

    class FakeControls:
        def __init__(self, path):
            calls.append(("controls_init", path))

    async def fake_presence(controls, name, owner, work):
        calls.append(("presence", name))
        await work

    async def fake_wait_for_release_activation():
        calls.append(("activation", None))

    async def stop_after_first_cycle(_seconds):
        raise asyncio.CancelledError

    def fake_plan(db, config, store, *, now):
        calls.append(("plan", now))
        return type(
            "Plan",
            (),
            {"planned_count": 0, "trade_date": None},
        )()

    monkeypatch.setattr("server.workers.data_worker.AppDatabase", FakeDb)
    monkeypatch.setattr("server.workers.data_worker.SQLiteJobStore", FakeStore)
    monkeypatch.setattr(
        "server.workers.data_worker.RuntimeControlRepository", FakeControls
    )
    monkeypatch.setattr("server.workers.data_worker.run_with_presence", fake_presence)
    monkeypatch.setattr(
        "server.workers.data_worker.wait_for_release_activation",
        fake_wait_for_release_activation,
    )
    monkeypatch.setattr(
        "server.workers.data_worker.enqueue_latest_daily_market_collection_jobs",
        fake_plan,
    )
    monkeypatch.setattr(
        "server.workers.data_worker.asyncio.sleep", stop_after_first_cycle
    )

    config = type("Config", (), {"market_calendar_auto_sync": False})()

    with pytest.raises(asyncio.CancelledError):
        await run_data_worker(config)

    names = [name for name, _ in calls]
    assert names.index("plan") < names.index("claim")
    assert ("claim", DAILY_MARKET_COLLECTION_JOB) in calls
    assert ("claim", VERIFIED_DAILY_MARKET_JOB) in calls
