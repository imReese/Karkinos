"""Forward batches reuse real verified CAS while current permission stays fresh."""

import asyncio
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from server.db import AppDatabase
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_daily_call_budget import (
    BUDGET_DEFERRED_CODE,
    MarketDailyProviderBudgetDeferred,
    reserve_market_daily_provider_call,
)
from server.workers import data_worker as worker
from tests.server.test_research_observation_data_preparation import (
    BASKET,
    CONFIG,
    FUTURE,
    prepare,
    supplied,  # noqa: F401
    toggle,
)
from tests.server.test_research_observation_inputs import NOW, source
from tests.server.test_research_observations_journey import (
    journey,  # noqa: F401
    start,
)
from tests.server.test_verified_daily_worker_gate import DAY, _calendar


def test_existing_forty_stock_and_new_daily_jobs_keep_the_exact_scope_guard(
    supplied, monkeypatch
):
    from core.types import InstrumentKey, InstrumentType
    from server.services.research import (
        research_observation_data_preparation as preparation,
    )

    _, observations, current, _, _, _, jobs, _ = supplied
    toggle(supplied)
    report = prepare(supplied)[0]
    original = jobs.get(report["pending_job_ids"][0])
    assert original is not None
    day = datetime.fromisoformat(original.payload["trade_date"]).date()
    expected = tuple(
        InstrumentKey(str(600000 + index), InstrumentType.STOCK) for index in range(101)
    )
    monkeypatch.setattr(
        preparation, "ResearchObservationService", lambda _: observations
    )
    monkeypatch.setattr(
        preparation,
        "_dynamic_memberships",
        lambda *args, **kwargs: (
            SimpleNamespace(
                partition_date=day, instruments=expected, maintenance_instruments=()
            ),
        ),
    )

    def job_for(keys):
        return replace(
            original,
            payload={
                **original.payload,
                "instruments": [
                    {"symbol": key.symbol, "instrument_type": key.instrument_type.value}
                    for key in keys
                ],
            },
        )

    for members in (expected[:40], expected[:100], expected[100:]):
        preparation.require_observation_preparation_job(
            observations.db, CONFIG, job_for(members)
        )
    # Preserving old batches never permits an arbitrary overlapping subset.
    with pytest.raises(ValueError, match="job_scope_mismatch"):
        preparation.require_observation_preparation_job(
            observations.db, CONFIG, job_for(expected[1:41])
        )


def test_forward_waiting_preserves_real_budget_resume_time(supplied):
    from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR

    _, observations, current, _, _, _, jobs, _ = supplied
    toggle(supplied)
    report = prepare(supplied)[0]
    job = jobs.claim(
        worker.VERIFIED_DAILY_MARKET_JOB,
        "budget-fixture",
        now=current[0],
        job_id=report["pending_job_ids"][0],
    )
    assert job is not None
    reserve_market_daily_provider_call(
        observations.db.path,
        job.lease,
        BAOSTOCK_DAILY_BAR_DESCRIPTOR,
        now=current[0],
        daily_limit=1,
    )
    with pytest.raises(MarketDailyProviderBudgetDeferred) as deferred:
        reserve_market_daily_provider_call(
            observations.db.path,
            job.lease,
            BAOSTOCK_DAILY_BAR_DESCRIPTOR,
            now=current[0],
            daily_limit=1,
        )
    waiting = prepare(supplied)[0]
    assert waiting["status"] == "waiting"
    assert waiting["last_blocker"] == {
        "code": BUDGET_DEFERRED_CODE,
        "available_at": deferred.value.available_at.isoformat(timespec="microseconds"),
    }


