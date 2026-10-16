import asyncio
import json
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from data.market.capture import capture_provider_payload, read_provider_capture
from data.market.ingestion import DailyBarIngestionCapturedFailure
from data.storage.objects import ContentAddressedObjectStore
from server.contracts.market_calendar import MarketCalendarAutomationPublication
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_calendar_publication_uow import (
    MarketCalendarPublicationUnitOfWork,
)
from server.persistence.market_daily_call_budget import (
    market_daily_provider_call_budget_status,
    reserve_market_daily_provider_call,
)
from server.services.verified_daily_market_data import (
    VerifiedDailyMarketDataNotPublishable,
    VerifiedDailyMarketDataUnavailable,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reported_code", "expected_code"),
    [
        ("baostock_response_number_missing", "baostock_response_number_missing"),
        (
            "baostock_response_number_missing:close",
            "baostock_response_number_missing:close",
        ),
        (
            "baostock_response_adjustflag_invalid",
            "baostock_response_adjustflag_invalid",
        ),
        (
            "baostock_response_number_missing:close?token=private",
            "daily_bar_ingestion_failed_after_capture",
        ),
        (None, "daily_bar_ingestion_failed_after_capture"),
    ],
)
async def test_verified_worker_retains_captured_parse_failure_without_sdk_error_text(
    tmp_path, reported_code, expected_code
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    now = datetime.now(timezone.utc)
    objects = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    raw = b'{"rows":[["2026-01-05","sz000001","0",""]]}'
    capture = capture_provider_payload(
        objects,
        provider="baostock",
        operation="daily_bars",
        request={"symbol": "000001"},
        raw_payload=raw,
        payload_format="fixture.sdk.rows.v1",
        adapter_version="fixture.v1",
        started_at=now,
        completed_at=now,
        record_count=1,
    )
    store.enqueue(VERIFIED_DAILY_MARKET_JOB, {"fixture": "failed_parse"}, now=now)
    job = store.claim(VERIFIED_DAILY_MARKET_JOB, "fixture", now=now)
    failure = DailyBarIngestionCapturedFailure(capture)
    failure.public_error_code = reported_code
    service = Mock()
    service.run.side_effect = failure

    await execute_verified_daily_market_job(store, job, service)

    saved = store.get(job.job_id)
    assert saved.status == "queued"
    assert saved.result_ref is None
    assert saved.error == expected_code
    assert saved.failure_evidence_ref == f"capture:{capture.capture_id}"
    reopened = read_provider_capture(objects, objects.resolve_ref(capture.capture_id))
    assert objects.read_bytes(reopened.raw_object_ref) == raw


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
        failure_evidence_ref="verification:sha256:" + "d" * 64,
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
    assert replay.error == "verified_daily_market_cross_source_conflict"
    assert replay.failure_evidence_ref == "verification:sha256:" + "d" * 64


@pytest.mark.asyncio
async def test_verified_unavailable_defers_without_spending_failure_allowance_or_refunding_io(
    tmp_path, monkeypatch
):
    from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR

    tick = [datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (
                tick[0].astimezone(tz)
                if tz is not None
                else tick[0].replace(tzinfo=None)
            )

    monkeypatch.setattr("server.workers.data_worker.datetime", Clock)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    payload = {"fixture": "external-unavailable-then-quality-conflict"}
    queued = store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=tick[0])
    failure = [
        VerifiedDailyMarketDataUnavailable(
            "verified_daily_market_sources_unavailable:baostock"
        )
    ]

    def run(_payload, *, before_provider_fetch, **_):
        before_provider_fetch(BAOSTOCK_DAILY_BAR_DESCRIPTOR)
        raise failure[0]

    service = SimpleNamespace(run=run)
    history = []
    for attempt in range(1, 8):
        if attempt == 5:
            failure[0] = VerifiedDailyMarketDataNotPublishable(
                "verified_daily_market_cross_source_conflict",
                failure_evidence_ref="verification:sha256:" + "d" * 64,
            )
        job = store.claim(
            VERIFIED_DAILY_MARKET_JOB, "same-worker", now=tick[0], job_id=queued.job_id
        )
        assert job is not None and job.attempt == attempt
        if history:
            # A deferral cannot give an old thread the current worker's lease.
            with pytest.raises(ValueError, match="job_lease_lost"):
                store.fail(
                    history[-1],
                    now=tick[0],
                    error="stale",
                    preserve_retry_allowance=True,
                )
        history.append(job.lease)
        await execute_verified_daily_market_job(
            store,
            job,
            service,
            heartbeat_interval=60,
            before_provider_fetch=lambda descriptor: reserve_market_daily_provider_call(
                db.path, job.lease, descriptor, now=tick[0]
            ),
        )
        persisted = store.get(job.job_id)
        assert persisted.attempt == attempt
        assert (
            persisted.payload == payload
            and persisted.input_fingerprint == queued.input_fingerprint
        )
        budget = market_daily_provider_call_budget_status(db.path, now=tick[0])
        assert budget["groups"]["baostock"] == {
            "used": attempt,
            "limit": 100,
            "remaining": 100 - attempt,
        }
        assert persisted.status == ("failed" if attempt == 7 else "queued")
        if attempt <= 4:
            assert persisted.error == "VerifiedDailyMarketDataUnavailable"
        else:
            assert persisted.error == "verified_daily_market_cross_source_conflict"
        later = datetime.fromisoformat(persisted.available_at)
        assert (later - tick[0]).total_seconds() == min(
            60 * 2 ** min(attempt - 1, 6), 3600
        )
        assert (
            store.claim(
                VERIFIED_DAILY_MARKET_JOB, "early", now=tick[0], job_id=job.job_id
            )
            is None
        )
        tick[0] = later
        store = SQLiteJobStore(db.path)
    assert (
        store.claim(
            VERIFIED_DAILY_MARKET_JOB, "restarted", now=tick[0], job_id=queued.job_id
        )
        is None
    )
    assert (
        store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=tick[0]).status
        == "failed"
    )
    with pytest.raises(ValueError, match="job_lease_lost"):
        store.fail(
            history[-1],
            now=tick[0],
            error="do-not-revive-terminal",
            preserve_retry_allowance=True,
        )


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


