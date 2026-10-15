"""Complete daily shards and dated selection retain their original evidence."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetMembership, DailyBarDatasetSnapshot
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.market.contracts import DailyBarRequest
from data.storage.objects import ContentAddressedObjectStore
from data.store import DataStore
from server.persistence.jobs import SQLiteJobStore
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    build_market_universe_truth,
    normalize_a_share_members,
)
from server.services.research_datasets import (
    ResearchDatasetError,
    ensure_forward_seed_for_source,
    publish_verified_interval_dataset,
)
from server.services.verified_daily_market_jobs import (
    enqueue_verified_daily_market_jobs_for_range,
)
from tests.server.test_market_universe_truth import _bars
from tests.server.test_verified_interval_dataset import (
    DAYS,
    NOW,
    STOCK,
    _db,
    _finished_job,
    _verified_day,
)

SECOND = InstrumentKey("600001", InstrumentType.STOCK)


def _composed(tmp_path, *, reverse=False):
    db = _db(tmp_path)
    root = tmp_path / "research"
    jobs = []
    for day, instruments in (
        (DAYS[0], (STOCK,)),
        (DAYS[1], (STOCK,)),
        (DAYS[1], (SECOND,)),
    ):
        ref = _verified_day(root, day, instruments=instruments)
        jobs.append(_finished_job(db, day, ref.dataset_id, instruments=instruments))
    memberships = tuple(
        DailyBarDatasetMembership(
            day,
            instruments,
            datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(hours=8, minutes=5),
        )
        for day, instruments in ((DAYS[0], (STOCK,)), (DAYS[1], (STOCK, SECOND)))
    )
    summary = publish_verified_interval_dataset(
        root,
        DailyBarRequest((STOCK, SECOND), *DAYS),
        db=db,
        job_ids=tuple(reversed(jobs) if reverse else jobs),
        session_memberships=memberships,
        universe_policy_id="fixture.dynamic.v1",
    )
    store = ContentAddressedObjectStore(root / "objects")
    result = read_daily_bar_dataset(
        store, type(ref)(store.resolve_ref(summary["dataset_id"]))
    )
    return store, result


def test_dated_shards_replay_exact_membership_and_order(tmp_path):
    store, result = _composed(tmp_path)
    _, reversed_result = _composed(tmp_path / "reversed", reverse=True)
    assert result.ref == reversed_result.ref
    assert [(bar.session_date, bar.instrument) for bar in result.bars] == [
        (DAYS[0], STOCK),
        (DAYS[1], STOCK),
        (DAYS[1], SECOND),
    ]
    assert result.snapshot.instruments_for_session(DAYS[0]) == (STOCK,)
    assert result.snapshot.instruments_for_session(DAYS[1]) == (STOCK, SECOND)
    assert result.snapshot.membership_evidence_bound is False
    assert (
        json.loads(store.read_bytes(result.ref.manifest_ref))["schema_version"]
        == "karkinos.dataset_manifest.v4"
    )


def test_shards_reject_missing_or_duplicate_members(tmp_path):
    _, result = _composed(tmp_path)
    with pytest.raises(ValueError, match="shard_membership_incomplete"):
        replace(result.snapshot, partitions=result.snapshot.partitions[:-1])
    with pytest.raises(ValueError, match="shard_instrument_duplicate"):
        replace(
            result.snapshot,
            partitions=(*result.snapshot.partitions, result.snapshot.partitions[-1]),
        )
    with pytest.raises(ValueError, match="membership_after_cutoff"):
        replace(
            result.snapshot,
            session_memberships=(
                replace(
                    result.snapshot.session_memberships[0],
                    available_at=NOW + timedelta(days=1),
                ),
                result.snapshot.session_memberships[1],
            ),
        )


def test_membership_replays_actual_stock_master_source_and_time(tmp_path):
    store, result = _composed(tmp_path)
    master = DataStore(tmp_path / "master").save_market_universe_snapshot(
        trade_date=DAYS[1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol, SECOND.symbol]),
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
    )
    identity = bind_stock_master_observation(store, master)
    memberships = tuple(
        replace(
            item, available_at=NOW, source_observation_ids=(identity,), decision_at=NOW
        )
        for item in result.snapshot.session_memberships
    )
    snapshot = replace(result.snapshot, cutoff=NOW, session_memberships=memberships)
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    assert read_daily_bar_dataset(store, ref).snapshot.membership_evidence_bound is True
    tampered = replace(
        snapshot,
        session_memberships=tuple(
            replace(item, available_at=NOW - timedelta(seconds=1))
            for item in memberships
        ),
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        read_daily_bar_dataset(
            store, publish_daily_bar_dataset_manifest(store, tampered)
        )
    with pytest.raises(ValueError, match="unavailable_at_decision"):
        replace(memberships[-1], decision_at=NOW - timedelta(seconds=1))


def test_range_planner_batches_without_narrowing_declared_universe(tmp_path):
    from types import SimpleNamespace

    from data.source_policy import FREE_CN_RESEARCH_V1

    db = _db(tmp_path)
    instruments = tuple(
        InstrumentKey(str(600000 + index), InstrumentType.STOCK) for index in range(201)
    )
    jobs = enqueue_verified_daily_market_jobs_for_range(
        db,
        SimpleNamespace(
            market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id
        ),
        SQLiteJobStore(db.path),
        instruments=instruments,
        start_date=DAYS[0],
        end_date=DAYS[-1],
        now=NOW,
    )
    assert len(jobs) == 6
    for day in DAYS:
        groups = [
            job.payload["instruments"]
            for job in jobs
            if job.payload["trade_date"] == day.isoformat()
        ]
        assert sorted(len(group) for group in groups) == [1, 100, 100]
        assert {row["symbol"] for group in groups for row in group} == {
            key.symbol for key in instruments
        }


def test_full_scope_defaults_evaluate_every_member_and_legacy_retains_40(tmp_path):
    store = DataStore(tmp_path)
    symbols = [str(600000 + index) for index in range(50)]
    snapshot = store.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
        source_metadata=[
            {"symbol": symbol, "display_name": "普通股"} for symbol in symbols
        ],
    )
    frames = {symbol: _bars() for symbol in symbols}
    arguments = dict(
        data_store=store,
        snapshot=snapshot,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000,
        frames=frames,
    )
    full = build_market_universe_truth(
        **arguments, policy=MarketUniversePolicy(minimum_master_member_count=50)
    )
    legacy_policy = MarketUniversePolicy.legacy(minimum_master_member_count=50)
    legacy = build_market_universe_truth(**arguments, policy=legacy_policy)
    assert full["research_panel"]["member_count"] == 50
    assert full["coverage"]["unresolved"] == 0
    assert full["deployment_scope"]["scope_kind"] == "full_declared_market"
    assert legacy["research_panel"]["member_count"] == 40
    assert "deployment_scope" not in legacy
    assert (
        MarketUniversePolicy.from_dict(legacy_policy.to_dict()).to_dict()
        == legacy_policy.to_dict()
    )


def test_full_scope_excludes_known_special_names_and_blocks_unknown_names(tmp_path):
    from server.services.market_universe_truth import market_master_buy_instruments

    symbols = [str(600000 + index) for index in range(5)]
    market = DataStore(tmp_path / "market")
    master = market.save_market_universe_snapshot(
        trade_date="2026-08-21",
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
        source_metadata=[
            {"symbol": symbol, "display_name": name}
            for symbol, name in zip(
                symbols, ("普通股", "*ST样本", "样本退", "N样本", None), strict=True
            )
        ],
    )
    policy = MarketUniversePolicy(minimum_master_member_count=5)
    assert market_master_buy_instruments(master, policy, require_status=False) == (
        STOCK,
    )
    with pytest.raises(ValueError, match="trading_state_unverified"):
        market_master_buy_instruments(master, policy)
    truth = build_market_universe_truth(
        data_store=market,
        snapshot=master,
        start_date="2026-04-01",
        end_date="2026-08-21",
        initial_cash=100_000,
        frames={symbol: _bars() for symbol in symbols},
        policy=policy,
    )
    assert truth["status"] == "incomplete"
    assert truth["coverage"] == {
        "expected": 5,
        "evaluated": 1,
        "excluded": 3,
        "unresolved": 1,
        "as_of": master["available_at"],
    }


def test_final_resolver_waits_then_consumes_real_dated_scope_inputs(tmp_path):
    from data.dataset.model import DatasetRef
    from server.persistence.automation_runs import AutomationRunRepository
    from server.persistence.research_observations import ResearchObservationsRepository
    from server.services.market_universe_truth import market_deployment_scope
    from server.services.research_datasets import resolve_deployment_evaluation_dataset

    objects, original = _composed(tmp_path)
    db = _db(tmp_path, trading_days=(*DAYS, date(2026, 9, 21)))
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    args = dict(
        source_result_id=1,
        scope=scope,
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[-1].isoformat(),
        cutoff=NOW,
    )
    assert resolve_deployment_evaluation_dataset(db, **args)["status"] == "waiting"
    market = DataStore(tmp_path / "master")
    memberships = []
    for item in original.snapshot.session_memberships:
        master = market.save_market_universe_snapshot(
            trade_date=item.partition_date.isoformat(),
            provider_name="fixture",
            members=normalize_a_share_members([key.symbol for key in item.instruments]),
            capture_started_at=item.available_at - timedelta(seconds=1),
            capture_completed_at=item.available_at,
            source_metadata=[
                {"symbol": key.symbol, "display_name": "普通股"}
                for key in item.instruments
            ],
        )
        memberships.append(
            replace(
                item,
                source_observation_ids=(
                    bind_stock_master_observation(objects, master),
                ),
                decision_at=item.available_at,
            )
        )
    snapshot = replace(
        original.snapshot,
        session_memberships=tuple(memberships),
        universe_policy_id=scope["deployment_scope_fingerprint"],
    )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    read_daily_bar_dataset(objects, ref)
    ResearchObservationsRepository(db.path).start(
        observation_id="scope-final",
        request_id="start",
        request_fingerprint="fixture",
        source_backtest_result_id=1,
        source={"source_selection": {"deployment_scope": scope}},
        code_binding={},
        policy={},
        universe=[],
    )
    AutomationRunRepository(db.path).upsert_automation_run_sync(
        {
            "run_id": "research-observation-automation:scope-final:latest:data",
            "run_type": "research_observation_data_preparation",
            "run_date": DAYS[-1].isoformat(),
            "status": "ready",
            "execution_mode": "fixture",
            "payload": {"dataset_id": ref.dataset_id},
        }
    )
    resolved = resolve_deployment_evaluation_dataset(db, **args)
    assert resolved["status"] == "ready", resolved
    assert resolved["dataset_id"] == ref.dataset_id
    assert resolved["dataset_snapshot"]["immutable_dataset_id"] == ref.dataset_id
    assert resolved["dataset_snapshot"]["point_in_time_verified"] is False
    late = replace(
        memberships[-1], decision_at=datetime(2026, 9, 21, 1, 30, tzinfo=timezone.utc)
    )
    bad = replace(snapshot, cutoff=NOW, session_memberships=(*memberships[:-1], late))
    bad_ref = publish_daily_bar_dataset_manifest(objects, bad)
    AutomationRunRepository(db.path).upsert_automation_run_sync(
        {
            "run_id": "research-observation-automation:scope-final:latest:data",
            "run_type": "research_observation_data_preparation",
            "run_date": DAYS[-1].isoformat(),
            "status": "ready",
            "execution_mode": "fixture",
            "payload": {"dataset_id": bad_ref.dataset_id},
        }
    )
    assert resolve_deployment_evaluation_dataset(db, **args)["status"] == "waiting"


@pytest.mark.parametrize(
    "case",
    [
        "short_prefix",
        "wrong_scope",
        "future_cutoff",
        "late_start",
        "matching_corrupt_lineage",
    ],
)
def test_final_dataset_manifest_is_only_a_rejection_prefilter(
    tmp_path, monkeypatch, case
):
    from server.persistence.automation_runs import AutomationRunRepository
    from server.persistence.research_observations import ResearchObservationsRepository
    from server.services.market_universe_truth import market_deployment_scope
    from server.services.research_datasets import resolve_deployment_evaluation_dataset

    objects, original = _composed(tmp_path)
    db = _db(tmp_path, trading_days=(*DAYS, date(2026, 9, 21)))
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    snapshot = replace(
        original.snapshot, universe_policy_id=scope["deployment_scope_fingerprint"]
    )
    if case == "short_prefix":
        snapshot = replace(
            snapshot,
            end_date=DAYS[0],
            instruments=(STOCK,),
            partitions=snapshot.partitions[:1],
            session_memberships=snapshot.session_memberships[:1],
        )
    elif case == "wrong_scope":
        snapshot = replace(snapshot, universe_policy_id="fixture.other.scope")
    elif case == "future_cutoff":
        snapshot = replace(snapshot, cutoff=NOW + timedelta(seconds=1))
    elif case == "late_start":
        snapshot = replace(
            snapshot,
            start_date=DAYS[-1],
            partitions=snapshot.partitions[1:],
            session_memberships=snapshot.session_memberships[1:],
        )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    ResearchObservationsRepository(db.path).start(
        observation_id="scope-prefilter",
        request_id="start",
        request_fingerprint="fixture",
        source_backtest_result_id=1,
        source={"source_selection": {"deployment_scope": scope}},
        code_binding={},
        policy={},
        universe=[],
    )
    AutomationRunRepository(db.path).upsert_automation_run_sync(
        {
            "run_id": "research-observation-automation:scope-prefilter:latest:data",
            "run_type": "research_observation_data_preparation",
            "run_date": DAYS[-1].isoformat(),
            "status": "ready",
            "execution_mode": "fixture",
            "payload": {"dataset_id": ref.dataset_id},
        }
    )
    args = dict(
        source_result_id=1,
        scope=scope,
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[-1].isoformat(),
        cutoff=NOW,
    )
    if case == "matching_corrupt_lineage":
        # A qualifying manifest cannot stand in for the original raw objects.
        path = objects._path_for(snapshot.partitions[0].revision_id)
        path.chmod(0o644)
        path.write_bytes(b"corrupt original revision")
        with pytest.raises(DatasetReaderIntegrityError, match="partition_unreadable"):
            resolve_deployment_evaluation_dataset(db, **args)
    else:

        def forbidden_cold_read(*_args, **_kwargs):
            raise AssertionError(
                "irrelevant prefixes must be rejected before full market reads"
            )

        monkeypatch.setattr(
            "server.services.research.datasets.read_daily_bar_dataset",
            forbidden_cold_read,
        )
        result = resolve_deployment_evaluation_dataset(db, **args)
        assert result == {
            "status": "waiting",
            "last_blocker": {"code": "deployment_final_inputs_pending"},
        }


def test_dated_scope_has_a_bounded_longer_range_without_changing_legacy(
    tmp_path, monkeypatch
):
    db = _db(tmp_path)
    membership = DailyBarDatasetMembership(DAYS[-1], (STOCK,), NOW)
    request = DailyBarRequest((STOCK,), DAYS[-1] - timedelta(days=700), DAYS[-1])
    monkeypatch.setattr(
        "server.services.research_datasets.verified_dataset_dates",
        lambda *_args: (DAYS[-1],),
    )
    with pytest.raises(ResearchDatasetError, match="range_exceeds_366_days"):
        publish_verified_interval_dataset(
            tmp_path / "research", request, db=db, job_ids=()
        )
    with pytest.raises(ResearchDatasetError, match="job_coverage_invalid"):
        publish_verified_interval_dataset(
            tmp_path / "research",
            request,
            db=db,
            job_ids=(),
            session_memberships=(membership,),
            universe_policy_id="fixture.scope",
        )
    too_long = DailyBarRequest((STOCK,), DAYS[-1] - timedelta(days=3653), DAYS[-1])
    with pytest.raises(ResearchDatasetError, match="range_exceeds_ten_years"):
        publish_verified_interval_dataset(
            tmp_path / "research",
            too_long,
            db=db,
            job_ids=(),
            session_memberships=(membership,),
            universe_policy_id="fixture.scope",
        )
    monkeypatch.setattr(
        "server.services.research_datasets.verified_dataset_dates",
        lambda *_args: tuple(DAYS[-1] - timedelta(days=index) for index in range(2001)),
    )
    with pytest.raises(ResearchDatasetError, match="session_budget_exceeded"):
        publish_verified_interval_dataset(
            tmp_path / "research",
            request,
            db=db,
            job_ids=(),
            session_memberships=(membership,),
            universe_policy_id="fixture.scope",
        )


def test_seed_waits_for_real_jobs_then_binds_only_current_observed_membership(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from data.source_policy import FREE_CN_RESEARCH_V1
    from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
    from server.services.market_universe_truth import market_deployment_scope

    db = _db(tmp_path)
    market_store = DataStore(tmp_path / "market")
    market_store.save_market_universe_snapshot(
        trade_date=DAYS[-1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol, SECOND.symbol]),
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
        source_metadata=[
            {"symbol": symbol, "display_name": "普通股"}
            for symbol in (STOCK.symbol, SECOND.symbol)
        ],
    )
    policy = MarketUniversePolicy(minimum_master_member_count=2, minimum_history_rows=2)
    source = {
        "instruments": [{"symbol": STOCK.symbol, "instrument_type": "stock"}],
        "minimum_bars": 2,
        "source_selection": {
            "deployment_scope": market_deployment_scope(policy),
            "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        },
    }
    config = SimpleNamespace(
        market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id
    )
    pending = ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market_store
    )
    assert pending["status"] == "waiting"
    assert len(pending["job_ids"]) == 1
    root = tmp_path / "research"
    from server.services.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB
    from tests.server.test_verified_daily_market_range import _service

    service, _, _ = _service(tmp_path, monkeypatch)
    jobs = SQLiteJobStore(db.path)
    from server.persistence.market_daily_call_budget import BUDGET_DEFERRED_CODE

    deferred = jobs.claim(VERIFIED_DAILY_MARKET_JOB, "budget-fixture", now=NOW)
    jobs.fail(deferred.lease, now=NOW, error=BUDGET_DEFERRED_CODE, retry_seconds=0)
    waiting = ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market_store
    )
    assert waiting["status"] == "waiting"
    assert waiting["last_blocker"] == {
        "code": BUDGET_DEFERRED_CODE,
        "available_at": jobs.get(pending["job_ids"][0]).available_at,
    }
    claimed = jobs.claim(VERIFIED_DAILY_MARKET_JOB, "range-fixture", now=NOW)
    publication = service.run(claimed.payload, checked_at=NOW)
    jobs.finish(claimed.lease, now=NOW, result_ref=publication.result_ref)
    ready = ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market_store
    )
    assert ready["status"] == "ready", ready
    store = ContentAddressedObjectStore(root / "objects")
    from data.dataset.model import DatasetRef

    result = read_daily_bar_dataset(
        store, DatasetRef(store.resolve_ref(ready["dataset_id"]))
    )
    assert result.snapshot.session_memberships[0].decision_at is None
    assert result.snapshot.session_memberships[-1].decision_at == NOW
    assert result.snapshot.session_memberships[-1].source_observation_ids
    assert result.snapshot.instruments_for_session(DAYS[-1]) == (STOCK, SECOND)
    assert (
        ensure_forward_seed_for_source(
            db, config, source=source, now=NOW, data_store=market_store
        )["dataset_id"]
        == ready["dataset_id"]
    )
    assert (
        ensure_forward_seed_for_source(
            db,
            config,
            source={**source, "source_result_id": 999},
            now=NOW,
            data_store=market_store,
        )["dataset_id"]
        == ready["dataset_id"]
    )


@pytest.mark.parametrize("warmup,forward", [(2001, 0), (2000, 1), (1941, 60)])
def test_seed_blocks_session_budget_before_any_job_is_queued(
    tmp_path, monkeypatch, warmup, forward
):
    from types import SimpleNamespace

    from server.services.market_universe_truth import market_deployment_scope

    def forbidden_queue(*_args, **_kwargs):
        raise AssertionError("resource rejection must precede queueing")

    monkeypatch.setattr(
        "server.services.verified_daily_market_jobs.enqueue_verified_daily_market_jobs_for_range",
        forbidden_queue,
    )
    source = {
        "minimum_bars": warmup,
        "forward_minimum_observations": forward,
        "source_selection": {
            "deployment_scope": market_deployment_scope(
                MarketUniversePolicy(minimum_master_member_count=1)
            )
        },
    }
    result = ensure_forward_seed_for_source(
        _db(tmp_path), SimpleNamespace(), source=source, now=NOW
    )
    assert result == {
        "status": "blocked",
        "job_ids": [],
        "last_blocker": {
            "code": "forward_seed_session_budget_exceeded",
            "warmup_sessions": warmup,
            "minimum_forward_sessions": forward,
            "limit": 2000,
        },
    }


def test_seed_blocks_instrument_budget_before_any_job_is_queued(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from server.services.market_universe_truth import market_deployment_scope

    market = DataStore(tmp_path / "market")
    market.save_market_universe_snapshot(
        trade_date=DAYS[-1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol]),
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
        source_metadata=[{"symbol": STOCK.symbol, "display_name": "普通股"}],
    )

    def forbidden_queue(*_args, **_kwargs):
        raise AssertionError("resource rejection must precede queueing")

    monkeypatch.setattr(
        "server.services.verified_daily_market_jobs.enqueue_verified_daily_market_jobs_for_range",
        forbidden_queue,
    )
    source = {
        "minimum_bars": 2,
        "instruments": [
            {"symbol": str(600000 + index), "instrument_type": "stock"}
            for index in range(10_001)
        ],
        "source_selection": {
            "deployment_scope": market_deployment_scope(
                MarketUniversePolicy(
                    minimum_master_member_count=1, minimum_history_rows=2
                )
            )
        },
    }
    result = ensure_forward_seed_for_source(
        _db(tmp_path), SimpleNamespace(), source=source, now=NOW, data_store=market
    )
    assert result["status"] == "blocked"
    assert result["job_ids"] == []
    assert result["last_blocker"] == {
        "code": "forward_seed_instrument_budget_exceeded",
        "instruments": 10_001,
        "limit": 10_000,
    }


def test_seed_warmup_uses_actual_receipt_rows_without_inventing_ipo_history(tmp_path):
    from types import SimpleNamespace

    import pandas as pd

    from data.source_policy import FREE_CN_RESEARCH_V1
    from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
    from server.services.market_universe_truth import market_deployment_scope

    db = _db(tmp_path)
    market = DataStore(tmp_path / "market")
    market.save_market_universe_snapshot(
        trade_date=DAYS[-1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol, SECOND.symbol]),
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
        source_metadata=[
            {"symbol": key.symbol, "display_name": "普通股"} for key in (STOCK, SECOND)
        ],
    )
    for day, instruments in ((DAYS[0], (STOCK,)), (DAYS[-1], (STOCK, SECOND))):
        market.ingest_market_daily_batch(
            trade_date=day.isoformat(),
            provider_name="fixture",
            bars=pd.DataFrame(
                [
                    {
                        "symbol": key.symbol,
                        "timestamp": pd.Timestamp(day),
                        "open": 10.0,
                        "high": 10.1,
                        "low": 9.9,
                        "close": 10.0,
                        "volume": 1000000,
                        "amount": 10000000,
                    }
                    for key in instruments
                ]
            ),
        )
    policy = MarketUniversePolicy(minimum_master_member_count=2, minimum_history_rows=2)
    result = ensure_forward_seed_for_source(
        db,
        SimpleNamespace(
            market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id
        ),
        source={
            "instruments": [{"symbol": STOCK.symbol, "instrument_type": "stock"}],
            "minimum_bars": 2,
            "source_selection": {
                "deployment_scope": market_deployment_scope(policy),
                "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
            },
        },
        now=NOW,
        data_store=market,
    )
    assert result["status"] == "waiting", result
    jobs = [SQLiteJobStore(db.path).get(job_id) for job_id in result["job_ids"]]
    from server.services.verified_daily_market_data import VerifiedDailyMarketJobRequest

    assert len(jobs) == 1
    request = VerifiedDailyMarketJobRequest.from_payload(jobs[0].payload)
    assert [
        (
            day.isoformat(),
            [key.symbol for key in request.instruments_for_session(day)],
        )
        for day in request.expected_sessions()
    ] == [
        (DAYS[0].isoformat(), [STOCK.symbol]),
        (DAYS[-1].isoformat(), [STOCK.symbol, SECOND.symbol]),
    ]


def test_dynamic_membership_adds_current_master_and_keeps_only_held_exits(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from data.dataset.model import DatasetRef
    from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
    from server.services import research_observation_data_preparation as preparation
    from server.services.market_universe_truth import market_deployment_scope
    from tests.server.test_verified_interval_dataset import _calendar

    objects, result = _composed(tmp_path)
    day = DAYS[-1] + timedelta(days=3)
    now = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(
        hours=8, minutes=10
    )
    third = InstrumentKey("600002", InstrumentType.STOCK)
    market_store = DataStore(tmp_path / "market")
    market_store.save_market_universe_snapshot(
        trade_date=day.isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([SECOND.symbol, third.symbol]),
        capture_started_at=now - timedelta(minutes=2),
        capture_completed_at=now - timedelta(minutes=1),
        source_metadata=[
            {"symbol": symbol, "display_name": "普通股"}
            for symbol in (SECOND.symbol, third.symbol)
        ],
    )
    policy = MarketUniversePolicy(minimum_master_member_count=2, minimum_history_rows=2)
    source = {
        "source_selection": {
            "deployment_scope": market_deployment_scope(policy),
            "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        }
    }
    service = SimpleNamespace(
        db=_db(tmp_path),
        objects=objects,
        clock=lambda: now,
        _calendar=lambda *_: [
            _calendar(
                trading_days=(
                    *DAYS,
                    day,
                    day + timedelta(days=1),
                    day + timedelta(days=2),
                )
            )
        ],
    )
    monkeypatch.setattr(
        preparation,
        "ResearchPaperBooksRepository",
        lambda *_args, **_kwargs: SimpleNamespace(
            get=lambda _: {"state": {"positions": {STOCK.symbol: {"quantity": "100"}}}}
        ),
    )
    memberships = preparation._dynamic_memberships(
        service,
        {"id": "fixture", "source": source},
        result.snapshot,
        (SimpleNamespace(trade_date=day.isoformat()),),
        now,
        market_store,
    )
    assert memberships[0].instruments == (SECOND, third)
    assert memberships[0].maintenance_instruments == (STOCK,)
    assert memberships[0].available_at == now - timedelta(minutes=1)
    assert memberships[0].decision_at == now
    assert objects.resolve_ref(memberships[0].source_observation_ids[0])
    with pytest.raises(ValueError, match="membership_observation_unavailable"):
        preparation._dynamic_memberships(
            service,
            {"id": "fixture", "source": source},
            result.snapshot,
            (SimpleNamespace(trade_date=(day + timedelta(days=1)).isoformat()),),
            now + timedelta(days=1),
            market_store,
        )