@pytest.mark.parametrize("revoke_during_capture", [False, True])
def test_forward_batch_inherits_verified_reads_and_reopens_permission(
    supplied, monkeypatch, revoke_during_capture
):
    import data.dataset.reader as reader

    _, observations, current, observation, prefix, verified, jobs, state = supplied
    current[0] = FUTURE + timedelta(days=2)
    policy = toggle(supplied)
    if revoke_during_capture:
        state["after_fetch"] = lambda _: toggle(
            supplied,
            preparation_enabled=False,
            generation=policy["generation"],
        )
    cold = reader._read_daily_bar_dataset
    warmup_reads = []

    def track(objects, ref):
        if ref.dataset_id == prefix["dataset_id"]:
            warmup_reads.append(ref)
        return cold(objects, ref)

    class TimedService:
        def run(self, payload, **kwargs):
            return verified.run(payload, checked_at=current[0], **kwargs)

    async def presence(_controls, _name, _owner, work):
        await work

    real_sleep = asyncio.sleep
    cycles = 0

    async def stop_after_two_batches(seconds):
        nonlocal cycles
        if seconds == 5:
            cycles += 1
            if cycles == 2:
                raise asyncio.CancelledError
            await real_sleep(0)
        else:
            await real_sleep(seconds)

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", track)
    monkeypatch.setattr(worker, "AppDatabase", lambda: observations.db)
    monkeypatch.setattr(worker, "run_with_presence", presence)
    monkeypatch.setattr(worker, "datetime", SimpleNamespace(now=lambda tz: current[0]))
    monkeypatch.setattr(
        worker,
        "VerifiedDailyMarketDataService",
        lambda *args: TimedService(),
    )
    monkeypatch.setattr(
        worker,
        "enqueue_latest_daily_market_collection_jobs",
        lambda *args, **kwargs: SimpleNamespace(planned_count=0, trade_date=None),
    )
    monkeypatch.setattr(worker.asyncio, "sleep", stop_after_two_batches)
    config = SimpleNamespace(**vars(CONFIG), market_calendar_auto_sync=False)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.run_data_worker(config))

    observation_jobs = jobs.list_verified_observation_jobs(
        observation["id"], start_date="2026-09-21", end_date="2026-09-23"
    )
    assert len(observation_jobs) == 3
    if revoke_during_capture:
        assert state["calls"] == ["baostock"]
        assert not any(job.status == "succeeded" for job in observation_jobs)
        assert len(warmup_reads) == 1
    else:
        assert all(job.status == "succeeded" for job in observation_jobs)
        assert state["calls"] == ["baostock", "akshare_tencent"] * 3
        # Main preparation verifies first, all three real job threads reuse
        # that exact Dataset, and the next batch must perform a fresh cold read.
        assert len(warmup_reads) == 2


