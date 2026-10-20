"""Range warmup captures remain real daily, dual-source research evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.model import DailyBarDatasetMembership, DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.market.capture import read_provider_capture
from data.market.contracts import DailyBarRequest, ProviderDailyBarBatch
from data.market.revision import read_market_revision_materialization
from data.provider_registry import ProviderRegistration, ProviderRegistry
from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.providers.tencent import AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore
from server.persistence.jobs import SQLiteJobStore, job_id_for
from server.services.market.verified_daily_market_data import (
    VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
    VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION,
    VerifiedDailyMarketDataNotPublishable,
    VerifiedDailyMarketDataRequestError,
    VerifiedDailyMarketDataService,
    VerifiedDailyMarketJobRequest,
)
from server.services.market.verified_daily_market_jobs import (
    VERIFIED_DAILY_MARKET_JOB,
    enqueue_verified_daily_market_jobs_for_range,
)
from server.services.research.datasets import (
    ResearchDatasetError,
    publish_verified_interval_dataset,
)
from tests.server.test_verified_daily_market_data import FakeDailyProvider
from tests.server.test_verified_daily_market_jobs import _calendar, _config, _store
from tests.server.test_verified_interval_dataset import _db

DAYS = (date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 21))
NOW = datetime(2026, 9, 28, 8, tzinfo=timezone.utc)
STOCKS = (
    InstrumentKey("600000", InstrumentType.STOCK),
    InstrumentKey("600001", InstrumentType.STOCK),
)


class RangeProvider(FakeDailyProvider):
    def __init__(self, descriptor, *, missing=None, conflict=False):
        super().__init__(descriptor)
        self.missing = missing
        self.conflict = conflict

    def fetch_daily_bars(self, request):
        self.calls.append(request)
        rows = []
        for day in DAYS:
            if not request.start_date <= day <= request.end_date:
                continue
            for key in request.instruments:
                if (day, key) == self.missing:
                    continue
                row = self._row(key)
                row = replace(
                    row,
                    session_date=day,
                    event_time=datetime.combine(day, datetime.min.time(), timezone.utc)
                    + timedelta(hours=7),
                )
                if self.conflict and day == DAYS[-1]:
                    row = replace(
                        row,
                        close_value=row.close_value + 1,
                        high_value=row.high_value + 1,
                    )
                rows.append(row)
        return ProviderDailyBarBatch(
            provider=self.descriptor.provider,
            adapter_version=self.descriptor.adapter_version,
            payload_format="range.fixture.v1",
            started_at=NOW - timedelta(seconds=1),
            completed_at=NOW,
            raw_payload=(self.descriptor.provider + repr(rows)).encode(),
            rows=tuple(rows),
        )


def _service(tmp_path, monkeypatch, *, missing=None, conflict=False):
    primary = RangeProvider(BAOSTOCK_DAILY_BAR_DESCRIPTOR)
    comparison = RangeProvider(
        AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR, missing=missing, conflict=conflict
    )
    registry = ProviderRegistry(
        tuple(
            ProviderRegistration(
                name=provider.descriptor.provider,
                upstream_group=group,
                daily_bar_factory=lambda provider=provider: provider,
            )
            for provider, group in ((primary, "baostock"), (comparison, "tencent"))
        )
    )
    monkeypatch.setattr(
        "server.services.market.verified_daily_market_data.provider_registry_for_config",
        lambda *_args, **_kwargs: registry,
    )
    return (
        VerifiedDailyMarketDataService(tmp_path / "research", _config()),
        primary,
        comparison,
    )


def _plan(db, *, members=None):
    return enqueue_verified_daily_market_jobs_for_range(
        db,
        _config(),
        SQLiteJobStore(db.path),
        instruments=STOCKS,
        start_date=DAYS[0],
        end_date=DAYS[-1],
        now=NOW,
        historical_range=True,
        session_instruments=members,
    )


def test_reverify_actual_capture_lineage_without_any_new_provider_call(
    tmp_path, monkeypatch
):
    import pandas as pd

    from data.market.capture import read_provider_raw_payload
    from data.market.cross_source import ingest_cross_source_daily_bars_range
    from data.market.quality import RESEARCH_STRICT_DAILY
    from data.market.verification_evidence import read_market_verification_evidence
    from data.providers.baostock import BaoStockDailyBarProvider
    from data.providers.tushare import TushareDailyBarProvider
    from tests.data.providers.test_baostock_daily import FakeBaoStock, FakeResult

    class Bao(FakeBaoStock):
        def query_history_k_data_plus(self, code, fields, **kwargs):
            self.query_calls.append(code)
            return FakeResult(
                [
                    [
                        day.isoformat(),
                        code,
                        "10",
                        "11",
                        "9",
                        "10",
                        "10000",
                        "100000.25",
                        "3",
                        "1",
                    ]
                    for day in DAYS
                ]
            )

    class TuShare:
        def __init__(self):
            self.calls = []

        def daily(self, **kwargs):
            self.calls.append(kwargs)
            return pd.DataFrame(
                {
                    "trade_date": [day.strftime("%Y%m%d") for day in DAYS],
                    "open": [10] * 3,
                    "high": [11] * 3,
                    "low": [9] * 3,
                    "close": [10] * 3,
                    "vol": [100] * 3,
                    "amount": [100] * 3,
                }
            )

    bao, ts = Bao(), TuShare()
    primary, comparison = (
        BaoStockDailyBarProvider(bao, clock=lambda: NOW),
        TushareDailyBarProvider(ts, clock=lambda: NOW),
    )
    registry = ProviderRegistry(
        tuple(
            ProviderRegistration(
                name=p.descriptor.provider,
                upstream_group=p.descriptor.upstream_group,
                daily_bar_factory=lambda p=p: p,
            )
            for p in (primary, comparison)
        )
    )
    monkeypatch.setattr(
        "server.services.market.verified_daily_market_data.provider_registry_for_config",
        lambda *_a, **_kw: registry,
    )
    db = _db(tmp_path, trading_days=DAYS)
    job = _plan(db)[0]
    planned = VerifiedDailyMarketJobRequest.from_payload(job.payload)
    objects = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    original = ingest_cross_source_daily_bars_range(
        primary,
        comparison,
        objects,
        request=DailyBarRequest(STOCKS, DAYS[0], DAYS[-1]),
        expected_sessions={day: STOCKS for day in DAYS},
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=NOW,
    )
    ids = tuple(row.verification.verification_id for row in original)
    assert all(row.verification_status == "conflict" for row in original)
    counts = len(bao.query_calls), len(ts.calls)

    def forbidden(*_a, **_kw):
        raise AssertionError("reverification_must_not_fetch")

    monkeypatch.setattr(bao, "query_history_k_data_plus", forbidden)
    monkeypatch.setattr(ts, "daily", forbidden)
    service = VerifiedDailyMarketDataService(tmp_path / "research", _config())
    result = service.reverify_captured_range(
        planned.to_payload(),
        verification_ids=ids,
        checked_at=NOW + timedelta(seconds=10),
    )
    restored = read_daily_bar_dataset(objects, result.dataset_ref)
    assert restored.row_count == 6 and restored.snapshot.verification_bound
    assert {bar.amount for bar in restored.bars} == {Decimal("100000.25")}
    assert (len(bao.query_calls), len(ts.calls)) == counts
    assert restored.snapshot.cutoff == NOW + timedelta(seconds=10)
    assert result.source_resolution.outcome == "captured_reverified"
    for evidence in original:
        assert (
            read_market_verification_evidence(
                objects, evidence.verification.ref
            ).status.value
            == "conflict"
        )
        read_provider_raw_payload(objects, evidence.primary.capture)
    with pytest.raises(ValueError, match="original_policy_or_time"):
        service.reverify_captured_range(
            planned.to_payload(),
            verification_ids=ids,
            checked_at=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="session_coverage_mismatch"):
        service.reverify_captured_range(
            planned.to_payload(),
            verification_ids=ids[:-1],
            checked_at=NOW + timedelta(seconds=10),
        )
    raw_path = objects._path_for(original[0].primary.capture.raw_object_ref.object_id)
    raw_path.chmod(0o644)
    raw_path.write_bytes(b"corrupt")
    with pytest.raises(Exception, match="integrity_mismatch"):
        service.reverify_captured_range(
            planned.to_payload(),
            verification_ids=ids,
            checked_at=NOW + timedelta(seconds=10),
        )


def test_range_planner_has_125_batches_for_5000_by_120_and_preserves_v1_identity(
    tmp_path,
):
    dates = tuple(date(2026, 5, 22) + timedelta(days=i) for i in range(120))
    db = SimpleNamespace(
        get_market_calendar_snapshot_sync=lambda **_kw: _calendar(
            trading_dates=set(dates)
        )
    )
    store = _store(tmp_path)
    keys = tuple(
        InstrumentKey(f"{600000 + i}", InstrumentType.STOCK) for i in range(5000)
    )
    jobs = enqueue_verified_daily_market_jobs_for_range(
        db,
        _config(),
        store,
        instruments=keys,
        start_date=dates[0],
        end_date=dates[-1],
        now=NOW,
        historical_range=True,
    )
    assert len(jobs) == 125
    assert all(len(job.payload["instruments"]) == 40 for job in jobs)
    assert all(
        len(VerifiedDailyMarketJobRequest.from_payload(job.payload).expected_sessions())
        == 120
        for job in jobs
    )
    repeated = enqueue_verified_daily_market_jobs_for_range(
        db,
        _config(),
        store,
        instruments=keys,
        start_date=dates[0],
        end_date=dates[-1],
        now=NOW,
        historical_range=True,
    )
    assert [job.job_id for job in repeated] == [job.job_id for job in jobs]
    legacy = VerifiedDailyMarketJobRequest(
        DAYS[0],
        keys[:40],
        _config().market_data_verification_source_policy,
        ("calendar:fixture",),
    ).to_payload()
    expected = {
        "schema_version": VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
        "trade_date": DAYS[0].isoformat(),
        "instruments": [
            {"symbol": key.symbol, "instrument_type": key.instrument_type.value}
            for key in keys[:40]
        ],
        "source_policy_id": _config().market_data_verification_source_policy,
        "calendar_evidence_refs": ["calendar:fixture"],
        "observation_round": "post_close.v1",
    }
    assert legacy == expected
    assert job_id_for(VERIFIED_DAILY_MARKET_JOB, legacy) == job_id_for(
        VERIFIED_DAILY_MARKET_JOB, expected
    )
    assert VerifiedDailyMarketJobRequest.from_payload(legacy).to_payload() == expected


def test_daily_and_range_payloads_keep_separate_instrument_bounds():
    keys = tuple(
        InstrumentKey(f"{600000 + index}", InstrumentType.STOCK) for index in range(101)
    )
    daily = VerifiedDailyMarketJobRequest(
        DAYS[-1],
        keys[:100],
        _config().market_data_verification_source_policy,
        ("calendar:fixture",),
    ).to_payload()
    assert len(VerifiedDailyMarketJobRequest.from_payload(daily).instruments) == 100
    with pytest.raises(VerifiedDailyMarketDataRequestError, match="batch_exceeded"):
        VerifiedDailyMarketJobRequest.from_payload(
            {
                **daily,
                "instruments": [
                    {"symbol": key.symbol, "instrument_type": key.instrument_type.value}
                    for key in keys
                ],
            }
        )
    oversized_range = VerifiedDailyMarketJobRequest(
        DAYS[-1],
        keys[:41],
        _config().market_data_verification_source_policy,
        ("calendar:fixture",),
        range_start_date=DAYS[0],
        range_end_date=DAYS[-1],
        session_memberships=tuple(
            (day, keys[:41], ("calendar:fixture",)) for day in DAYS
        ),
    ).to_payload()
    with pytest.raises(VerifiedDailyMarketDataRequestError, match="batch_exceeded"):
        VerifiedDailyMarketJobRequest.from_payload(oversized_range)


def test_range_capture_replays_daily_verification_and_composes_declared_members(
    tmp_path, monkeypatch
):
    db = _db(tmp_path, trading_days=DAYS)
    members = {DAYS[0]: (STOCKS[0],), DAYS[1]: STOCKS, DAYS[2]: STOCKS}
    (job,) = _plan(db, members=members)
    request = VerifiedDailyMarketJobRequest.from_payload(job.payload)
    assert request.is_range and request.trade_date == DAYS[-1]
    assert request.expected_sessions() == DAYS
    service, primary, comparison = _service(tmp_path, monkeypatch)
    admitted = []
    publication = service.run(
        job.payload,
        checked_at=NOW + timedelta(seconds=1),
        before_provider_fetch=lambda descriptor: admitted.append(descriptor.provider),
    )
    assert len(primary.calls) == len(comparison.calls) == 1
    assert admitted == [primary.descriptor.provider, comparison.descriptor.provider]
    objects = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    read = read_daily_bar_dataset(objects, publication.dataset_ref)
    assert len(read.bars) == 5
    assert read.snapshot.verification_bound
    assert all(row.available_at == NOW for row in read.bars)
    assert all(
        item.decision_at is None and not item.source_observation_ids
        for item in read.snapshot.session_memberships
    )
    captures = set()
    for part in read.snapshot.partitions:
        materialization = read_market_revision_materialization(
            objects, objects.resolve_ref(part.materialization_id)
        )
        captures.add(materialization.capture_ref.object_id)
    assert (
        len(captures) == 1
    )  # one primary range capture truthfully parents three daily shards
    capture = read_provider_capture(objects, objects.resolve_ref(captures.pop()))
    assert (
        json.loads(capture.request_json)
        == DailyBarRequest(STOCKS, DAYS[0], DAYS[-1]).to_capture_request()
    )
    assert capture.completed_at == NOW
    store = SQLiteJobStore(db.path)
    leased = store.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=NOW, job_id=job.job_id
    )
    store.finish(leased.lease, now=NOW, result_ref=publication.result_ref)
    summary = publish_verified_interval_dataset(
        tmp_path / "research",
        DailyBarRequest(STOCKS, DAYS[0], DAYS[-1]),
        db=db,
        job_ids=(job.job_id,),
        session_memberships=tuple(
            DailyBarDatasetMembership(day, keys, NOW) for day, keys in members.items()
        ),
        universe_policy_id="fixture.full.scope",
    )
    composed = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(summary["dataset_id"]))
    )
    assert composed.bars == read.bars
    assert composed.snapshot.instruments_for_session(DAYS[0]) == (STOCKS[0],)
    assert composed.snapshot.universe_policy_id == "fixture.full.scope"


@pytest.mark.parametrize("case", ["missing", "conflict"])
def test_range_never_promotes_partial_or_conflicting_days(tmp_path, monkeypatch, case):
    db = _db(tmp_path, trading_days=DAYS)
    (job,) = _plan(db)
    service, primary, comparison = _service(
        tmp_path,
        monkeypatch,
        missing=(DAYS[1], STOCKS[1]) if case == "missing" else None,
        conflict=case == "conflict",
    )
    with pytest.raises(
        VerifiedDailyMarketDataNotPublishable,
        match="quality_blocked" if case == "missing" else "cross_source_conflict",
    ) as caught:
        service.run(job.payload, checked_at=NOW + timedelta(seconds=1))
    evidence_ref = caught.value.failure_evidence_ref
    assert evidence_ref.startswith("quality:" if case == "missing" else "verification:")
    assert ContentAddressedObjectStore(tmp_path / "research" / "objects").resolve_ref(
        evidence_ref.split(":", 1)[1]
    )
    assert len(primary.calls) == len(comparison.calls) == 1
    assert not (tmp_path / "research" / "catalog" / "datasets.sqlite3").exists()


def test_range_payload_retains_empty_sessions_and_requires_explicit_version(tmp_path):
    db = _db(tmp_path, trading_days=DAYS)
    # The second 40-symbol transport batch may have no history on early sessions.
    keys = tuple(
        InstrumentKey(f"{600000 + i}", InstrumentType.STOCK) for i in range(41)
    )
    jobs = enqueue_verified_daily_market_jobs_for_range(
        db,
        _config(),
        SQLiteJobStore(db.path),
        instruments=keys,
        start_date=DAYS[0],
        end_date=DAYS[-1],
        now=NOW,
        historical_range=True,
        session_instruments={DAYS[0]: keys[:40], DAYS[1]: keys, DAYS[2]: keys},
    )
    request = VerifiedDailyMarketJobRequest.from_payload(jobs[1].payload)
    assert request.expected_sessions() == DAYS
    assert request.instruments_for_session(DAYS[0]) == ()
    assert request.calendar_refs_for_session(DAYS[0])
    assert (
        request.to_payload()["schema_version"]
        == VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION
    )
    with pytest.raises(
        VerifiedDailyMarketDataRequestError, match="range_schema_required"
    ):
        VerifiedDailyMarketJobRequest.from_payload(
            {
                **request.to_payload(),
                "schema_version": VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
            }
        )
    with pytest.raises(
        VerifiedDailyMarketDataRequestError, match="range_payload_invalid"
    ):
        VerifiedDailyMarketJobRequest.from_payload(
            {**request.to_payload(), "calendar_evidence_refs": ["unknown"]}
        )


def test_empty_history_batch_is_composed_without_adding_unobserved_members(
    tmp_path, monkeypatch
):
    db = _db(tmp_path, trading_days=DAYS)
    keys = tuple(
        InstrumentKey(f"{600000 + i}", InstrumentType.STOCK) for i in range(41)
    )
    members = {DAYS[0]: keys[:40], DAYS[1]: keys, DAYS[2]: keys}
    jobs = enqueue_verified_daily_market_jobs_for_range(
        db,
        _config(),
        SQLiteJobStore(db.path),
        instruments=keys,
        start_date=DAYS[0],
        end_date=DAYS[-1],
        now=NOW,
        historical_range=True,
        session_instruments=members,
    )
    service, primary, comparison = _service(tmp_path, monkeypatch)
    store = SQLiteJobStore(db.path)
    for job in jobs:
        leased = store.claim(
            VERIFIED_DAILY_MARKET_JOB, "fixture", now=NOW, job_id=job.job_id
        )
        publication = service.run(job.payload, checked_at=NOW)
        store.finish(leased.lease, now=NOW, result_ref=publication.result_ref)
    assert len(primary.calls) == len(comparison.calls) == 2
    summary = publish_verified_interval_dataset(
        tmp_path / "research",
        DailyBarRequest(keys, DAYS[0], DAYS[-1]),
        db=db,
        job_ids=tuple(job.job_id for job in jobs),
        session_memberships=tuple(
            DailyBarDatasetMembership(day, values, NOW)
            for day, values in members.items()
        ),
        universe_policy_id="fixture.scope",
    )
    assert summary["partition_count"] == 5
    assert summary["session_count"] == 3
    objects = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    read = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(summary["dataset_id"]))
    )
    assert len(read.bars) == 122
    assert read.snapshot.instruments_for_session(DAYS[0]) == keys[:40]
    assert read.snapshot.instruments_for_session(DAYS[-1]) == keys
    # Missing calendar sessions cannot be hidden by an incomplete range request.
    planned = VerifiedDailyMarketJobRequest.from_payload(jobs[0].payload)
    bad_payload = replace(
        planned,
        session_memberships=(
            planned.session_memberships[0],
            planned.session_memberships[-1],
        ),
    ).to_payload()
    bad = store.enqueue(VERIFIED_DAILY_MARKET_JOB, bad_payload, now=NOW)
    leased = store.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=NOW, job_id=bad.job_id
    )
    store.finish(leased.lease, now=NOW, result_ref=store.get(jobs[0].job_id).result_ref)
    with pytest.raises(ResearchDatasetError, match="job_calendar_mismatch"):
        publish_verified_interval_dataset(
            tmp_path / "research",
            DailyBarRequest(keys, DAYS[0], DAYS[-1]),
            db=db,
            job_ids=(bad.job_id, jobs[1].job_id),
            session_memberships=tuple(
                DailyBarDatasetMembership(day, values, NOW)
                for day, values in members.items()
            ),
            universe_policy_id="fixture.scope",
        )


def test_range_http_is_explicit_and_old_http_remains_daily(tmp_path):
    from tests.server.test_verified_daily_market_jobs import _verified_jobs_api

    client, _store = _verified_jobs_api(tmp_path, trading_dates=set(DAYS))
    payload = {
        "instruments": [
            {"symbol": key.symbol, "instrument_type": key.instrument_type.value}
            for key in STOCKS
        ],
        "start_date": DAYS[0].isoformat(),
        "end_date": DAYS[-1].isoformat(),
    }
    with client:
        old = client.post("/api/backtest/datasets/verified-jobs", json=payload)
        new = client.post(
            "/api/backtest/datasets/verified-jobs",
            json={**payload, "historical_range": True},
        )
        invalid = client.post(
            "/api/backtest/datasets/verified-jobs",
            json={**payload, "historical_range": "true"},
        )
        status = client.get(
            f"/api/backtest/datasets/verified-jobs/{new.json()['jobs'][0]['job_id']}"
        )
    assert old.status_code == new.status_code == status.status_code == 200
    assert len(old.json()["jobs"]) == 3
    assert len(new.json()["jobs"]) == 1
    assert invalid.status_code == 422
    assert (
        status.json()["schema_version"]
        == VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION
    )
    assert status.json()["range_start_date"] == DAYS[0].isoformat()
    assert status.json()["range_end_date"] == DAYS[-1].isoformat()
    assert all("range_start_date" not in job for job in old.json()["jobs"])


def test_range_calendar_expands_only_with_explicit_bounded_budget(tmp_path):
    from server.services.market.calendar import (
        resolve_verified_closed_trading_dates_in_range,
    )

    start, end = date(2025, 5, 1), date(2026, 9, 18)
    dates = {start, end}
    db = SimpleNamespace(
        get_market_calendar_snapshot_sync=lambda *, year, **_kw: _calendar(
            year, trading_dates=dates
        )
    )
    with pytest.raises(ValueError, match="range_invalid"):
        resolve_verified_closed_trading_dates_in_range(
            db, NOW, start_date=start, end_date=end
        )
    actual = resolve_verified_closed_trading_dates_in_range(
        db, NOW, start_date=start, end_date=end, maximum_calendar_days=3653
    )
    assert tuple(row.trade_date for row in actual) == (
        start.isoformat(),
        end.isoformat(),
    )
    store = _store(tmp_path)
    jobs = enqueue_verified_daily_market_jobs_for_range(
        db,
        _config(),
        store,
        instruments=STOCKS,
        start_date=start,
        end_date=end,
        now=NOW,
        historical_range=True,
    )
    assert len(jobs) == 1
    assert VerifiedDailyMarketJobRequest.from_payload(
        jobs[0].payload
    ).expected_sessions() == (start, end)
    with pytest.raises(ValueError, match="range_invalid"):
        resolve_verified_closed_trading_dates_in_range(
            db, NOW, start_date=start, end_date=end, maximum_calendar_days=3654
        )
