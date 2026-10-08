"""Explicit input supply through two providers, durable jobs and frozen prefixes."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.market.contracts import DailyBarRequest
from data.provider_registry import ProviderRegistration, ProviderRegistry
from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.providers.tencent import AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR
from data.source_policy import FREE_CN_RESEARCH_V1
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.jobs import SQLiteJobStore
from server.services import research_observation_data_preparation as preparation
from server.services.market_calendar_dates import (
    resolve_verified_closed_trading_dates_in_range,
)
from server.services.research_datasets import publish_verified_interval_dataset
from server.services.research_observation_automation import (
    run_research_observation_automation_once,
)
from server.services.research_paper_books import ResearchPaperBookService
from server.services.verified_daily_market_data import (
    VerifiedDailyMarketDataService,
    VerifiedDailyMarketJobRequest,
)
from server.services.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB
from server.workers.data_worker import (
    _require_current_verified_daily_market_job,
    execute_verified_daily_market_job,
)
from tests.server.test_dataset_corporate_actions import _observe
from tests.server.test_research_observation_inputs import (
    DAYS,
    NOW,
    STOCK,
    calendar,
    dataset,
    source,
)
from tests.server.test_research_observations_journey import journey, start  # noqa: F401
from tests.server.test_verified_daily_market_data import FakeDailyProvider

pytestmark = pytest.mark.product_smoke
ETF = InstrumentKey("510300", InstrumentType.ETF)
BASKET = (ETF, STOCK)
CONFIG = SimpleNamespace(
    market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id
)
FUTURE = datetime(2026, 9, 21, 8, 10, tzinfo=timezone.utc)


@pytest.fixture
def supplied(journey, monkeypatch):
    client, observations, current, _, _ = journey
    state = {"calls": [], "after_fetch": None, "partial": False, "conflict": False}

    class SyntheticProvider(FakeDailyProvider):
        def fetch_daily_bars(self, request):
            batch = super().fetch_daily_bars(request)
            day = request.start_date
            captured = datetime.combine(
                day, datetime.min.time(), tzinfo=timezone.utc
            ) + timedelta(hours=8)
            rows = []
            moves = tuple(
                map(Decimal, ("0", "0", "0", "-0.3", "0.4", "0.41", "0.42", "0.43"))
            )
            for row in batch.rows:
                scale = Decimal("0.2") if row.instrument == ETF else Decimal("1")
                move = moves[DAYS.index(day)] if day in DAYS else Decimal("0")
                close = (
                    row.close_value + move * scale + state.get("offset", Decimal("0"))
                )
                rows.append(
                    replace(
                        row,
                        session_date=day,
                        event_time=captured - timedelta(hours=1),
                        open_value=close,
                        close_value=close,
                        high_value=close + Decimal("0.01"),
                        low_value=close - Decimal("0.01"),
                        amount=(row.amount * close / row.close_value).quantize(
                            Decimal("0.01")
                        ),
                    )
                )
            rows = tuple(rows)
            if state["partial"]:
                rows = tuple(row for row in rows if row.instrument != ETF)
            if state["conflict"] and self.descriptor.provider == "akshare_tencent":
                rows = tuple(
                    replace(
                        row,
                        close_value=row.close_value + 1,
                        high_value=row.high_value + 1,
                    )
                    for row in rows
                )
            if state["after_fetch"] is not None:
                state["after_fetch"](self.descriptor.provider)
            return replace(
                batch,
                rows=rows,
                raw_payload=batch.raw_payload + str(state.get("offset", "0")).encode(),
                started_at=captured
                + timedelta(minutes=1 if state.get("offset") else 0)
                - timedelta(seconds=1),
                completed_at=captured
                + timedelta(minutes=1 if state.get("offset") else 0),
            )

    descriptors = (BAOSTOCK_DAILY_BAR_DESCRIPTOR, AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR)
    registry = ProviderRegistry(
        tuple(
            ProviderRegistration(
                name=descriptor.provider,
                upstream_group=descriptor.upstream_group,
                daily_bar_factory=lambda descriptor=descriptor: SyntheticProvider(
                    descriptor, call_log=state["calls"]
                ),
            )
            for descriptor in descriptors
        )
    )
    monkeypatch.setattr(
        "server.services.verified_daily_market_data.provider_registry_for_config",
        lambda *args, **kwargs: registry,
    )
    verified = VerifiedDailyMarketDataService(
        observations.db.path.parent / "research", CONFIG
    )
    jobs = SQLiteJobStore(observations.db.path)
    dates = resolve_verified_closed_trading_dates_in_range(
        observations.db, NOW, start_date=DAYS[0], end_date=DAYS[4]
    )
    source_jobs = []
    for resolved in dates:
        request = VerifiedDailyMarketJobRequest(
            datetime.fromisoformat(resolved.trade_date).date(),
            BASKET,
            FREE_CN_RESEARCH_V1.policy_id,
            resolved.calendar_evidence_refs,
        )
        enqueued = jobs.enqueue(
            VERIFIED_DAILY_MARKET_JOB, request.to_payload(), now=NOW
        )
        claimed = jobs.claim(
            VERIFIED_DAILY_MARKET_JOB, "source", now=NOW, job_id=enqueued.job_id
        )
        published = verified.run(claimed.payload, checked_at=NOW)
        jobs.finish(claimed.lease, now=NOW, result_ref=published.result_ref)
        source_jobs.append(enqueued.job_id)
    prefix = publish_verified_interval_dataset(
        observations.db.path.parent / "research",
        DailyBarRequest(BASKET, DAYS[0], DAYS[4]),
        db=observations.db,
        job_ids=tuple(source_jobs),
    )
    row = source(SimpleNamespace(dataset_id=prefix["dataset_id"]))
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
    observation, _ = start(client, result_id)
    state["calls"].clear()
    current[0] = FUTURE
    return client, observations, current, observation, prefix, verified, jobs, state


def toggle(supplied, *, preparation_enabled=True, generation=None, enabled=True):
    client, _, _, observation, *_ = supplied
    response = client.put(
        f"/api/research-observations/{observation['id']}/automation",
        json={
            "enabled": enabled,
            "dataset_preparation_enabled": preparation_enabled,
            "expected_generation": generation,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def prepare(supplied):
    _, observations, current, *_ = supplied
    return preparation.run_research_observation_data_preparation_once(
        observations.db, CONFIG, now=current[0]
    )


async def execute_async(supplied, job_id, *, completed=None):
    _, observations, current, _, _, verified, jobs, _ = supplied
    now = datetime.now(timezone.utc)
    job = jobs.claim(VERIFIED_DAILY_MARKET_JOB, "future", now=now, job_id=job_id)
    grant = preparation.observation_daily_job_grant(job.payload)

    class TimedService:
        def run(self, payload, **kwargs):
            try:
                return verified.run(payload, checked_at=current[0], **kwargs)
            finally:
                if completed is not None:
                    completed.set()

    await execute_verified_daily_market_job(
        jobs,
        job,
        TimedService(),
        request_validator=lambda: _require_current_verified_daily_market_job(
            observations.db, CONFIG, job
        ),
        before_provider_fetch=lambda _: _require_current_verified_daily_market_job(
            observations.db, CONFIG, job
        ),
        publication_guard=lambda action: AutomationRunRepository(
            observations.db.path
        ).publish_observation_dataset(
            observation_id=grant["observation_id"],
            generation=grant["generation"],
            stop_requested=lambda: False,
            publish=action,
        ),
        finish_guard=lambda conn: preparation.guard_observation_data_preparation(
            conn, grant, lambda: False
        ),
    )
    return jobs.get(job_id)


def execute(supplied, job_id):
    return asyncio.run(execute_async(supplied, job_id))


def test_explicit_supply_appends_full_basket_then_local_publication_and_restart(
    supplied,
):
    client, observations, _, observation, prefix, _, jobs, state = supplied
    assert prepare(supplied) == []
    toggle(supplied, preparation_enabled=False)
    assert prepare(supplied) == []
    policy = client.get(f"/api/research-observations/{observation['id']}").json()[
        "automation"
    ]
    enabled = toggle(supplied, generation=policy["generation"])
    pending = prepare(supplied)[0]
    assert pending["status"] == "waiting"
    assert len(pending["job_ids"]) == 1
    queued = jobs.get(pending["job_ids"][0])
    assert (
        VerifiedDailyMarketJobRequest.from_payload(queued.payload).instruments == BASKET
    )
    assert (
        queued.payload["observation_automation"]["generation"] == enabled["generation"]
    )
    assert state["calls"] == []
    assert observations.repository.get(observation["id"])["version"] == 0
    assert execute(supplied, queued.job_id).status == "succeeded"
    ready = prepare(supplied)[0]
    assert ready["status"] == "completed", ready
    old = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(prefix["dataset_id"])),
    ).snapshot
    new = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(ready["dataset_id"])),
    ).snapshot
    assert new.partitions[: len(old.partitions)] == old.partitions
    assert new.instruments == old.instruments == BASKET
    assert len(new.partitions) == len(old.partitions) + 1
    assert (
        run_research_observation_automation_once(observations)[0]["status"]
        == "completed"
    )
    assert len(observations.repository.get(observation["id"])["publications"]) == 1
    assert state["calls"] == ["baostock", "akshare_tencent"]
    newer = toggle(supplied, generation=enabled["generation"])
    reopened = prepare(supplied)[0]
    assert reopened["generation"] == newer["generation"]
    assert reopened["dataset_id"] == ready["dataset_id"]
    assert reopened["job_ids"] == []
    assert state["calls"] == ["baostock", "akshare_tencent"]


@pytest.mark.parametrize("bad_input", ["partial", "conflict"])
def test_bad_two_source_input_never_materializes_ready_interval(supplied, bad_input):
    _, observations, _, observation, _, _, _, state = supplied
    toggle(supplied)
    pending = prepare(supplied)[0]
    state[bad_input] = True
    assert execute(supplied, pending["job_ids"][0]).status != "succeeded"
    assert prepare(supplied)[0]["status"] == "waiting"
    assert observations.repository.get(observation["id"])["version"] == 0
    assert not any(
        entry.end_date == DAYS[5]
        for entry in DatasetCatalog(
            observations.db.path.parent / "research"
        ).list_daily_bar_datasets()
    )


def test_revoke_during_first_fetch_prevents_second_fetch_and_visible_publication(
    supplied,
):
    _, observations, _, observation, _, _, _, state = supplied
    policy = toggle(supplied)
    pending = prepare(supplied)[0]
    state["after_fetch"] = lambda _: toggle(
        supplied, preparation_enabled=False, generation=policy["generation"]
    )
    assert execute(supplied, pending["job_ids"][0]).status != "succeeded"
    assert state["calls"] == ["baostock"]
    assert prepare(supplied) == []
    assert observations.repository.get(observation["id"])["version"] == 0
    assert not any(
        entry.end_date == DAYS[5]
        for entry in DatasetCatalog(
            observations.db.path.parent / "research"
        ).list_daily_bar_datasets()
    )


def test_ready_late_data_never_backfills_missed_target(supplied):
    _, observations, current, observation, *_ = supplied
    toggle(supplied)
    pending = prepare(supplied)[0]
    execute(supplied, pending["job_ids"][0])
    current[0] = datetime(2026, 9, 22, 1, 30, tzinfo=timezone.utc)
    assert prepare(supplied)[0]["status"] == "completed"
    scheduled = run_research_observation_automation_once(observations)[0]
    assert (
        scheduled["last_blocker"]["code"]
        == "observation_automation_publication_window_missed"
    )
    assert observations.repository.get(observation["id"])["publications"] == []


def test_cancel_inflight_provider_thread_cannot_continue_fetch_or_publish(supplied):
    _, observations, _, _, _, _, jobs, state = supplied
    toggle(supplied)
    pending = prepare(supplied)[0]
    entered, release, completed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def delay_first_fetch(_):
        entered.set()
        assert release.wait(5)

    state["after_fetch"] = delay_first_fetch

    async def cancel():
        task = asyncio.create_task(
            execute_async(supplied, pending["job_ids"][0], completed=completed)
        )
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert await asyncio.to_thread(completed.wait, 5)

    asyncio.run(cancel())
    assert state["calls"] == ["baostock"]
    assert jobs.get(pending["job_ids"][0]).status != "succeeded"
    assert not any(
        entry.end_date == DAYS[5]
        for entry in DatasetCatalog(
            observations.db.path.parent / "research"
        ).list_daily_bar_datasets()
    )


def test_pause_stops_supply_and_paper_permission_separately_restores_valuation_inputs(
    supplied,
):
    client, observations, current, observation, *_ = supplied
    current[0] = NOW
    ResearchPaperBookService(observations.db, clock=lambda: current[0]).start(
        observation["id"], request_id=str(uuid4()), initial_cash=Decimal("100000")
    )
    policy = toggle(supplied)
    response = client.post(
        f"/api/research-observations/{observation['id']}/pause",
        json={"request_id": str(uuid4()), "expected_version": 0},
    )
    assert response.status_code == 200, response.text
    current[0] = FUTURE
    blocked = prepare(supplied)[0]
    assert blocked["status"] == "blocked"
    assert blocked["last_blocker"]["code"] == "observation_data_preparation_paused"
    response = client.put(
        f"/api/research-observations/{observation['id']}/automation",
        json={
            "enabled": False,
            "paper_settlement_enabled": True,
            "expected_generation": policy["generation"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["dataset_preparation_enabled"] is True
    assert prepare(supplied)[0]["status"] == "waiting"
    assert observations.repository.get(observation["id"])["lifecycle"] == "paused"


@pytest.mark.parametrize("invalid", ["unverified", "missing_session"])
def test_invalid_source_history_blocks_before_any_daily_job(journey, invalid):
    client, observations, current, original, _ = journey
    if invalid == "unverified":
        _, ref = dataset(observations.db.path.parent / "research", verified=False)
    else:
        snapshot = read_daily_bar_dataset(observations.objects, original).snapshot
        ref = publish_daily_bar_dataset_manifest(
            observations.objects,
            replace(
                snapshot, partitions=(snapshot.partitions[0], *snapshot.partitions[2:])
            ),
        )
    row = source(ref)
    result_id = asyncio.run(
        observations.db.save_backtest_result(
            config_json=row["config_json"],
            metrics_json=row["metrics_json"],
            initial_cash=100000,
            final_equity=100000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    observation, _ = start(client, result_id)
    response = client.put(
        f"/api/research-observations/{observation['id']}/automation",
        json={"enabled": False, "dataset_preparation_enabled": True},
    )
    assert response.status_code == 200, response.text
    current[0] = FUTURE
    report = preparation.run_research_observation_data_preparation_once(
        observations.db, CONFIG, now=current[0]
    )[0]
    assert report["status"] == "blocked"
    assert report["last_blocker"]["code"] == (
        "observation_data_preparation_source_mismatch"
        if invalid == "unverified"
        else "observation_data_preparation_source_calendar_mismatch"
    )
    assert (
        SQLiteJobStore(observations.db.path).list_recent(VERIFIED_DAILY_MARKET_JOB)
        == []
    )


def test_supply_drives_real_automatic_paper_fills_fees_and_later_marks(supplied):
    client, observations, current, observation, _, _, _, state = supplied
    current[0] = NOW
    books = ResearchPaperBookService(observations.db, clock=lambda: current[0])
    started = books.start(
        observation["id"], request_id=str(uuid4()), initial_cash=Decimal("100000")
    )
    current[0] += timedelta(seconds=1)
    response = client.put(
        f"/api/research-observations/{observation['id']}/automation",
        json={
            "enabled": True,
            "dataset_preparation_enabled": True,
            "paper_settlement_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        run_research_observation_automation_once(observations)[0]["status"]
        == "completed"
    )
    target = observations.repository.get(observation["id"])["publications"][0]
    assert target["decision_session"] == DAYS[4].isoformat()
    assert books.get(observation["id"])["fills"] == []

    current[0] = FUTURE
    pending = prepare(supplied)[0]
    assert execute(supplied, pending["pending_job_ids"][0]).status == "succeeded"
    assert prepare(supplied)[0]["status"] == "completed"
    run_research_observation_automation_once(observations)
    first = books.get(observation["id"])
    assert first["version"] > started["version"]
    assert {fill["symbol"] for fill in first["fills"]} == {
        item.symbol for item in BASKET
    }
    assert all(fill["session"] == DAYS[5].isoformat() for fill in first["fills"])
    assert Decimal(first["performance"]["fees_paid"]) > 0
    assert Decimal(first["performance"]["slippage_cost"]) > 0
    assert Decimal(first["performance"]["cash"]) < Decimal("100000")
    assert first["performance"]["benchmark_start_session"] == DAYS[5].isoformat()
    assert first["performance"]["costs_already_in_equity"] is True
    assert first["performance"]["account_authority"] is False

    # Operational status can be rebuilt; the book's accepted inputs must still
    # keep their exact partitions when preparation resumes after its loss.
    with sqlite3.connect(observations.db.path) as conn:
        conn.execute(
            "DELETE FROM automation_runs WHERE run_id=?",
            (f"research-observation-automation:{observation['id']}:latest:data",),
        )

    current[0] = FUTURE + timedelta(days=1)
    second_pending = prepare(supplied)[0]
    assert len(second_pending["pending_job_ids"]) == 1
    assert execute(supplied, second_pending["pending_job_ids"][0]).status == "succeeded"
    assert prepare(supplied)[0]["status"] == "completed"
    run_research_observation_automation_once(observations)
    second = books.get(observation["id"])
    assert second["version"] > first["version"]
    assert second["steps"][0] == first["steps"][0]
    assert second["last_settled_session"] == DAYS[6].isoformat()
    assert second["performance"]["settled_sessions"] == 2
    assert Decimal(second["performance"]["pnl_reconciliation_residual"]) == 0
    assert second["performance"]["return_basis"] == "price_only"
    assert second["performance"]["corporate_action_coverage_complete"] is False
    assert state["calls"] == ["baostock", "akshare_tencent"] * 2


@pytest.fixture
def long_supplied(supplied):
    client, observations, current, _, _, verified, jobs, state = supplied
    history = tuple(
        map(
            date.fromisoformat, ("2024-01-02", "2024-06-03", "2024-09-02", "2025-01-03")
        )
    )
    future = tuple(
        map(
            date.fromisoformat, ("2025-01-06", "2025-12-31", "2026-09-21", "2026-09-22")
        )
    )
    for year in (2024, 2025, 2026):
        observations.db.upsert_market_calendar_snapshot_sync(
            calendar(year=year, trading_days=history + future)
        )
        observations.db.update_market_calendar_verification_sync(
            exchange="SSE",
            year=year,
            source_fingerprint="a" * 64,
            verification_status="verified",
            official_source_url="https://example.test/calendar",
            official_source_fingerprint="b" * 64,
            verified_by="synthetic fixture",
        )
    _, original = dataset(observations.db.path.parent / "research", days=history)
    row = source(original)
    config = json.loads(row["config_json"])
    config.update(start_date=history[0].isoformat(), end_date=history[-1].isoformat())
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
    current[0] = NOW
    observation, _ = start(client, result_id)
    observation = observations.repository.get(observation["id"])
    current[0] = FUTURE
    state["calls"].clear()
    return (
        client,
        observations,
        current,
        observation,
        {"dataset_id": original.dataset_id},
        verified,
        jobs,
        state,
    )


def test_long_history_appends_bounded_batches_and_reuses_frozen_prior_batch(
    long_supplied,
):
    _, observations, _, observation, prefix, _, jobs, state = long_supplied
    toggle(long_supplied)
    pending = prepare(long_supplied)[0]
    dates = [
        jobs.get(identity).payload["trade_date"]
        for identity in pending["pending_job_ids"]
    ]
    assert dates == ["2025-01-06", "2025-12-31"]
    assert pending["dataset_id"] == prefix["dataset_id"]
    for identity in pending["pending_job_ids"]:
        assert execute(long_supplied, identity).status == "succeeded"
    first = prepare(long_supplied)[0]
    assert first["status"] == "waiting"
    assert first["last_blocker"]["code"] == "observation_data_preparation_catching_up"
    assert first["through_session"] == "2025-12-31"
    before = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(first["dataset_id"])),
    ).snapshot
    original = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(prefix["dataset_id"])),
    ).snapshot
    assert (original.end_date - original.start_date).days >= 366
    assert before.partitions[: len(original.partitions)] == original.partitions
    second_pending = prepare(long_supplied)[0]
    assert second_pending["dataset_id"] == first["dataset_id"]
    assert len(second_pending["pending_job_ids"]) == 1
    assert (
        jobs.get(second_pending["pending_job_ids"][0]).payload["trade_date"]
        == "2026-09-21"
    )
    assert (
        execute(long_supplied, second_pending["pending_job_ids"][0]).status
        == "succeeded"
    )
    ready = prepare(long_supplied)[0]
    assert ready["status"] == "completed"
    after = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(ready["dataset_id"])),
    ).snapshot
    assert after.partitions[: len(before.partitions)] == before.partitions
    assert prepare(long_supplied)[0]["dataset_id"] == ready["dataset_id"]
    assert state["calls"] == ["baostock", "akshare_tencent"] * 3
    assert (
        observations.repository.get(observation["id"])["source"]
        == observation["source"]
    )


def test_long_history_total_row_budget_blocks_before_enqueue(long_supplied):
    _, observations, current, observation, _, _, jobs, state = long_supplied
    policy = toggle(long_supplied)
    bounded = {
        **observation,
        "policy": {**observation["policy"], "max_dataset_rows": 5},
    }
    before = jobs.list_recent(VERIFIED_DAILY_MARKET_JOB)
    with pytest.raises(ValueError, match="observation_dataset_budget_exceeded"):
        preparation._prepare(
            observations,
            CONFIG,
            jobs,
            bounded,
            current[0],
            {"observation_id": observation["id"], "generation": policy["generation"]},
            lambda: False,
        )
    assert jobs.list_recent(VERIFIED_DAILY_MARKET_JOB) == before
    assert state["calls"] == []


def test_expired_consumer_history_blocks_new_and_already_queued_supply(
    long_supplied, monkeypatch
):
    _, observations, current, _, _, _, jobs, state = long_supplied
    toggle(long_supplied)
    pending = prepare(long_supplied)[0]
    existing = jobs.list_recent(VERIFIED_DAILY_MARKET_JOB)
    current[0] = datetime(2035, 9, 21, 8, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(
        preparation, "ResearchObservationService", lambda *args, **kwargs: observations
    )

    blocked = prepare(long_supplied)[0]
    assert blocked["status"] == "blocked"
    assert blocked["last_blocker"]["code"] == "observation_history_budget_exceeded"
    assert jobs.list_recent(VERIFIED_DAILY_MARKET_JOB) == existing
    assert execute(long_supplied, pending["pending_job_ids"][0]).status != "succeeded"
    assert state["calls"] == []


def test_revocation_in_later_batch_preserves_completed_prefix(long_supplied):
    _, observations, _, observation, _, _, jobs, state = long_supplied
    policy = toggle(long_supplied)
    pending = prepare(long_supplied)[0]
    for identity in pending["pending_job_ids"]:
        assert execute(long_supplied, identity).status == "succeeded"
    first = prepare(long_supplied)[0]
    pending = prepare(long_supplied)[0]
    state["calls"].clear()
    state["after_fetch"] = lambda _: toggle(
        long_supplied, preparation_enabled=False, generation=policy["generation"]
    )
    assert execute(long_supplied, pending["pending_job_ids"][0]).status != "succeeded"
    assert state["calls"] == ["baostock"]
    run = AutomationRunRepository(observations.db.path).get_automation_run_sync(
        f"research-observation-automation:{observation['id']}:latest:data"
    )
    assert json.loads(run["payload_json"])["dataset_id"] == first["dataset_id"]
    assert prepare(long_supplied) == []
    assert not any(
        entry.start_date == date(2024, 1, 2) and entry.end_date == date(2026, 9, 21)
        for entry in DatasetCatalog(
            observations.db.path.parent / "research"
        ).list_daily_bar_datasets()
    )


def test_temporary_failure_retains_prefix_after_earlier_provider_revision(
    supplied, monkeypatch
):
    _, observations, current, _, _, verified, jobs, state = supplied
    toggle(supplied)
    pending = prepare(supplied)[0]
    original_job = jobs.get(pending["pending_job_ids"][0])
    assert execute(supplied, original_job.job_id).status == "succeeded"
    ready = prepare(supplied)[0]
    frozen = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(ready["dataset_id"])),
    ).snapshot

    # A separately collected revision of an already settled date is not an
    # instruction to replace this observation's previously accepted partition.
    manual_payload = {
        key: value
        for key, value in original_job.payload.items()
        if key != "observation_automation"
    }
    manual = jobs.enqueue(VERIFIED_DAILY_MARKET_JOB, manual_payload, now=current[0])
    claimed = jobs.claim(
        VERIFIED_DAILY_MARKET_JOB, "manual", now=current[0], job_id=manual.job_id
    )
    state["offset"] = Decimal("0.05")
    revision = verified.run(claimed.payload, checked_at=current[0])
    jobs.finish(claimed.lease, now=current[0], result_ref=revision.result_ref)
    revised = read_daily_bar_dataset(
        observations.objects, revision.dataset_ref
    ).snapshot
    assert revised.partitions[0] != frozen.partitions[-1]
    state["offset"] = Decimal("0")

    with monkeypatch.context() as transient:
        transient.setattr(
            preparation,
            "resolve_latest_verified_closed_trading_date",
            lambda *args: None,
        )
        failed = prepare(supplied)[0]
    assert failed["status"] == "waiting"
    assert failed["dataset_id"] == ready["dataset_id"]

    current[0] += timedelta(days=1)
    following = prepare(supplied)[0]
    assert len(following["pending_job_ids"]) == 1
    assert execute(supplied, following["pending_job_ids"][0]).status == "succeeded"
    completed = prepare(supplied)[0]
    appended = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(completed["dataset_id"])),
    ).snapshot
    assert appended.partitions[: len(frozen.partitions)] == frozen.partitions


@pytest.mark.parametrize(
    "status_actions,book_actions,extend_status,admitted",
    [
        ("first", None, False, True),
        (None, "first", False, True),
        ("second", "first", False, False),
        (None, "first", True, False),
        ("first", "first", True, True),
    ],
)
def test_prepared_prefix_preserves_corporate_action_evidence_across_book_anchors(
    journey, status_actions, book_actions, extend_status, admitted
):
    client, observations, current, source_ref, result_id = journey
    observation, _ = start(client, result_id)
    identity = observation["id"]
    books = ResearchPaperBookService(observations.db, clock=lambda: current[0])
    book = books.start(
        identity,
        request_id=str(uuid4()),
        initial_cash=Decimal("100000"),
        corporate_action_mode="price_only",
    )
    current[0] += timedelta(seconds=1)
    observations.advance(
        identity,
        request_id=str(uuid4()),
        expected_version=0,
        dataset_id=source_ref.dataset_id,
    )
    current[0] = FUTURE
    actions = {
        "first": _observe(
            observations.objects, at=FUTURE - timedelta(minutes=1)
        ).object_id,
        "second": _observe(observations.objects, at=FUTURE).object_id,
    }

    def bound_dataset(action, *, extended=False):
        end = 7 if extended else 6
        _, ref = dataset(
            observations.db.path.parent / "research",
            days=DAYS[:end],
            cutoff=current[0],
        )
        if action is None:
            return ref
        snapshot = read_daily_bar_dataset(observations.objects, ref).snapshot
        return publish_daily_bar_dataset_manifest(
            observations.objects,
            replace(snapshot, corporate_action_observation_ids=(actions[action],)),
        )

    book_ref = bound_dataset(book_actions)
    books.settle(
        identity,
        request_id=str(uuid4()),
        expected_version=book["version"],
        dataset_id=book_ref.dataset_id,
    )
    assert books.get(identity)["steps"][-1]["dataset_id"] == book_ref.dataset_id
    if extend_status:
        current[0] += timedelta(days=1)
    status_ref = bound_dataset(status_actions, extended=extend_status)
    configured = client.put(
        f"/api/research-observations/{identity}/automation",
        json={"enabled": True, "dataset_preparation_enabled": True},
    )
    assert configured.status_code == 200, configured.text
    AutomationRunRepository(observations.db.path).upsert_automation_run_sync(
        {
            "run_id": f"research-observation-automation:{identity}:latest:data",
            "run_type": "research_observation_dataset_preparation",
            "run_date": current[0].date().isoformat(),
            "status": "completed",
            "source_ref": identity,
            "execution_mode": "research_inputs",
            "payload": {"dataset_id": status_ref.dataset_id},
        }
    )
    report = preparation.run_research_observation_data_preparation_once(
        observations.db, CONFIG, now=current[0]
    )[0]
    if not admitted:
        assert report["status"] == "blocked"
        assert (
            report["last_blocker"]["code"]
            == "observation_data_preparation_prefix_mismatch"
        )
        return
    assert report["status"] == "completed", report
    expected = status_ref if status_actions else book_ref
    assert report["dataset_id"] == expected.dataset_id
    selected = read_daily_bar_dataset(
        observations.objects,
        DatasetRef(observations.objects.resolve_ref(report["dataset_id"])),
    ).snapshot
    assert selected.corporate_action_observation_ids == (actions["first"],)