def test_each_observation_releases_its_verified_scope(supplied, monkeypatch):
    import data.dataset.reader as reader
    from data.dataset.manifest import publish_daily_bar_dataset_manifest
    from data.dataset.model import DatasetRef

    client, observations, current, first, prefix, _, _, state = supplied
    current[0] = NOW + timedelta(seconds=1)
    first_ref = DatasetRef(observations.objects.resolve_ref(prefix["dataset_id"]))
    snapshot = reader.read_daily_bar_dataset(observations.objects, first_ref).snapshot
    second_ref = publish_daily_bar_dataset_manifest(
        observations.objects,
        replace(snapshot, cutoff=snapshot.cutoff + timedelta(microseconds=1)),
    )
    row = source(SimpleNamespace(dataset_id=second_ref.dataset_id))
    config = json.loads(row["config_json"])
    config["assets"] = [
        {"symbol": item.symbol, "asset_class": item.instrument_type.value}
        for item in BASKET
    ]
    result_id = asyncio.run(
        observations.db.save_backtest_result(
            config_json=json.dumps(config),
            metrics_json=row["metrics_json"],
            initial_cash=100000,
            final_equity=100000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    second, _ = start(client, result_id)
    toggle(supplied)
    response = client.put(
        f"/api/research-observations/{second['id']}/automation",
        json={"enabled": True, "dataset_preparation_enabled": True},
    )
    assert response.status_code == 200, response.text
    # Two independently frozen books may share earlier bar partitions while
    # retaining different source/append manifests. Neither book owns a cache
    # lifetime extending into the next book's canonical input verification.
    for observation, anchor in ((first, second_ref), (second, first_ref)):
        AutomationRunRepository(observations.db.path).upsert_automation_run_sync(
            {
                "run_id": f"research-observation-automation:{observation['id']}:latest:data",
                "run_type": "research_observation_dataset_preparation",
                "run_date": current[0].date().isoformat(),
                "status": "completed",
                "source_ref": observation["id"],
                "execution_mode": "research_inputs",
                "payload": {"dataset_id": anchor.dataset_id},
            }
        )
    cold = reader._read_daily_bar_dataset
    reads = []

    def track(objects, ref):
        reads.append(ref.dataset_id)
        return cold(objects, ref)

    async def presence(_controls, _name, _owner, work):
        await work

    async def stop_after_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", track)
    monkeypatch.setattr(worker, "AppDatabase", lambda: observations.db)
    monkeypatch.setattr(worker, "run_with_presence", presence)
    monkeypatch.setattr(worker, "datetime", SimpleNamespace(now=lambda tz: current[0]))
    monkeypatch.setattr(
        worker,
        "enqueue_latest_daily_market_collection_jobs",
        lambda *args, **kwargs: SimpleNamespace(planned_count=0, trade_date=None),
    )
    monkeypatch.setattr(worker.asyncio, "sleep", stop_after_cycle)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            worker.run_data_worker(
                SimpleNamespace(**vars(CONFIG), market_calendar_auto_sync=False)
            )
        )
    assert Counter(reads) == {first_ref.dataset_id: 2, second_ref.dataset_id: 2}
    assert state["calls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision_day,full_scope_active,collects",
    [(DAY, True, False), (DAY + timedelta(days=2), True, True), (DAY, False, True)],
)
async def test_active_full_scope_keeps_trading_day_budget_for_after_close(
    tmp_path, monkeypatch, decision_day, full_scope_active, collects
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    now = datetime.combine(decision_day, datetime.min.time(), tzinfo=timezone.utc)
    db._market_calendar._now = lambda tz=None: now
    calendar = db.upsert_market_calendar_snapshot_sync(_calendar())
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=DAY.year,
        source_fingerprint=calendar["source_fingerprint"],
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )
    store = SQLiteJobStore(db.path)
    histories = [
        store.enqueue(kind, {"fixture": "historical"}, now=now)
        for kind in (
            worker.DAILY_MARKET_COLLECTION_JOB,
            worker.VERIFIED_DAILY_MARKET_JOB,
        )
    ]

    async def presence(_controls, _name, _owner, work):
        await work

    async def complete(store, job, _service, **kwargs):
        store.finish(job.lease, now=now, result_ref="fixture:complete")

    async def stop_after_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "AppDatabase", lambda: db)
    monkeypatch.setattr(
        "server.workers.data_worker.AutomationRunRepository.list_observation_automation_policies",
        lambda _: [
            {
                "observation_id": "da6a8efb-fc60-4c0a-80ac-f8d59d94fbe4",
                "dataset_preparation_enabled": True,
            }
        ],
    )
    monkeypatch.setattr(worker, "datetime", SimpleNamespace(now=lambda tz: now))
    monkeypatch.setattr(worker, "run_with_presence", presence)
    monkeypatch.setattr(
        worker,
        "run_research_observation_data_preparation_once",
        lambda *args, **kwargs: [
            {"full_scope_input_active": full_scope_active, "pending_job_ids": []}
        ],
    )
    monkeypatch.setattr(
        worker,
        "enqueue_latest_daily_market_collection_jobs",
        lambda *args, **kwargs: SimpleNamespace(planned_count=0, trade_date=None),
    )
    monkeypatch.setattr(worker, "execute_daily_market_collection_job", complete)
    monkeypatch.setattr(worker, "execute_verified_daily_market_job", complete)
    monkeypatch.setattr(worker.asyncio, "sleep", stop_after_cycle)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_data_worker(SimpleNamespace(market_calendar_auto_sync=False))
    for old in histories:
        current = store.get(old.job_id)
        assert current.status == ("succeeded" if collects else "queued")
        assert current.attempt == (1 if collects else 0)
