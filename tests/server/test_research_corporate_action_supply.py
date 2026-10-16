"""Actual leased worker jobs supply prospective CA data without the manual API."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.market.capture import read_provider_capture
from data.market.corporate_actions import read_corporate_action_window
from data.source_policy import FREE_CN_RESEARCH_V1
from data.store import DataStore
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.jobs import SQLiteJobStore
from server.services import research_corporate_action_jobs as supply
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
    normalize_a_share_members,
)
from server.services.research.datasets import ensure_forward_seed_for_source
from server.services.research_observation_data_preparation import _publish_append
from server.services.verified_daily_market_data import VerifiedDailyMarketJobRequest
from server.services.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB
from server.workers import data_worker
from tests.server.test_dataset_corporate_actions import _response
from tests.server.test_deployment_scope_datasets import SECOND, _composed
from tests.server.test_recommendation_publication import _grant
from tests.server.test_research_observation_data_preparation import (
    supplied,  # noqa: F401
)
from tests.server.test_research_observations_journey import journey, start  # noqa: F401
from tests.server.test_verified_daily_market_range import _service as range_service
from tests.server.test_verified_interval_dataset import (
    DAYS,
    NOW,
    STOCK,
    _db,
)


def clocked_worker(monkeypatch, current, *, frame=None, after_call=None):
    from data.providers import tushare_corporate_actions as provider

    calls = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz or timezone.utc)

    monkeypatch.setattr(provider, "datetime", Clock)
    monkeypatch.setattr(data_worker, "datetime", Clock)

    def dividend(**query):
        calls.append(query)
        if after_call:
            after_call(len(calls))
        if frame is None:
            return pd.DataFrame()
        field = next(key for key in query if key != "fields")
        return frame[frame[field] == query[field]]

    monkeypatch.setattr(
        provider, "tushare_pro_client", lambda _: SimpleNamespace(dividend=dividend)
    )
    return calls


def install_grant(db, scope_id="b" * 64):
    repo = AutomationRunRepository(db.path)
    grant = _grant(deployment_scope_fingerprint=scope_id)
    repo.upsert_automation_policy_sync(
        policy_id="ai_recommendation_publication",
        payload=grant,
        updated_by="human:test",
    )
    db.get_automation_policy_sync = repo.get_automation_policy_sync
    return grant


def run_jobs(db, config, ids, current):
    store = SQLiteJobStore(db.path)
    for identity in ids:
        job = store.claim(
            supply.CORPORATE_ACTION_DAY_JOB,
            "sanitized-worker",
            now=current[0],
            job_id=identity,
        )
        assert job is not None
        asyncio.run(
            data_worker.execute_corporate_action_day_job(db, config, store, job)
        )
    return [store.get(identity) for identity in ids]


@pytest.mark.parametrize("simulation", [False, True])
def test_automatic_full_scope_seed_waits_for_canonical_worker_then_reuses_ca(
    tmp_path, monkeypatch, simulation
):
    db = _db(tmp_path)
    market = DataStore(tmp_path / "market")
    current = [NOW.replace(hour=14)]
    policy = MarketUniversePolicy(minimum_master_member_count=2, minimum_history_rows=2)
    scope = market_deployment_scope(policy)
    if simulation:
        from uuid import uuid4

        from server.contracts.research_observation_automation import (
            SIMULATION_VALIDATION_AUTHORIZE,
        )
        from server.services.ai_shadow_research_commands import (
            simulation_validation_defaults,
        )

        proposal = simulation_validation_defaults(current[0])
        grant = {
            **proposal,
            "enabled": True,
            "authorization": SIMULATION_VALIDATION_AUTHORIZE,
            "grant_id": str(uuid4()),
            "generation": str(uuid4()),
            "deployment_scope": scope,
            "deployment_scope_fingerprint": scope["deployment_scope_fingerprint"],
        }
        repo = AutomationRunRepository(db.path)
        repo.upsert_automation_policy_sync(
            policy_id="ai_shadow_research",
            payload={"simulation_validation": grant},
            updated_by="human:test",
        )
        db.get_automation_policy_sync = repo.get_automation_policy_sync
        assert repo.get_automation_policy_sync("ai_recommendation_publication") is None
    else:
        install_grant(db, scope["deployment_scope_fingerprint"])
    market.save_market_universe_snapshot(
        trade_date=DAYS[-1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol, SECOND.symbol]),
        source_metadata=[
            {"symbol": key.symbol, "display_name": "普通股"} for key in (STOCK, SECOND)
        ],
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
    )
    source = {
        "instruments": [{"symbol": STOCK.symbol, "instrument_type": "stock"}],
        "minimum_bars": 2,
        "forward_minimum_observations": 1,
        "source_selection": {
            "deployment_scope": scope,
            "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        },
    }
    config = SimpleNamespace(
        tushare_token="sanitized-not-a-secret",
        market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id,
    )
    calls = clocked_worker(monkeypatch, current)
    if simulation:
        from server.services.ai_shadow_research_workflow import (
            AiShadowResearchWorkflowMixin,
        )

        class WarmupWorkflow(AiShadowResearchWorkflowMixin):
            _db = db
            _data_store = market
            _state = SimpleNamespace(require_config=lambda: config)

            def get_policy(self):
                return SimpleNamespace(
                    simulation_validation=grant, research_end_date=None
                )

            def _policy_preflight(self, _policy):
                return None

            def _now(self):
                return current[0]

            def status(self):
                return {}

            async def _forward_validation_preflight(self, _grant):
                return None

            def _provider_batch_window_admission(self):
                return {"run_status": "deferred_for_provider_off_peak"}, None

            def _validation_seed_source(self, _policy, _grant):
                return source

            def _validation_seed_prepared(self, _source):
                return False

            def _require_deepseek_provider(self):
                raise AssertionError("warmup must not require or invoke a model")

            def _record_preflight(self, **kwargs):
                raise AssertionError(kwargs)

        prepared = asyncio.run(WarmupWorkflow().run_once())
        assert prepared["run_status"] == "awaiting_verified_research_inputs"
        assert prepared["provider_call_performed"] is False
        warmup = prepared["forward_validation"]
    else:
        warmup = ensure_forward_seed_for_source(
            db, config, source=source, now=current[0], data_store=market
        )
    assert warmup["status"] == "waiting"
    assert warmup["last_blocker"]["code"] == "forward_seed_verified_jobs_incomplete"
    warmup_service, primary, comparison = range_service(tmp_path, monkeypatch)
    for provider in (primary, comparison):
        original_fetch = provider.fetch_daily_bars

        def capture_at_current(request, original_fetch=original_fetch):
            return replace(
                original_fetch(request),
                started_at=current[0] - timedelta(seconds=1),
                completed_at=current[0],
            )

        monkeypatch.setattr(provider, "fetch_daily_bars", capture_at_current)
    store = SQLiteJobStore(db.path)
    for job_id in warmup["job_ids"]:
        job = store.claim(
            VERIFIED_DAILY_MARKET_JOB, "range-warmup", now=current[0], job_id=job_id
        )
        assert job is not None
        assert VerifiedDailyMarketJobRequest.from_payload(job.payload).is_range
        publication = warmup_service.run(job.payload, checked_at=current[0])
        store.finish(job.lease, now=current[0], result_ref=publication.result_ref)
        assert store.get(job_id).status == "succeeded"
    assert len(primary.calls) == len(comparison.calls) == 1
    pending = ensure_forward_seed_for_source(
        db, config, source=source, now=current[0], data_store=market
    )
    assert (
        pending["status"] == "waiting"
        and pending["last_blocker"]["code"] == "corporate_action_jobs_incomplete"
    )
    assert calls == []
    assert all(
        job.status == "succeeded"
        for job in run_jobs(db, config, pending["job_ids"], current)
    )
    ready = ensure_forward_seed_for_source(
        db, config, source=source, now=current[0], data_store=market
    )
    assert ready["status"] == "ready", ready
    objects = supply.ContentAddressedObjectStore(tmp_path / "research" / "objects")
    result = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(ready["dataset_id"]))
    )
    assert (
        result.corporate_action_evidence["coverage_start_date"] == DAYS[-1].isoformat()
    )
    assert result.snapshot.start_date == DAYS[0]
    assert (
        result.corporate_action_evidence["coverage_status"] == "provider_reported_only"
    )
    assert result.snapshot.session_memberships[-1].source_observation_ids
    assert len(calls) == 4 * len(pending["job_ids"])
    again = ensure_forward_seed_for_source(
        db, config, source=source, now=current[0], data_store=market
    )
    assert again["dataset_id"] == ready["dataset_id"]
    assert len(calls) == 4 * len(pending["job_ids"])
    with sqlite3.connect(db.path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM market_daily_provider_call_reservations WHERE upstream_group='tushare'"
        ).fetchone()[0] == len(calls)


def test_real_append_new_member_and_maintenance_preserves_old_raw_inputs(
    tmp_path, monkeypatch
):
    objects, composed = _composed(tmp_path)
    db = _db(tmp_path)
    install_grant(db)
    config = SimpleNamespace(
        tushare_token="sanitized",
        market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id,
    )
    first = replace(
        composed.snapshot,
        end_date=DAYS[0],
        instruments=(STOCK,),
        partitions=composed.snapshot.partitions[:1],
        session_memberships=composed.snapshot.session_memberships[:1],
        universe_policy_id="b" * 64,
    )
    current = [
        datetime.combine(DAYS[0], datetime.min.time(), timezone.utc)
        + timedelta(hours=14)
    ]
    calls = clocked_worker(monkeypatch, current)
    pending = supply.ensure_dataset_corporate_actions(
        db, config, snapshot=first, now=current[0], prospective_start=DAYS[0]
    )
    run_jobs(db, config, pending["job_ids"], current)
    ready = supply.ensure_dataset_corporate_actions(
        db, config, snapshot=first, now=current[0], prospective_start=DAYS[0]
    )
    before = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(ready["dataset_id"]))
    )
    original_id = before.snapshot.corporate_action_observation_ids[0]
    original = read_corporate_action_window(objects, objects.resolve_ref(original_id))
    first_day = json.loads(
        objects.read_bytes(objects.resolve_ref(original["day_observation_ids"][0]))
    )
    capture = read_provider_capture(
        objects,
        objects.resolve_ref(first_day["queries"][0]["capture_ref"]["object_id"]),
    )
    original_bytes = objects.read_bytes(capture.raw_object_ref)
    # Actual suffix adds SECOND as buy member and keeps held STOCK as maintenance.
    membership = replace(
        composed.snapshot.session_memberships[-1],
        instruments=(SECOND,),
        maintenance_instruments=(STOCK,),
    )
    # Actual verified shard jobs from _composed are reused; no provider relabel.
    jobs = SQLiteJobStore(db.path)
    suffix_ids = tuple(
        row["job_id"]
        for row in jobs.list_recent("market_daily_verified")
        if json.loads(row["payload_json"])["trade_date"] == DAYS[-1].isoformat()
    )
    assert suffix_ids
    service = SimpleNamespace(db=db, objects=objects)
    tail = _publish_append(
        service, before.snapshot, DAYS[-1], suffix_ids, (membership,), "b" * 64
    )
    tail_snapshot = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(tail["dataset_id"]))
    ).snapshot
    current[0] += timedelta(days=1)
    pending = supply.ensure_dataset_corporate_actions(
        db,
        config,
        snapshot=tail_snapshot,
        now=current[0],
        prospective_start=DAYS[0],
        previous_observation_ids=before.snapshot.corporate_action_observation_ids,
    )
    run_jobs(db, config, pending["job_ids"], current)
    ready = supply.ensure_dataset_corporate_actions(
        db,
        config,
        snapshot=tail_snapshot,
        now=current[0],
        prospective_start=DAYS[0],
        previous_observation_ids=before.snapshot.corporate_action_observation_ids,
    )
    after = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(ready["dataset_id"]))
    )
    assert after.snapshot.instruments == (STOCK, SECOND)
    assert after.snapshot.partitions[:1] == before.snapshot.partitions
    assert after.snapshot.session_memberships[-1].maintenance_instruments == (STOCK,)
    assert (
        after.corporate_action_evidence["day_observation_ids"][0]
        == original["day_observation_ids"][0]
    )
    assert objects.read_bytes(capture.raw_object_ref) == original_bytes
    assert (
        read_corporate_action_window(objects, objects.resolve_ref(original_id))
        == original
    )
    assert len(calls) == 8


def test_provider_window_revocation_and_budget_fence_without_more_sdk_calls(
    tmp_path, monkeypatch
):
    objects, composed = _composed(tmp_path)
    db = _db(tmp_path)
    grant = install_grant(db)
    config = SimpleNamespace(tushare_token="sanitized")
    snapshot = replace(composed.snapshot, universe_policy_id="b" * 64)
    current = [
        datetime.combine(DAYS[-1], datetime.min.time(), timezone.utc)
        + timedelta(hours=12)
    ]
    calls = clocked_worker(monkeypatch, current)
    waiting = supply.ensure_dataset_corporate_actions(
        db, config, snapshot=snapshot, now=current[0], prospective_start=DAYS[-1]
    )
    assert waiting["last_blocker"]["code"] == "tushare_dividend_update_window_pending"
    assert (
        calls == []
        and SQLiteJobStore(db.path).list_recent(supply.CORPORATE_ACTION_DAY_JOB) == []
    )
    current[0] += timedelta(hours=2)
    pending = supply.ensure_dataset_corporate_actions(
        db, config, snapshot=snapshot, now=current[0], prospective_start=DAYS[-1]
    )
    repo = AutomationRunRepository(db.path)

    def revoke(count):
        if count == 1:
            repo.upsert_automation_policy_sync(
                policy_id="ai_recommendation_publication",
                payload={**grant, "enabled": False},
                updated_by="human:test",
            )

    calls = clocked_worker(monkeypatch, current, after_call=revoke)
    result = run_jobs(db, config, pending["job_ids"], current)
    assert result[0].status != "succeeded" and len(calls) == 1
    assert result[0].result_ref is None
    # Restore existing permission; the shared budget still counts the spent call.
    repo.upsert_automation_policy_sync(
        policy_id="ai_recommendation_publication",
        payload=grant,
        updated_by="human:test",
    )
    from server.persistence.market_daily_call_budget import (
        reserve_market_daily_provider_call,
    )

    monkeypatch.setattr(
        data_worker,
        "reserve_market_daily_provider_call",
        lambda *args, **kwargs: reserve_market_daily_provider_call(
            *args, **kwargs, daily_limit=1
        ),
    )
    current[0] += timedelta(minutes=2)
    calls = clocked_worker(monkeypatch, current)
    result = run_jobs(db, config, pending["job_ids"], current)
    assert result[0].status == "queued"
    assert result[0].error == "market_daily_provider_call_budget_exhausted"
    assert calls == []


def test_real_observation_opt_in_supplies_window_and_revocation_blocks_future_jobs(
    journey, tmp_path, monkeypatch
):
    from server.services.research_observation_automation import (
        configure_observation_automation,
    )

    client, service, current, _, result_id = journey
    observation, _ = start(client, result_id)
    configured = configure_observation_automation(
        service,
        observation["id"],
        enabled=True,
        expected_generation=None,
        dataset_preparation_enabled=True,
    )
    permission = {
        "kind": "observation",
        "observation_id": observation["id"],
        "generation": configured["generation"],
    }
    objects, composed = _composed(tmp_path)
    snapshot = replace(composed.snapshot, universe_policy_id="b" * 64)
    current[0] = datetime.combine(
        DAYS[-1], datetime.min.time(), timezone.utc
    ) + timedelta(hours=14)
    config = SimpleNamespace(tushare_token="sanitized")
    calls = clocked_worker(monkeypatch, current)
    pending = supply.ensure_dataset_corporate_actions(
        service.db,
        config,
        snapshot=snapshot,
        now=current[0],
        prospective_start=DAYS[-1],
        permission=permission,
    )
    assert all(
        row.status == "succeeded"
        for row in run_jobs(service.db, config, pending["job_ids"], current)
    )
    ready = supply.ensure_dataset_corporate_actions(
        service.db,
        config,
        snapshot=snapshot,
        now=current[0],
        prospective_start=DAYS[-1],
        permission=permission,
    )
    assert ready["status"] == "ready" and len(calls) == 4
    before = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(ready["dataset_id"]))
    )
    current[0] += timedelta(days=1)
    pending = supply.ensure_dataset_corporate_actions(
        service.db,
        config,
        snapshot=before.snapshot,
        now=current[0],
        prospective_start=DAYS[-1],
        permission=permission,
        previous_observation_ids=before.snapshot.corporate_action_observation_ids,
    )
    configure_observation_automation(
        service,
        observation["id"],
        enabled=True,
        expected_generation=configured["generation"],
        dataset_preparation_enabled=False,
    )
    assert (
        run_jobs(service.db, config, pending["job_ids"], current)[0].status
        != "succeeded"
    )
    assert len(calls) == 4


def test_slow_canonical_replay_does_not_hold_account_write_lock_and_revoke_blocks_catalog(
    tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from data.dataset.catalog import DatasetCatalog

    objects, composed = _composed(tmp_path)
    db = _db(tmp_path)
    grant = install_grant(db)
    config = SimpleNamespace(tushare_token="sanitized")
    snapshot = replace(composed.snapshot, universe_policy_id="b" * 64)
    current = [
        datetime.combine(DAYS[-1], datetime.min.time(), timezone.utc)
        + timedelta(hours=14)
    ]
    clocked_worker(monkeypatch, current)
    pending = supply.ensure_dataset_corporate_actions(
        db, config, snapshot=snapshot, now=current[0], prospective_start=DAYS[-1]
    )
    run_jobs(db, config, pending["job_ids"], current)
    catalog = DatasetCatalog(tmp_path / "research")
    before = catalog.list_daily_bar_datasets()
    replaying, release = threading.Event(), threading.Event()
    real_read = supply.read_daily_bar_dataset

    def slow_read(*args, **kwargs):
        replaying.set()
        assert release.wait(5)
        return real_read(*args, **kwargs)

    monkeypatch.setattr(supply, "read_daily_bar_dataset", slow_read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            supply.ensure_dataset_corporate_actions,
            db,
            config,
            snapshot=snapshot,
            now=current[0],
            prospective_start=DAYS[-1],
        )
        assert replaying.wait(5)
        # A real competing app-DB write completes while the full read is paused.
        AutomationRunRepository(db.path).upsert_automation_policy_sync(
            policy_id="ai_recommendation_publication",
            payload={**grant, "enabled": False},
            updated_by="human:test",
        )
        release.set()
        with pytest.raises(ValueError, match="publication_grant_changed"):
            future.result(timeout=5)
    assert catalog.list_daily_bar_datasets() == before


@pytest.mark.usefixtures("supplied")
def test_slow_append_replay_allows_revoke_before_catalog_admission(
    supplied, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from server.services import research_observation_data_preparation as preparation
    from tests.server.test_research_observation_data_preparation import (
        execute,
        prepare,
        toggle,
    )

    client, observations, _, observation, *_ = supplied
    policy = toggle(supplied)
    pending = prepare(supplied)[0]
    assert execute(supplied, pending["pending_job_ids"][0]).status == "succeeded"
    replaying, release = threading.Event(), threading.Event()
    real_append = preparation._publish_append

    def slow_append(*args, **kwargs):
        assert kwargs["register"] is False
        replaying.set()
        assert release.wait(5)
        return real_append(*args, **kwargs)

    monkeypatch.setattr(preparation, "_publish_append", slow_append)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(prepare, supplied)
        assert replaying.wait(5)
        toggle(supplied, preparation_enabled=False, generation=policy["generation"])
        release.set()
        assert future.result(timeout=5) == []
    assert observations.repository.get(observation["id"])["publications"] == []
