"""Fallback preserves budgets, complete scope, raw provenance and disagreements."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import read_daily_bar_dataset
from data.market.capture import read_provider_capture
from data.market.contracts import DailyBarRequest
from data.provider_registry import ProviderRegistration, ProviderRegistry
from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.providers.eastmoney import AKSHARE_DAILY_BAR_DESCRIPTOR
from data.providers.tencent import (
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
    AkshareTencentDailyBarProvider,
)
from data.providers.tushare import TushareDailyBarProvider
from data.storage.objects import ContentAddressedObjectStore
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_daily_call_budget import (
    BUDGET_DEFERRED_CODE,
    market_daily_provider_call_budget_status,
    reserve_market_daily_provider_call,
)
from server.services.market.verified_daily_market_data import (
    VerifiedDailyMarketDataNotPublishable,
    VerifiedDailyMarketDataService,
    VerifiedDailyMarketJobRequest,
    provider_fallback_recovery_payload,
)
from server.services.research.datasets import (
    ResearchDatasetError,
    verified_daily_job_successor,
)
from server.workers.data_worker import execute_verified_daily_market_job
from tests.server.test_verified_daily_market_data import (
    CAPTURED,
    CHECKED,
    DAY,
    FakeDailyProvider,
)

STOCKS = tuple(
    InstrumentKey(symbol, InstrumentType.STOCK) for symbol in ("600000", "600001")
)
DESCRIPTORS = (
    BAOSTOCK_DAILY_BAR_DESCRIPTOR,
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
    AKSHARE_DAILY_BAR_DESCRIPTOR,
)


def baostock_status_batch(batch, request, suspended):
    """Encode explicit dated tradestatus, including omitted normalized halt rows."""
    fields = [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjustflag",
        "tradestatus",
    ]
    calls = []
    for key in request.instruments:
        code = ("sh." if key.symbol.startswith("6") else "sz.") + key.symbol
        rows = [
            [
                row.session_date.isoformat(),
                code,
                *[
                    str(value)
                    for value in (
                        row.open_value,
                        row.high_value,
                        row.low_value,
                        row.close_value,
                        row.volume,
                        row.amount,
                    )
                ],
                "3",
                "1",
            ]
            for row in batch.rows
            if row.instrument == key
        ]
        rows.extend(
            [day.isoformat(), code, "9.06", "9.06", "9.06", "9.06", "", "", "3", "0"]
            for day, instrument in suspended
            if instrument == key
        )
        calls.append({"code": code, "fields": fields, "rows": sorted(rows)})
    schema = "baostock.history_k_data_plus.rows.v2"
    return replace(
        batch,
        payload_format=schema,
        raw_payload=json.dumps(
            {
                "schema": schema,
                "request": {
                    "frequency": "d",
                    "adjustflag": "3",
                    "start_date": request.start_date.isoformat(),
                    "end_date": request.end_date.isoformat(),
                    "fields": fields,
                },
                "calls": calls,
            }
        ).encode(),
    )


class CoverageProvider(FakeDailyProvider):
    def __init__(self, descriptor, *, missing=(), suspended=(), **kwargs):
        super().__init__(descriptor, **kwargs)
        self.missing = set(missing)
        self.suspended = set(suspended)

    def _row(self, instrument):
        return replace(
            super()._row(instrument), volume=Decimal("10000"), amount=Decimal("90600")
        )

    def fetch_daily_bars(self, request):
        batch = super().fetch_daily_bars(request)
        batch = replace(
            batch,
            rows=tuple(row for row in batch.rows if row.instrument not in self.missing),
        )
        if self.descriptor.provider == "baostock":
            return baostock_status_batch(
                batch, request, {(DAY, key) for key in self.suspended}
            )
        return replace(batch, raw_payload=repr(batch.rows).encode())


def service_with_sources(tmp_path, monkeypatch, sources):
    registry = ProviderRegistry(
        tuple(
            ProviderRegistration(
                name=p.descriptor.provider,
                upstream_group=p.descriptor.upstream_group,
                daily_bar_factory=lambda p=p: p,
            )
            for p in sources
        )
    )

    def configured(_config, *, include_tdx):
        assert include_tdx is False
        return registry

    monkeypatch.setattr(
        "server.services.market.verified_daily_market_data.provider_registry_for_config",
        configured,
    )
    return VerifiedDailyMarketDataService(tmp_path / "research", SimpleNamespace())


def payload(*, range_request=False):
    request = VerifiedDailyMarketJobRequest(
        DAY, STOCKS, "karkinos.market.source.free_cn_research.v1", ("calendar:fixture",)
    )
    if range_request:
        request = replace(
            request,
            range_start_date=DAY,
            range_end_date=DAY,
            session_memberships=((DAY, STOCKS, request.calendar_evidence_refs),),
        )
    return request.to_payload()


@pytest.mark.parametrize(
    "case", ["matched", "wrong_scope", "old_capture", "original_conflict", "pending"]
)
def test_bk_successor_replays_scope_and_fresh_captures_without_changing_failure(
    tmp_path, monkeypatch, case
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    jobs = SQLiteJobStore(db.path)
    original_payload = payload()
    now = CAPTURED - timedelta(seconds=30)
    original = jobs.enqueue("market_daily_verified", original_payload, now=now)
    claimed = jobs.claim(original.kind, "original", now=now, lease_seconds=600)
    partial = service_with_sources(
        tmp_path,
        monkeypatch,
        [
            CoverageProvider(DESCRIPTORS[0], missing=(STOCKS[1],)),
            CoverageProvider(DESCRIPTORS[1]),
        ],
    )
    with pytest.raises(VerifiedDailyMarketDataNotPublishable) as failed:
        partial.run(original_payload, checked_at=CHECKED)
    jobs.fail(
        claimed.lease,
        now=CHECKED,
        error="verified_daily_market_cross_source_conflict"
        if case == "original_conflict"
        else str(failed.value),
        failure_evidence_ref=failed.value.failure_evidence_ref,
        retryable=False,
    )
    original = jobs.get(original.job_id)
    recovery_payload = provider_fallback_recovery_payload(original_payload)
    successor = jobs.enqueue(
        original.kind, recovery_payload, now=CHECKED + timedelta(seconds=1)
    )
    assert successor.job_id != original.job_id
    if case == "pending":
        assert verified_daily_job_successor(jobs, original) == original
        return
    claimed = jobs.claim(
        original.kind, "recovery", now=CHECKED + timedelta(seconds=2), lease_seconds=600
    )

    class FreshProvider(CoverageProvider):
        def fetch_daily_bars(self, request):
            batch = super().fetch_daily_bars(request)
            if case == "old_capture":
                return batch
            return replace(
                batch,
                started_at=CHECKED + timedelta(seconds=3),
                completed_at=CHECKED + timedelta(seconds=4),
            )

    service = service_with_sources(
        tmp_path, monkeypatch, [FreshProvider(d) for d in DESCRIPTORS[:2]]
    )
    captured_payload = recovery_payload
    if case == "wrong_scope":
        captured_payload = {
            **recovery_payload,
            "instruments": recovery_payload["instruments"][:1],
        }
    publication = service.run(
        captured_payload, checked_at=CHECKED + timedelta(seconds=5)
    )
    jobs.finish(
        claimed.lease,
        now=CHECKED + timedelta(seconds=6),
        result_ref=publication.result_ref,
    )
    if case in {"wrong_scope", "old_capture"}:
        with pytest.raises(ResearchDatasetError, match="scope"):
            verified_daily_job_successor(jobs, original)
    elif case == "original_conflict":
        assert verified_daily_job_successor(jobs, original) == original
    else:
        resolved = verified_daily_job_successor(jobs, original)
        assert resolved.job_id == successor.job_id and resolved.status == "succeeded"
        assert resolved.result_ref == publication.result_ref
    assert jobs.get(original.job_id) == original


@pytest.mark.parametrize("missing_provider", [0, 1])
@pytest.mark.parametrize("range_request", [False, True])
def test_missing_rows_continue_to_complete_pair_with_original_lineage(
    tmp_path, monkeypatch, missing_provider, range_request
):
    sources = [
        CoverageProvider(d, missing=(STOCKS[1],) if i == missing_provider else ())
        for i, d in enumerate(DESCRIPTORS)
    ]
    service = service_with_sources(tmp_path, monkeypatch, sources)
    publication = service.run(payload(range_request=range_request), checked_at=CHECKED)
    assert all(len(p.calls) == 1 for p in sources)
    assert (
        sources[missing_provider].descriptor.provider
        not in publication.source_resolution.selected_pair
    )
    store = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    replay = read_daily_bar_dataset(store, publication.dataset_ref)
    assert {row.instrument for row in replay.bars} == set(STOCKS)
    attempts = publication.source_resolution.to_payload()["provider_attempts"]
    filled = [a for a in attempts if a["outcome"] == "missing_records_completed"]
    assert len(filled) == 1
    assert filled[0]["instruments"] == [
        {"symbol": "600001", "instrument_type": "stock"}
    ]
    assert len(filled[0]["selected_sources"]) == 2
    original = read_provider_capture(store, store.resolve_ref(filled[0]["capture_id"]))
    assert original.record_count == 1 and original.completed_at == CAPTURED
    assert (
        json.loads(original.request_json)
        == DailyBarRequest(STOCKS, DAY, DAY).to_capture_request()
    )
    for source in filled[0]["selected_sources"]:
        capture = read_provider_capture(store, store.resolve_ref(source["capture_id"]))
        assert capture.provider == source["provider"] and capture.record_count == 2
    # Re-read the rejected original after publication: it has not been overwritten.
    assert read_provider_capture(store, original.capture_ref) == original


def test_partial_missing_cannot_hide_conflict_on_existing_row(tmp_path, monkeypatch):
    sources = [
        CoverageProvider(DESCRIPTORS[0], missing=(STOCKS[1],)),
        CoverageProvider(DESCRIPTORS[1], close_offset=Decimal("0.01")),
        CoverageProvider(DESCRIPTORS[2]),
    ]
    service = service_with_sources(tmp_path, monkeypatch, sources)
    with pytest.raises(
        VerifiedDailyMarketDataNotPublishable, match="cross_source_conflict"
    ) as caught:
        service.run(payload(), checked_at=CHECKED)
    assert caught.value.source_resolution.outcome == "conflict"
    assert caught.value.failure_evidence_ref.startswith("quality:")
    assert [len(p.calls) for p in sources] == [1, 1, 0]
    assert not DatasetCatalog(service.root).path.exists()


@pytest.mark.parametrize("conflict", [False, True])
def test_budget_skip_then_partial_gap_uses_remaining_two_sources(
    tmp_path, monkeypatch, conflict
):
    now = datetime.now(timezone.utc)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    jobs = SQLiteJobStore(db.path)
    jobs.enqueue("market_daily_verified", payload(), now=now)
    job = jobs.claim("market_daily_verified", "fixture-worker", now=now)
    assert job is not None
    reserve_market_daily_provider_call(
        db.path, job.lease, DESCRIPTORS[0], now=now, daily_limit=1
    )
    calls = []

    class SDK:
        __version__ = "1.18.97"

        def stock_zh_a_hist_tx(self, **kwargs):
            calls.append(("tencent", kwargs))
            if kwargs["symbol"].endswith("600001"):
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    dict(
                        date=DAY.isoformat(),
                        open=9.06,
                        high=9.07,
                        low=9.05,
                        close=9.06,
                        volume=10000,
                        amount=90600,
                    )
                ]
            )

        def daily(self, **kwargs):
            calls.append(("tushare", kwargs))
            assert kwargs == {"trade_date": DAY.strftime("%Y%m%d")}
            return pd.DataFrame(
                [
                    dict(
                        ts_code=key.symbol + ".SH",
                        trade_date=DAY.strftime("%Y%m%d"),
                        open=9.06,
                        high=9.07,
                        low=9.05,
                        close=9.06,
                        vol=100,
                        amount=90.6,
                    )
                    for key in STOCKS
                ]
            )

    sdk = SDK()
    sources = [
        CoverageProvider(DESCRIPTORS[0]),
        AkshareTencentDailyBarProvider(sdk, clock=lambda: CAPTURED),
        CoverageProvider(
            DESCRIPTORS[2], close_offset=Decimal("0.01") if conflict else Decimal("0")
        ),
        TushareDailyBarProvider(sdk, clock=lambda: CAPTURED),
    ]
    service = service_with_sources(tmp_path, monkeypatch, sources)
    if conflict:
        with pytest.raises(
            VerifiedDailyMarketDataNotPublishable, match="cross_source_conflict"
        ) as caught:
            service.run(
                payload(),
                checked_at=CHECKED,
                before_provider_fetch=lambda d: reserve_market_daily_provider_call(
                    db.path, job.lease, d, now=now, daily_limit=1, defer_job=False
                ),
            )
        assert caught.value.source_resolution.outcome == "conflict"
        assert [provider for provider, _ in calls] == ["tencent", "tencent"]
        assert not DatasetCatalog(service.root).path.exists()
        return
    publication = service.run(
        payload(),
        checked_at=CHECKED,
        before_provider_fetch=lambda d: reserve_market_daily_provider_call(
            db.path, job.lease, d, now=now, daily_limit=1, defer_job=False
        ),
    )
    assert publication.source_resolution.selected_pair == ("akshare", "tushare")
    assert not sources[0].calls and len(sources[2].calls) == 1
    assert [provider for provider, _ in calls] == ["tencent", "tencent", "tushare"]
    assert jobs.get(job.job_id).status == "running"
    attempts = publication.source_resolution.to_payload()["provider_attempts"]
    assert any(a["outcome"] == "budget_exhausted" for a in attempts)
    assert any(
        a["outcome"] == "missing_records_completed"
        and a["provider"] == "akshare_tencent"
        for a in attempts
    )


@pytest.mark.parametrize("all_suspended", [False, True])
def test_explicit_suspension_is_never_filled_with_trading_rows(
    tmp_path, monkeypatch, all_suspended
):
    missing = STOCKS if all_suspended else (STOCKS[1],)
    sources = [
        CoverageProvider(DESCRIPTORS[0], missing=missing, suspended=missing),
        CoverageProvider(DESCRIPTORS[1]),
        CoverageProvider(DESCRIPTORS[2]),
    ]
    service = service_with_sources(tmp_path, monkeypatch, sources)
    reason = (
        "suspension_requires_status" if all_suspended else "trade_coverage_conflict"
    )
    with pytest.raises(VerifiedDailyMarketDataNotPublishable, match=reason) as caught:
        service.run(payload(), checked_at=CHECKED)
    assert caught.value.failure_evidence_ref.startswith(
        "capture:" if all_suspended else "quality:"
    )
    assert len(sources[2].calls) == 0
    assert not DatasetCatalog(service.root).path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", [1, 3])
@pytest.mark.parametrize("range_request", [False, True])
async def test_worker_skips_only_exhausted_providers_and_defers_after_all_pairs(
    tmp_path, monkeypatch, exhausted, range_request
):
    now = datetime.now(timezone.utc)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    jobs = SQLiteJobStore(db.path)
    queued = jobs.enqueue(
        "market_daily_verified", payload(range_request=range_request), now=now
    )
    job = jobs.claim("market_daily_verified", "fixture-worker", now=now)
    assert job is not None
    for descriptor in DESCRIPTORS[:exhausted]:
        reserve_market_daily_provider_call(
            db.path, job.lease, descriptor, now=now, daily_limit=1
        )
    sources = [CoverageProvider(d) for d in DESCRIPTORS]
    service = service_with_sources(tmp_path, monkeypatch, sources)
    events = []

    def before_fetch(descriptor):
        # The first exhausted source must leave the lease valid for later calls.
        assert jobs.get(job.job_id).status == "running"
        reserve_market_daily_provider_call(
            db.path, job.lease, descriptor, now=now, daily_limit=1, defer_job=False
        )

    await execute_verified_daily_market_job(
        jobs,
        job,
        service,
        before_provider_fetch=before_fetch,
        source_resolution_recorder=events.append,
    )
    persisted = jobs.get(queued.job_id)
    assert len(events) == 1
    skips = [a for a in events[0]["provider_attempts"] if "used" in a]
    # Once both independent partners are unavailable, there is no useful
    # two-source call for the last provider. Do not spend its budget speculatively.
    assert len(skips) == (1 if exhausted == 1 else 2)
    assert all(
        a["outcome"] == "budget_exhausted" and a["used"] == a["limit"] == 1
        for a in skips
    )
    budget = market_daily_provider_call_budget_status(db.path, now=now, daily_limit=1)
    assert all(budget["groups"][d.upstream_group]["used"] == 1 for d in DESCRIPTORS)
    with sqlite3.connect(db.path) as conn:
        max_attempts = conn.execute(
            "select max_attempts from job_runs where job_id=?", (job.job_id,)
        ).fetchone()[0]
    if exhausted == 1:
        assert persisted.status == "succeeded" and persisted.result_ref.startswith(
            "dataset:"
        )
        assert [len(p.calls) for p in sources] == [0, 1, 1]
        assert max_attempts == 3
    else:
        assert any(
            a["provider"] == "akshare" and a["outcome"] == "no_independent_pair"
            for a in events[0]["provider_attempts"]
        )
        assert persisted.status == "queued" and persisted.error == BUDGET_DEFERRED_CODE
        reset_at = datetime.fromisoformat(budget["reset_at"])
        assert (
            reset_at
            <= datetime.fromisoformat(persisted.available_at)
            < reset_at + timedelta(seconds=1)
        )
        assert max_attempts == 4 and persisted.attempt == 1
        assert all(not p.calls for p in sources)
        assert not DatasetCatalog(service.root).path.exists()
        assert datetime.fromisoformat(persisted.available_at) - now <= timedelta(days=1)
