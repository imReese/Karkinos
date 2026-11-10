"""Multi-session seed catch-up reuses real range owners without changing scope."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_daily_call_budget import (
    reserve_market_daily_provider_call,
)
from server.services.market.verified_daily_market_data import (
    VerifiedDailyMarketJobRequest,
)
from server.services.market.verified_daily_market_jobs import (
    VERIFIED_DAILY_MARKET_JOB,
    enqueue_verified_daily_market_jobs_for_range,
)
from server.services.research import datasets
from tests.server.test_deployment_scope_datasets import _source_prefix_seed
from tests.server.test_verified_daily_market_jobs import _config
from tests.server.test_verified_daily_market_range import DAYS, NOW, _service
from tests.server.test_verified_interval_dataset import _db, _verified_day

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


def _rows(db, table):
    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


@pytest.mark.parametrize(
    "observation", ["halted", "missing", "contradictory", "traded"]
)
def test_failed_seed_keeps_only_proven_halts_out_of_historical_prices(
    tmp_path, monkeypatch, observation
):
    from data.dataset.reader import dataset_session_nontrading_instruments
    from data.market.contracts import DailyBarRequest
    from data.market.ingestion import ingest_daily_bars
    from data.market.quality import RESEARCH_STRICT_DAILY
    from data.market.quality_evidence import publish_market_quality_evidence
    from data.providers.baostock import BaoStockDailyBarProvider
    from server.services.market.market_universe_truth import normalize_a_share_members
    from tests.data.providers.test_baostock_daily import FakeBaoStock, FakeResult, _row
    from tests.server.test_forward_verified_union import union_seed

    _, market, config, source, objects, prefix, current = union_seed(
        tmp_path, suffix_receipts=observation == "traded"
    )
    day = DAYS[-1]
    following = tuple(day + timedelta(days=i) for i in (1, 2, 3))
    db = _db(tmp_path, trading_days=(*DAYS, *following))
    latest = SimpleNamespace(trade_date=day.isoformat())
    monkeypatch.setattr(
        "server.services.market.calendar.resolve_latest_verified_closed_trading_date",
        lambda *_: latest,
    )
    capture_time = NOW + timedelta(minutes=1)
    prepare_time = capture_time + timedelta(minutes=1)

    def prepare():
        return datasets.ensure_forward_seed_for_source(
            db, config, source=source, now=prepare_time, data_store=market
        )

    store = SQLiteJobStore(db.path)
    (original_id,) = prepare()["job_ids"]
    halted = current[0]
    sdk = FakeBaoStock()
    for key in current:
        code = "sh." + key.symbol
        if key == halted and observation == "missing":
            continue
        values = (
            _row(
                code,
                volume="100" if observation == "contradictory" else "",
                amount="",
                tradestatus="0",
            )
            if key == halted
            else _row(code)
        )
        values[0] = day.isoformat()
        sdk.results[code] = FakeResult([values])
    original = ingest_daily_bars(
        BaoStockDailyBarProvider(sdk, clock=lambda: capture_time),
        objects,
        request=DailyBarRequest(current, day, day),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="fixture",
        checked_at=prepare_time,
    )
    quality = publish_market_quality_evidence(objects, original.quality)
    job = store.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=prepare_time, job_id=original_id
    )
    store.fail(
        job.lease,
        now=prepare_time,
        error="verified_daily_market_quality_blocked",
        failure_evidence_ref="quality:" + quality.quality_id,
        retryable=False,
    )
    assert prepare()["status"] == "blocked"  # This is still the decision session.
    latest.trade_date = following[0].isoformat()
    revised = prepare()
    if observation != "halted":
        assert revised["status"] == "blocked"
        assert revised["job_ids"] == [original_id]
        if observation == "contradictory":
            assert (
                revised["last_blocker"]["code"]
                == "forward_seed_status_evidence_invalid"
            )
        if observation == "traded":
            assert (
                revised["last_blocker"]["code"] == "forward_seed_halt_status_conflict"
            )
        return
    assert revised["status"] == "waiting"
    (successor_id,) = revised["job_ids"]
    assert successor_id != original_id
    successor = store.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=prepare_time, job_id=successor_id
    )
    traded = tuple(key for key in current if key != halted)
    assert (
        VerifiedDailyMarketJobRequest.from_payload(successor.payload).instruments
        == traded
    )
    verified = _verified_day(tmp_path / "research", day, instruments=traded)
    store.finish(
        successor.lease, now=prepare_time, result_ref="dataset:" + verified.dataset_id
    )
    prepare()
    origins = AutomationRunRepository(db.path).list_automation_runs_sync(
        run_type="forward_seed_preparation"
    )
    (completed,) = [row for row in origins if row["status"] == "completed"]
    saved = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(completed["source_ref"]))
    ).snapshot
    assert (
        saved.session_memberships[: len(prefix.session_memberships)]
        == prefix.session_memberships
    )
    assert set(saved.instruments) == set(current)
    membership = saved.session_memberships[-1]
    assert membership.instruments == traded
    assert original.capture.capture_id in membership.source_observation_ids
    assert membership.available_at == capture_time and membership.decision_at is None
    assert dataset_session_nontrading_instruments(objects, saved, session_date=day) == {
        day: (halted,)
    }
    assert (
        store.get(original_id).failure_evidence_ref == "quality:" + quality.quality_id
    )

    # The following sessions have full dated rosters. One has a partial price
    # receipt, another has none. Neither shrinks the pool or prolongs the halt.
    for session in following:
        market.save_market_universe_snapshot(
            trade_date=session.isoformat(),
            provider_name="fixture",
            members=normalize_a_share_members([key.symbol for key in current]),
            capture_started_at=NOW - timedelta(seconds=1),
            capture_completed_at=NOW,
            source_metadata=[
                {"symbol": key.symbol, "display_name": "普通股"} for key in current
            ],
        )
    partial = following[1]
    market.ingest_market_daily_batch(
        trade_date=partial.isoformat(),
        provider_name="fixture",
        bars=pd.DataFrame(
            [
                dict(
                    symbol=traded[0].symbol,
                    timestamp=pd.Timestamp(partial),
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    volume=100,
                    amount=1000,
                )
            ]
        ),
    )
    latest.trade_date = following[-1].isoformat()
    extension = prepare()
    assert extension["status"] == "waiting", extension
    (new_id,) = extension["job_ids"]
    requested = VerifiedDailyMarketJobRequest.from_payload(store.get(new_id).payload)
    assert requested.expected_sessions() == following
    assert all(requested.instruments_for_session(d) == current for d in following)


def test_multi_session_suffix_shards_preserve_each_sessions_exact_members(tmp_path):
    days = (*DAYS, date(2026, 9, 22), date(2026, 9, 23))
    db = _db(tmp_path, trading_days=days)
    stocks = tuple(
        InstrumentKey(f"600{i:03d}", InstrumentType.STOCK) for i in range(83)
    )
    expected = {
        days[0]: stocks[:40],
        days[1]: stocks[:82],
        days[2]: stocks[1:],
        days[3]: stocks,
        days[4]: stocks[2:],
    }
    prefix = SimpleNamespace(end_date=days[0])
    report = datasets._forward_seed_jobs(
        db,
        _config(),
        expected=expected,
        prefix=prefix,
        through=days[-1],
        now=NOW,
        replacements={},
    )
    assert report["status"] == "waiting"
    store = SQLiteJobStore(db.path)
    jobs = [store.get(identity) for identity in report["job_ids"]]
    assert len(jobs) == 3  # 83 union members / 40, not a narrowed 40-stock pool.
    planned = [VerifiedDailyMarketJobRequest.from_payload(job.payload) for job in jobs]
    assert all(item.is_range and len(item.instruments) <= 40 for item in planned)
    assert all(item.expected_sessions() == days[1:] for item in planned)
    for day in days[1:]:
        supplied = [
            key for item in planned for key in item.instruments_for_session(day)
        ]
        assert len(supplied) == len(set(supplied))
        assert set(supplied) == set(expected[day])
    assert (
        datasets._forward_seed_jobs(
            db,
            _config(),
            expected=expected,
            prefix=prefix,
            through=days[-1],
            now=NOW,
            replacements={},
        )
        == report
    )
    # A dated halt removes the first stock from every new session. The other
    # two 40-stock acquisition batches keep their original jobs and captures.
    halted = stocks[0]
    corrected = datasets._forward_seed_jobs(
        db,
        _config(),
        expected={
            day: tuple(k for k in keys if k != halted) for day, keys in expected.items()
        },
        prefix=prefix,
        through=days[-1],
        now=NOW,
        replacements={},
        halted_batch_instruments=(halted,),
    )
    assert corrected["job_ids"][1:] == report["job_ids"][1:]
    assert corrected["job_ids"][0] != report["job_ids"][0]
    updated = VerifiedDailyMarketJobRequest.from_payload(
        store.get(corrected["job_ids"][0]).payload
    )
    assert halted not in updated.instruments
    assert all(halted not in updated.instruments_for_session(day) for day in days[1:])


def test_single_session_suffix_keeps_existing_daily_identity_and_batch_size(tmp_path):
    db = _db(tmp_path, trading_days=DAYS)
    stocks = tuple(
        InstrumentKey(f"600{i:03d}", InstrumentType.STOCK) for i in range(83)
    )
    old = enqueue_verified_daily_market_jobs_for_range(
        db,
        _config(),
        SQLiteJobStore(db.path),
        instruments=stocks,
        start_date=DAYS[-1],
        end_date=DAYS[-1],
        now=NOW,
    )
    report = datasets._forward_seed_jobs(
        db,
        _config(),
        expected={DAYS[-1]: stocks},
        prefix=SimpleNamespace(end_date=DAYS[-2]),
        through=DAYS[-1],
        now=NOW,
        replacements={},
    )
    assert report["job_ids"] == [job.job_id for job in old]
    assert len(old) == 1 and len(old[0].payload["instruments"]) == 83
    assert not VerifiedDailyMarketJobRequest.from_payload(old[0].payload).is_range


@pytest.mark.parametrize(
    "scope", ["two_days_stable_83", "tie_stable_60", "tie_changing_40"]
)
def test_short_suffix_keeps_daily_jobs_when_ranges_cost_as_much_or_more(
    tmp_path, scope
):
    db = _db(tmp_path, trading_days=DAYS)
    stocks = tuple(
        InstrumentKey(f"600{i:03d}", InstrumentType.STOCK) for i in range(83)
    )
    members = (
        (stocks, stocks)
        if scope == "two_days_stable_83"
        else (stocks[:60], stocks[:60])
        if scope == "tie_stable_60"
        else (stocks[:40], stocks[40:80])
    )
    expected = dict(zip(DAYS[1:], members, strict=True))
    store = SQLiteJobStore(db.path)
    original = tuple(
        job
        for day, instruments in expected.items()
        for job in enqueue_verified_daily_market_jobs_for_range(
            db,
            _config(),
            store,
            instruments=instruments,
            start_date=day,
            end_date=day,
            now=NOW,
        )
    )
    report = datasets._forward_seed_jobs(
        db,
        _config(),
        expected=expected,
        prefix=SimpleNamespace(end_date=DAYS[0]),
        through=DAYS[-1],
        now=NOW,
        replacements={},
    )
    assert report["job_ids"] == [job.job_id for job in original]
    assert len(original) == 2
    assert all(
        not VerifiedDailyMarketJobRequest.from_payload(job.payload).is_range
        for job in original
    )


def test_public_seed_range_catchup_preserves_prefix_failed_jobs_budget_and_origin(
    tmp_path,
    monkeypatch,
):
    # Extend only this synthetic calendar. The actual range provider adapter,
    # capture/verification/publication owners and final reader remain in use.
    extra = date(2026, 9, 22)
    monkeypatch.setattr(
        "tests.server.test_verified_daily_market_range.DAYS", (*DAYS, extra)
    )
    db, market, config, source, objects, prefix, current = _source_prefix_seed(
        tmp_path,
        current_day=extra,
    )
    market.ingest_market_daily_batch(
        trade_date=DAYS[-1].isoformat(),
        provider_name="fixture",
        bars=pd.DataFrame(
            [
                {
                    "symbol": key.symbol,
                    "timestamp": pd.Timestamp(DAYS[-1]),
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.0,
                    "volume": 1_000_000,
                    "amount": 10_000_000,
                }
                for key in current
            ]
        ),
    )
    store = SQLiteJobStore(db.path)
    old_jobs = enqueue_verified_daily_market_jobs_for_range(
        db,
        config,
        store,
        instruments=current,
        start_date=DAYS[-1],
        end_date=extra,
        now=NOW,
    )
    failed = store.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=NOW, job_id=old_jobs[0].job_id
    )
    reserve_market_daily_provider_call(
        db.path, failed.lease, BAOSTOCK_DAILY_BAR_DESCRIPTOR, now=NOW
    )
    store.fail(
        failed.lease,
        now=NOW,
        error="verified_daily_market_quality_blocked",
        retryable=False,
    )
    succeeded = store.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=NOW, job_id=old_jobs[1].job_id
    )
    old_ref = _verified_day(tmp_path / "research", extra, instruments=current)
    store.finish(succeeded.lease, now=NOW, result_ref=f"dataset:{old_ref.dataset_id}")
    old_rows = {row["job_id"]: row for row in _rows(db, "job_runs")}
    budgets = _rows(db, "market_daily_provider_call_reservations")
    original_ref = DatasetRef(objects.resolve_ref(source["immutable_dataset_id"]))
    original_bytes = objects.read_bytes(original_ref.manifest_ref)
    origins = AutomationRunRepository(db.path)
    prior = origins.claim_automation_run_once_sync(
        run_id="preserved_old_failed_seed",
        run_type="forward_seed_preparation",
        run_date=NOW.date().isoformat(),
        claimed_at=NOW.isoformat(),
        execution_mode="paper_shadow",
        payload={"failed_history_retained": True},
    )["run"]
    pending = datasets.ensure_forward_seed_for_source(
        db,
        config,
        source=source,
        now=NOW,
        data_store=market,
    )
    assert pending["status"] == "waiting", pending
    assert len(pending["job_ids"]) == 1
    identity = pending["job_ids"][0]
    assert identity not in {job.job_id for job in old_jobs}
    job = store.get(identity)
    planned = VerifiedDailyMarketJobRequest.from_payload(job.payload)
    assert planned.is_range and planned.expected_sessions() == (DAYS[-1], extra)
    assert all(
        planned.instruments_for_session(day) == current
        for day in planned.expected_sessions()
    )
    pending_origin = next(
        row
        for row in origins.list_automation_runs_sync(
            run_type="forward_seed_preparation"
        )
        if row["run_id"] != prior["run_id"]
    )
    pending_payload = json.loads(pending_origin["payload_json"])
    service, primary, comparison = _service(tmp_path, monkeypatch)
    claimed = store.claim(
        VERIFIED_DAILY_MARKET_JOB, "range-fixture", now=NOW, job_id=identity
    )
    publication = service.run(claimed.payload, checked_at=NOW)
    store.finish(claimed.lease, now=NOW, result_ref=publication.result_ref)
    assert len(primary.calls) == len(comparison.calls) == 1
    ready = datasets.ensure_forward_seed_for_source(
        db,
        config,
        source=source,
        now=NOW,
        data_store=market,
    )
    assert ready["status"] == "ready", ready
    restored = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(ready["dataset_id"]))
    )
    assert restored.snapshot.partitions[: len(prefix.partitions)] == prefix.partitions
    assert (
        restored.snapshot.session_memberships[: len(prefix.session_memberships)]
        == prefix.session_memberships
    )
    assert objects.read_bytes(original_ref.manifest_ref) == original_bytes
    assert restored.snapshot.end_date == extra
    assert restored.snapshot.session_memberships[-1].decision_at == NOW
    assert restored.snapshot.instruments_for_session(extra) == current
    after_rows = {row["job_id"]: row for row in _rows(db, "job_runs")}
    assert all(after_rows[identity] == row for identity, row in old_rows.items())
    assert _rows(db, "market_daily_provider_call_reservations") == budgets
    assert origins.get_automation_run_sync(prior["run_id"]) == prior
    completed = origins.get_automation_run_sync(pending_origin["run_id"])
    assert completed["status"] == "completed"
    assert json.loads(completed["payload_json"]) == {
        **pending_payload,
        "prepared_through": extra.isoformat(),
    }