@pytest.mark.asyncio
async def test_forward_input_gets_last_budget_slot_before_watchlist_backfill(
    tmp_path, monkeypatch
):
    from core.types import InstrumentKey, InstrumentType
    from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
    from data.source_policy import FREE_CN_RESEARCH_V1
    from server.services.market_calendar_evidence import (
        validate_verified_market_calendar,
    )
    from server.services.verified_daily_market_data import VerifiedDailyMarketJobRequest
    from tests.server.test_verified_daily_worker_gate import DAY, _calendar

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    calendar = db.upsert_market_calendar_snapshot_sync(_calendar())
    calendar = db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=DAY.year,
        source_fingerprint=calendar["source_fingerprint"],
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )
    evidence_ref = validate_verified_market_calendar(calendar).evidence_ref
    assert evidence_ref is not None
    now = datetime.now(timezone.utc)
    store = SQLiteJobStore(db.path)
    history = store.enqueue(
        DAILY_MARKET_COLLECTION_JOB,
        {"fixture": "historical-watchlist"},
        now=now - timedelta(days=1),
    )
    verified_history = store.enqueue(
        VERIFIED_DAILY_MARKET_JOB,
        {"fixture": "historical-verification"},
        now=now - timedelta(days=1),
    )
    current = store.enqueue(
        VERIFIED_DAILY_MARKET_JOB,
        VerifiedDailyMarketJobRequest(
            DAY,
            (InstrumentKey("600000", InstrumentType.STOCK),),
            FREE_CN_RESEARCH_V1.policy_id,
            (evidence_ref,),
        ).to_payload(),
        now=now,
    )
    budget_job = store.enqueue("fixture_budget", {"index": 1}, now=now)
    budget_lease = store.claim("fixture_budget", "fixture", now=now)
    assert budget_lease is not None
    for _ in range(99):
        reserve_market_daily_provider_call(
            db.path, budget_lease.lease, BAOSTOCK_DAILY_BAR_DESCRIPTOR, now=now
        )
    store.finish(budget_lease.lease, now=now, result_ref="fixture:spent")
    calls = []

    class Service:
        def run(self, payload, *, before_publish, before_provider_fetch):
            before_provider_fetch(BAOSTOCK_DAILY_BAR_DESCRIPTOR)
            calls.append(payload["trade_date"])
            before_publish()
            return "dataset:sha256:" + "a" * 64

    async def presence(_controls, _name, _owner, work):
        await work

    real_sleep = asyncio.sleep

    async def stop_after_cycle(_seconds):
        if _seconds == 5:
            raise asyncio.CancelledError
        await real_sleep(_seconds)

    monkeypatch.setattr("server.workers.data_worker.AppDatabase", lambda: db)
    monkeypatch.setattr("server.workers.data_worker.run_with_presence", presence)
    monkeypatch.setattr(
        "server.workers.data_worker.AutomationRunRepository.list_observation_automation_policies",
        lambda _: [
            {
                "observation_id": "da6a8efb-fc60-4c0a-80ac-f8d59d94fbe4",
                "dataset_preparation_enabled": True,
            }
        ],
    )
    monkeypatch.setattr(
        "server.workers.data_worker.run_research_observation_data_preparation_once",
        lambda *args, **kwargs: [{"pending_job_ids": [current.job_id]}],
    )
    monkeypatch.setattr(
        "server.workers.data_worker.enqueue_latest_daily_market_collection_jobs",
        lambda *args, **kwargs: SimpleNamespace(planned_count=0, trade_date=None),
    )
    monkeypatch.setattr(
        "server.workers.data_worker.VerifiedDailyMarketDataService",
        lambda *args: Service(),
    )
    monkeypatch.setattr("server.workers.data_worker.asyncio.sleep", stop_after_cycle)
    config = SimpleNamespace(
        market_calendar_auto_sync=False,
        market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id,
    )
    with pytest.raises(asyncio.CancelledError):
        await run_data_worker(config)

    assert calls == [DAY.isoformat()]
    assert store.get(current.job_id).status == "succeeded"
    assert store.get(history.job_id) == history
    assert store.get(verified_history.job_id) == verified_history
    assert store.get(budget_job.job_id).status == "succeeded"
    assert market_daily_provider_call_budget_status(db.path, now=now)["groups"][
        "baostock"
    ] == {"used": 100, "limit": 100, "remaining": 0}
