from __future__ import annotations

import asyncio
import inspect
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
)
from server.config import AIProviderConfig, ServerConfig
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_ID,
    ShadowResearchPolicy,
)
from server.db import AppDatabase
from server.dependencies import AppState
from server.persistence.ai_shadow_research_worker_jobs import (
    AiShadowResearchWorkerJobStore,
)
from server.services.ai_shadow.ai_shadow_research_job_scheduler import (
    AiShadowResearchJobScheduler,
    shadow_research_provider_config_fingerprint,
)
from server.services.ai_shadow.ai_shadow_research_worker import (
    AiShadowResearchWorker,
    AiShadowResearchWorkerLeaseLost,
)
from server.services.controlled_execution.trading_controls import TradingControlState

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.unit
@pytest.mark.trading_safety
def test_scheduler_durably_enqueues_friday_18_window_without_provider(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    now = {"value": datetime(2026, 9, 4, 13, 0, tzinfo=SHANGHAI)}
    scheduler = AiShadowResearchJobScheduler(
        state=state,
        store=AiShadowResearchWorkerJobStore(state.require_database().path),
        now=lambda: now["value"],
    )

    first = scheduler.enqueue_if_authorized()
    now["value"] = datetime(2026, 9, 4, 13, 5, tzinfo=SHANGHAI)
    repeated = scheduler.enqueue_if_authorized()

    assert first["status"] == "enqueued"
    assert first["available_at"] == "2026-09-04T10:00:00+00:00"
    assert first["deadline_at"] == "2026-09-07T01:00:00+00:00"
    assert repeated["status"] == "already_enqueued"
    assert repeated["job_id"] == first["job_id"]
    assert first["provider_call_performed"] is False
    stored = AiShadowResearchWorkerJobStore(state.require_database().path).get(
        first["job_id"]
    )
    assert stored is not None
    assert stored["status"] == "pending"
    assert stored["payload"]["policy_fingerprint"] == content_fingerprint(
        policy.to_dict()
    )
    assert stored["payload"]["broker_submission_enabled"] is False
    assert stored["payload"]["execution_authority_granted"] is False
    assert stored["payload"]["capital_authority_granted"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_stale_lease_takeover_is_restart_recoverable_and_old_owner_cannot_commit(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    job = _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    first = store.claim_next(
        lease_owner="worker-a",
        claimed_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
        lease_seconds=90,
    )
    assert first is not None
    assert (
        store.claim_next(
            lease_owner="worker-b",
            claimed_at=datetime(2026, 9, 4, 18, 1, tzinfo=SHANGHAI),
            lease_seconds=90,
        )
        is None
    )

    recovered = store.claim_next(
        lease_owner="worker-b",
        claimed_at=datetime(2026, 9, 4, 18, 1, 31, tzinfo=SHANGHAI),
        lease_seconds=90,
    )

    assert recovered is not None
    assert recovered["run_id"] == job["run_id"]
    assert recovered["payload"]["attempt_count"] == 2
    assert recovered["payload"]["lease_generation"] == 2
    assert recovered["payload"]["takeover_count"] == 1
    assert not store.complete(
        job_id=job["run_id"],
        lease_owner="worker-a",
        lease_generation=1,
        completed_at=datetime(2026, 9, 4, 18, 1, 32, tzinfo=SHANGHAI),
        result={"run_status": "completed"},
    )
    assert store.complete(
        job_id=job["run_id"],
        lease_owner="worker-b",
        lease_generation=2,
        completed_at=datetime(2026, 9, 4, 18, 1, 32, tzinfo=SHANGHAI),
        result={"run_status": "completed"},
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_expired_lease_cannot_commit_even_before_takeover(tmp_path: Path) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    job = _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    assert store.claim_next(
        lease_owner="expired-worker",
        claimed_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
        lease_seconds=90,
    )

    assert not store.complete(
        job_id=str(job["run_id"]),
        lease_owner="expired-worker",
        lease_generation=1,
        completed_at=datetime(2026, 9, 4, 18, 1, 30, tzinfo=SHANGHAI),
        result={"run_status": "completed"},
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_same_owner_old_generation_cannot_renew_or_commit_after_takeover(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    job = _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    assert store.claim_next(
        lease_owner="reused-owner",
        claimed_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
        lease_seconds=10,
    )
    recovered = store.claim_next(
        lease_owner="reused-owner",
        claimed_at=datetime(2026, 9, 4, 18, 0, 11, tzinfo=SHANGHAI),
        lease_seconds=90,
    )
    assert recovered is not None
    assert recovered["payload"]["lease_generation"] == 2

    assert not store.renew_lease(
        job_id=str(job["run_id"]),
        lease_owner="reused-owner",
        lease_generation=1,
        renewed_at=datetime(2026, 9, 4, 18, 0, 12, tzinfo=SHANGHAI),
    )
    assert not store.complete(
        job_id=str(job["run_id"]),
        lease_owner="reused-owner",
        lease_generation=1,
        completed_at=datetime(2026, 9, 4, 18, 0, 12, tzinfo=SHANGHAI),
        result={"run_status": "completed"},
    )
    assert store.complete(
        job_id=str(job["run_id"]),
        lease_owner="reused-owner",
        lease_generation=2,
        completed_at=datetime(2026, 9, 4, 18, 0, 12, tzinfo=SHANGHAI),
        result={"run_status": "completed"},
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_takeover_waits_for_in_flight_send_and_old_thread_cannot_persist(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    clock = {"value": datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI)}
    send_started = threading.Event()
    release_send = threading.Event()
    persisted: list[str] = []

    class BlockingRunner:
        def __init__(self, fence: object) -> None:
            self._fence = fence

        async def run_once(self) -> dict[str, object]:
            def blocking_send() -> None:
                token = self._fence.begin_provider_send(timeout_seconds=120)  # type: ignore[attr-defined]
                send_started.set()
                assert release_send.wait(timeout=2)
                self._fence.finish_provider_send(token)  # type: ignore[attr-defined]
                persisted.append("provider-result")

            await asyncio.to_thread(blocking_send)
            return {"run_status": "completed"}

    worker = AiShadowResearchWorker(
        state=state,
        store=store,
        service_builder=lambda fence: BlockingRunner(fence),
        lease_owner="worker-a",
        now=lambda: clock["value"],
        lease_seconds=10,
        heartbeat_seconds=300,
    )
    old_attempt = asyncio.create_task(worker.run_one())
    assert await asyncio.to_thread(send_started.wait, 1)
    job = store.list_recent(limit=1)[0]
    job_id = str(job["run_id"])

    clock["value"] = datetime(2026, 9, 4, 18, 0, 11, tzinfo=SHANGHAI)
    assert (
        store.claim_next(
            lease_owner="worker-b",
            claimed_at=clock["value"],
            lease_seconds=90,
        )
        is None
    )
    clock["value"] = datetime(2026, 9, 4, 18, 2, 1, tzinfo=SHANGHAI)
    takeover = store.claim_next(
        lease_owner="worker-b",
        claimed_at=clock["value"],
        lease_seconds=90,
    )
    assert takeover is not None
    assert takeover["payload"]["lease_generation"] == 2
    release_send.set()

    with pytest.raises(AiShadowResearchWorkerLeaseLost):
        await asyncio.wait_for(old_attempt, timeout=1)
    assert persisted == []
    assert not store.complete(
        job_id=job_id,
        lease_owner="worker-a",
        lease_generation=1,
        completed_at=clock["value"],
        result={"run_status": "completed"},
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_restarted_worker_consumes_stale_job_once(tmp_path: Path) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    assert store.claim_next(
        lease_owner="crashed-worker",
        claimed_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
        lease_seconds=90,
    )
    calls: list[str] = []

    class Runner:
        async def run_once(self) -> dict[str, object]:
            calls.append("run")
            return {"run_status": "completed", "run_id": "research:fixture"}

    recovered_at = datetime(2026, 9, 4, 18, 1, 31, tzinfo=SHANGHAI)
    worker = AiShadowResearchWorker(
        state=state,
        store=store,
        service_builder=lambda _fence: Runner(),
        lease_owner="restarted-worker",
        now=lambda: recovered_at,
    )

    outcome = await worker.run_one()

    assert calls == ["run"]
    assert outcome is not None
    assert outcome["disposition"] == "completed"
    assert store.list_recent(limit=1)[0]["status"] == "completed"


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "waiting_status",
    ["awaiting_verified_research_inputs", "awaiting_independent_validation"],
)
async def test_worker_retries_same_durable_job_when_research_inputs_become_ready(
    tmp_path: Path,
    waiting_status: str,
) -> None:
    state, _policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    clock = {"value": datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI)}
    scheduler = AiShadowResearchJobScheduler(
        state=state, store=store, now=lambda: clock["value"]
    )
    enqueued = scheduler.enqueue_if_authorized()
    assert enqueued["status"] == "enqueued"
    inputs_ready = False
    calls: list[str] = []

    class Runner:
        async def run_once(self) -> dict[str, object]:
            calls.append("ready" if inputs_ready else "waiting")
            return {
                "run_status": "completed" if inputs_ready else waiting_status,
                "run_id": "research:ready" if inputs_ready else None,
            }

    runner = Runner()
    worker = AiShadowResearchWorker(
        state=state,
        store=store,
        service_builder=lambda _fence: runner,
        lease_owner="waiting-input-worker",
        now=lambda: clock["value"],
        retry_seconds=300,
    )

    waiting = await worker.run_one()

    assert waiting is not None
    assert waiting["job_id"] == enqueued["job_id"]
    assert waiting["disposition"] == "rescheduled"
    pending = store.get(enqueued["job_id"])
    assert pending is not None and pending["status"] == "pending"
    assert pending["payload"]["last_result"]["run_status"] == waiting_status
    assert pending["payload"]["attempt_count"] == 1
    assert await worker.run_one() is None
    repeated = scheduler.enqueue_if_authorized()
    assert repeated["status"] == "already_enqueued"
    assert repeated["job_id"] == enqueued["job_id"]

    inputs_ready = True
    clock["value"] += timedelta(seconds=300)
    completed = await worker.run_one()

    assert completed is not None
    assert completed["job_id"] == enqueued["job_id"]
    assert completed["disposition"] == "completed"
    finished = store.get(enqueued["job_id"])
    assert finished is not None and finished["status"] == "completed"
    assert finished["payload"]["attempt_count"] == 2
    assert finished["payload"]["lease_generation"] == 2
    assert finished["payload"]["last_result"]["run_id"] == "research:ready"
    assert calls == ["waiting", "ready"]
    assert len(store.list_recent()) == 1


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_worker_rechecks_kill_switch_before_provider_construction(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    assert state.trading_controls is not None
    state.trading_controls.set_kill_switch(True, "operator stop")
    worker = AiShadowResearchWorker(
        state=state,
        store=store,
        service_builder=lambda _fence: (_ for _ in ()).throw(
            AssertionError("provider path must remain unconstructed")
        ),
        lease_owner="guarded-worker",
        now=lambda: datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )

    outcome = await worker.run_one()

    assert outcome is not None
    assert outcome["disposition"] == "failed"
    assert outcome["failure_code"] == "blocked_by_kill_switch"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_worker_waits_for_release_activation_before_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services.ai_shadow import ai_shadow_research_worker as worker_runtime

    state, _policy = _state(tmp_path)
    events: list[str] = []

    class EmptyStore:
        def claim_next(self, **_kwargs: object) -> None:
            events.append("claim")

    class StopLoop(Exception):
        pass

    async def activation_guard() -> None:
        events.append("activation")

    async def stop_after_poll(_seconds: float) -> None:
        events.append("poll")
        raise StopLoop

    monkeypatch.setattr(worker_runtime, "wait_for_release_activation", activation_guard)
    monkeypatch.setattr(worker_runtime.asyncio, "sleep", stop_after_poll)
    worker = AiShadowResearchWorker(state=state, store=EmptyStore())  # type: ignore[arg-type]

    with pytest.raises(StopLoop):
        await worker.run_forever(poll_seconds=1)

    assert events == ["activation", "claim", "poll"]


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_delayed_provider_worker_does_not_block_independent_decision_work(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    provider_started = asyncio.Event()
    release_provider = asyncio.Event()

    class SlowRunner:
        async def run_once(self) -> dict[str, object]:
            provider_started.set()
            await release_provider.wait()
            return {"run_status": "completed", "run_id": "research:slow"}

    worker = AiShadowResearchWorker(
        state=state,
        store=store,
        service_builder=lambda _fence: SlowRunner(),
        lease_owner="isolated-worker",
        now=lambda: datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    worker_task = asyncio.create_task(worker.run_one())
    await asyncio.wait_for(provider_started.wait(), timeout=1)

    async def decision_work() -> str:
        await asyncio.sleep(0)
        return "NO-ACTION"

    assert await asyncio.wait_for(decision_work(), timeout=0.1) == "NO-ACTION"
    assert not worker_task.done()
    release_provider.set()
    outcome = await asyncio.wait_for(worker_task, timeout=1)
    assert outcome is not None and outcome["disposition"] == "completed"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_worker_transient_failure_retries_with_backoff_and_bounds(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    job = _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    job_id = str(job["run_id"])
    clock = {"value": datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI)}

    class FailingRunner:
        async def run_once(self) -> dict[str, object]:
            raise AttributeError("simulated transient hot reload error")

    worker = AiShadowResearchWorker(
        state=state,
        store=store,
        service_builder=lambda _fence: FailingRunner(),
        lease_owner="failing-worker",
        now=lambda: clock["value"],
    )

    # Attempt 1: transient failure -> rescheduled with 60s backoff
    outcome1 = await worker.run_one()
    assert outcome1 is not None
    assert outcome1["disposition"] == "rescheduled"
    assert outcome1["failure_code"] == "AttributeError"
    stored1 = store.get(job_id)
    assert stored1 is not None and stored1["status"] == "pending"
    assert stored1["payload"]["failure_attempt_count"] == 1
    assert (
        stored1["payload"]["available_at"]
        == (clock["value"] + timedelta(seconds=60)).astimezone(timezone.utc).isoformat()
    )

    # Advance 60s -> Attempt 2: transient failure -> rescheduled with 120s backoff
    clock["value"] += timedelta(seconds=60)
    outcome2 = await worker.run_one()
    assert outcome2 is not None
    assert outcome2["disposition"] == "rescheduled"
    assert outcome2["failure_code"] == "AttributeError"
    stored2 = store.get(job_id)
    assert stored2 is not None and stored2["status"] == "pending"
    assert stored2["payload"]["failure_attempt_count"] == 2
    assert (
        stored2["payload"]["available_at"]
        == (clock["value"] + timedelta(seconds=120))
        .astimezone(timezone.utc)
        .isoformat()
    )

    # Advance 120s -> Attempt 3: retries exhausted -> terminal fail
    clock["value"] += timedelta(seconds=120)
    outcome3 = await worker.run_one()
    assert outcome3 is not None
    assert outcome3["disposition"] == "failed"
    assert outcome3["failure_code"] == "AttributeError"
    stored3 = store.get(job_id)
    assert stored3 is not None and stored3["status"] == "failed"
    assert stored3["payload"]["last_result"]["failure_code"] == "AttributeError"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_worker_fatal_failure_fails_immediately_without_retry(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    job = _enqueue_direct(
        state=state,
        policy=policy,
        store=store,
        enqueued_at=datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI),
    )
    job_id = str(job["run_id"])
    clock = {"value": datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI)}

    # Activate kill switch
    controls = state.trading_controls
    assert controls is not None
    controls.set_kill_switch(True, reason="emergency halt")

    worker = AiShadowResearchWorker(
        state=state,
        store=store,
        lease_owner="fatal-worker",
        now=lambda: clock["value"],
    )

    outcome = await worker.run_one()
    assert outcome is not None
    assert outcome["disposition"] == "failed"
    assert outcome["failure_code"] == "blocked_by_kill_switch"
    stored = store.get(job_id)
    assert stored is not None and stored["status"] == "failed"


@pytest.mark.unit
def test_scheduler_recovers_failed_job_after_cooldown_with_runway(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    clock = {"value": datetime(2026, 9, 4, 18, 0, tzinfo=SHANGHAI)}
    scheduler = AiShadowResearchJobScheduler(
        state=state,
        store=store,
        now=lambda: clock["value"],
        recovery_cooldown_seconds=900,
    )

    enqueued = scheduler.enqueue_if_authorized()
    assert enqueued["status"] == "enqueued"
    job_id = enqueued["job_id"]

    # Claim and fail the job at 18:00
    claimed = store.claim_next(
        lease_owner="failing-worker",
        claimed_at=clock["value"],
        lease_seconds=90,
    )
    assert claimed is not None
    assert store.fail(
        job_id=job_id,
        lease_owner="failing-worker",
        lease_generation=1,
        failed_at=clock["value"],
        result={"run_status": "failed", "failure_code": "AttributeError"},
    )
    stored_failed = store.get(job_id)
    assert stored_failed is not None and stored_failed["status"] == "failed"

    # 5 minutes later (cooldown 900s not elapsed): scheduler does not recover
    clock["value"] += timedelta(minutes=5)
    too_early = scheduler.enqueue_if_authorized()
    assert too_early["status"] == "already_enqueued"
    assert store.get(job_id)["status"] == "failed"

    # 16 minutes after failure (cooldown elapsed): scheduler recovers the job
    clock["value"] += timedelta(minutes=11)
    recovered = scheduler.enqueue_if_authorized()
    assert recovered["status"] == "recovered"
    assert recovered["job_id"] == job_id
    stored = store.get(job_id)
    assert stored is not None and stored["status"] == "pending"
    assert stored["payload"]["attempt_count"] == 0
    assert stored["payload"]["failure_attempt_count"] == 0
    assert stored["payload"]["recovery_count"] == 1

    # Worker can immediately claim and run the recovered job
    claim = store.claim_next(
        lease_owner="fresh-worker",
        claimed_at=clock["value"],
        lease_seconds=90,
    )
    assert claim is not None
    assert claim["run_id"] == job_id
    assert claim["payload"]["attempt_count"] == 1


@pytest.mark.unit
def test_scheduler_does_not_recover_if_runway_insufficient_or_max_recoveries_exceeded(
    tmp_path: Path,
) -> None:
    state, policy = _state(tmp_path)
    store = AiShadowResearchWorkerJobStore(state.require_database().path)
    # Saturday 10:00 (inside weekend off-peak window, deadline is Monday 09:00)
    clock = {"value": datetime(2026, 9, 5, 10, 0, tzinfo=SHANGHAI)}
    scheduler = AiShadowResearchJobScheduler(
        state=state,
        store=store,
        now=lambda: clock["value"],
        recovery_cooldown_seconds=0,
        max_recovery_attempts=2,
    )

    # Initial enqueue at Saturday 10:00
    job = scheduler.enqueue_if_authorized()
    assert job["status"] == "enqueued"
    job_id = job["job_id"]

    # Recovery 1: fail and recover
    store.claim_next(
        lease_owner="w1",
        claimed_at=clock["value"],
        lease_seconds=90,
    )
    store.fail(
        job_id=job_id,
        lease_owner="w1",
        lease_generation=1,
        failed_at=clock["value"],
        result={"run_status": "failed", "failure_code": "AttributeError"},
    )
    rec1 = scheduler.enqueue_if_authorized()
    assert rec1["status"] == "recovered"
    assert store.get(job_id)["payload"]["recovery_count"] == 1

    # Recovery 2: fail and recover
    clock["value"] += timedelta(minutes=5)
    store.claim_next(
        lease_owner="w2",
        claimed_at=clock["value"],
        lease_seconds=90,
    )
    store.fail(
        job_id=job_id,
        lease_owner="w2",
        lease_generation=2,
        failed_at=clock["value"],
        result={"run_status": "failed", "failure_code": "AttributeError"},
    )
    rec2 = scheduler.enqueue_if_authorized()
    assert rec2["status"] == "recovered"
    assert store.get(job_id)["payload"]["recovery_count"] == 2

    # Attempt 3: fail again -> recovery_count (2) >= max_recovery_attempts (2) -> rejected
    clock["value"] += timedelta(minutes=5)
    store.claim_next(
        lease_owner="w3",
        claimed_at=clock["value"],
        lease_seconds=90,
    )
    store.fail(
        job_id=job_id,
        lease_owner="w3",
        lease_generation=3,
        failed_at=clock["value"],
        result={"run_status": "failed", "failure_code": "AttributeError"},
    )
    rec3 = scheduler.enqueue_if_authorized()
    assert rec3["status"] == "already_enqueued"
    assert store.get(job_id)["status"] == "failed"

    # Verify runway boundary check directly
    job_short_runway = dict(store.get(job_id))
    job_short_runway["payload"] = dict(job_short_runway["payload"])
    job_short_runway["payload"]["deadline_at"] = (
        clock["value"] + timedelta(hours=1)
    ).isoformat()
    assert not scheduler._should_recover_failed_job(
        job=job_short_runway, observed_at=clock["value"]
    )


@pytest.mark.unit
def test_fastapi_lifespan_has_no_external_research_construction() -> None:
    from server.app import lifespan
    from server.services.ai_shadow.ai_shadow_research_automation import (
        run_ai_shadow_research_automation_loop,
    )

    lifespan_source = inspect.getsource(lifespan)
    loop_source = inspect.getsource(run_ai_shadow_research_automation_loop)
    assert "build_strategy_research_write_service" not in lifespan_source
    assert "external=True" not in lifespan_source
    assert "build_ai_shadow_research_automation_service" not in loop_source
    assert "external=True" not in loop_source
    assert "generate_strategy_hypotheses" not in lifespan_source + loop_source
    assert "critique_strategy_backtest" not in lifespan_source + loop_source


def _state(tmp_path: Path) -> tuple[AppState, ShadowResearchPolicy]:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    config = ServerConfig(
        ai=AIProviderConfig(
            enabled=True,
            provider="deepseek",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
    )
    state = AppState()
    state.db = db
    state.config = config
    state.trading_controls = TradingControlState(db=db)
    policy = ShadowResearchPolicy(
        enabled=True,
        authorization=SHADOW_RESEARCH_POLICY_CONFIRMATION,
    )
    db.upsert_automation_policy_sync(
        policy_id=SHADOW_RESEARCH_POLICY_ID,
        payload=policy.to_dict(),
        updated_by=policy.updated_by,
    )
    return state, policy


def _enqueue_direct(
    *,
    state: AppState,
    policy: ShadowResearchPolicy,
    store: AiShadowResearchWorkerJobStore,
    enqueued_at: datetime,
) -> dict[str, object]:
    return store.enqueue(
        policy_fingerprint=content_fingerprint(policy.to_dict()),
        provider_config_fingerprint=shadow_research_provider_config_fingerprint(
            state.require_config().ai
        ),
        provider_window_policy_fingerprint=(
            DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.fingerprint
        ),
        available_at=enqueued_at,
        deadline_at=datetime(2026, 9, 7, 9, 0, tzinfo=SHANGHAI),
        enqueued_at=enqueued_at - timedelta(minutes=1),
    )
