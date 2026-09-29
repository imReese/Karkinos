"""Frozen verified intervals reuse completed daily jobs without provider I/O."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DailyBarDatasetPartition, DailyBarDatasetSnapshot
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.market.capture import capture_provider_payload
from data.market.contracts import DailyBarRequest
from data.market.normalize import normalize_daily_bar
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import publish_market_quality_evidence
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    reconcile_daily_bar_revisions,
)
from data.market.revision import publish_daily_bar_revision
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market.verification_evidence import publish_market_verification_evidence
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.providers.tushare import TUSHARE_DAILY_BAR_DESCRIPTOR
from data.source_policy import FREE_CN_RESEARCH_V1
from data.storage.objects import ContentAddressedObjectStore
from server.contracts.http.backtest import StrategySignalPreviewRequest
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.http.backtest_endpoints.datasets import create_router
from server.persistence.jobs import SQLiteJobStore
from server.services.backtest_views.strategy_inputs import load_signal_preview_bars
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.research_datasets import (
    ResearchDatasetError,
    publish_verified_interval_dataset,
)
from server.services.verified_daily_market_data import (
    VerifiedDailyMarketJobRequest,
    verified_daily_resolver_policy_id,
)
from server.services.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB

DAYS = (date(2026, 9, 17), date(2026, 9, 18))
STOCK = InstrumentKey("600000", InstrumentType.STOCK)
POLICY_ID = FREE_CN_RESEARCH_V1.policy_id
NOW = datetime(2026, 9, 28, 8, tzinfo=timezone.utc)


def _calendar(*, source: str = "a" * 64) -> dict:
    days = []
    day = date(2026, 1, 1)
    while day.year == 2026:
        days.append({"date": day.isoformat(), "is_trading_day": day in DAYS})
        day += timedelta(days=1)
    return {
        "year": 2026,
        "exchange": "SSE",
        "days": days,
        "trading_day_count": len(DAYS),
        "closed_day_count": len(days) - len(DAYS),
        "source_fingerprint": source,
        "verification_source_fingerprint": source,
        "official_source_fingerprint": "b" * 64,
        "official_source_url": "https://example.test/calendar",
        "official_verified_at": "2026-09-28T08:00:00Z",
        "official_verified_by": "fixture",
        "official_verification_status": "verified",
    }


def _db(tmp_path: Path):
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    row = _calendar()
    return SimpleNamespace(
        path=database.path,
        get_market_calendar_snapshot_sync=lambda *, exchange, year: (
            row if exchange == "SSE" and year == 2026 else None
        ),
        calendar_row=row,
    )


def _side(store, day: date, descriptor):
    completed = datetime(day.year, day.month, day.day, 8, tzinfo=timezone.utc)
    checked = completed + timedelta(minutes=5)
    capture = capture_provider_payload(
        store,
        provider=descriptor.provider,
        operation="daily_bars",
        request=DailyBarRequest((STOCK,), day, day).to_capture_request(),
        raw_payload=f"{descriptor.provider}:{day.isoformat()}".encode(),
        payload_format=f"{descriptor.provider}.fixture.v1",
        adapter_version=descriptor.adapter_version,
        started_at=completed - timedelta(seconds=1),
        completed_at=completed,
        record_count=1,
    )
    bar = normalize_daily_bar(
        instrument=STOCK,
        session_date=day,
        event_time=completed - timedelta(hours=1),
        available_at=completed,
        captured_at=completed,
        open_value="10.31",
        high_value="10.52",
        low_value="10.20",
        close_value="10.48",
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )
    revision, materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=(bar,),
        normalizer_version="karkinos.market.normalize.v1",
    )
    quality = publish_market_quality_evidence(
        store,
        evaluate_daily_bar_revision(
            store,
            revision=revision,
            materialization=materialization,
            policy=RESEARCH_STRICT_DAILY,
            expected_instruments=(STOCK,),
            checked_at=checked,
        ),
    )
    return revision, materialization, quality


def _verified_day(root: Path, day: date):
    store = ContentAddressedObjectStore(root / "objects")
    primary = _side(store, day, TDX_PROVIDER_DESCRIPTOR)
    comparison = _side(store, day, TUSHARE_DAILY_BAR_DESCRIPTOR)
    verification = publish_market_verification_evidence(
        store,
        report=reconcile_daily_bar_revisions(
            store,
            primary_revision=primary[0],
            primary_materialization=primary[1],
            comparison_revision=comparison[0],
            comparison_materialization=comparison[1],
            policy=STRICT_DAILY_RECONCILIATION,
        ),
        primary_quality=primary[2],
        comparison_quality=comparison[2],
        primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
        comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
        policy=STRICT_DAILY_RECONCILIATION,
        checked_at=datetime(day.year, day.month, day.day, 8, 5, tzinfo=timezone.utc),
    )
    snapshot = DailyBarDatasetSnapshot(
        start_date=day,
        end_date=day,
        cutoff=verification.checked_at,
        instruments=(STOCK,),
        resolver_policy_id=verified_daily_resolver_policy_id(POLICY_ID),
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=(
            DailyBarDatasetPartition(
                partition_date=day,
                provider=primary[0].provider,
                revision_id=primary[0].ref.revision_id,
                materialization_id=primary[1].materialization_id,
                verification_id=verification.verification_id,
            ),
        ),
    )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    assert read_daily_bar_dataset(store, ref).snapshot == snapshot
    DatasetCatalog(root).register(store, ref)
    return ref


def _finished_job(db, day: date, dataset_id: str) -> str:
    calendar_ref = validate_verified_market_calendar(db.calendar_row).evidence_ref
    assert calendar_ref is not None
    store = SQLiteJobStore(db.path)
    payload = VerifiedDailyMarketJobRequest(
        trade_date=day,
        instruments=(STOCK,),
        source_policy_id=POLICY_ID,
        calendar_evidence_refs=(calendar_ref,),
    ).to_payload()
    queued = store.enqueue(VERIFIED_DAILY_MARKET_JOB, payload, now=NOW)
    claimed = store.claim(VERIFIED_DAILY_MARKET_JOB, "test-worker", now=NOW)
    assert claimed is not None and claimed.job_id == queued.job_id
    store.finish(claimed.lease, now=NOW, result_ref=f"dataset:{dataset_id}")
    return queued.job_id


def _request() -> DailyBarRequest:
    return DailyBarRequest((STOCK,), DAYS[0], DAYS[-1])


def test_verified_interval_limits_explicit_range_to_366_natural_days(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    monkeypatch.setattr(
        "server.services.research_datasets._verified_dates",
        lambda *_args: (DAYS[-1],),
    )
    start = DAYS[-1] - timedelta(days=365)
    allowed = DailyBarRequest((STOCK,), start, DAYS[-1])
    with pytest.raises(ResearchDatasetError, match="job_coverage_invalid"):
        publish_verified_interval_dataset(
            tmp_path / "research", allowed, db=db, job_ids=()
        )

    too_long = DailyBarRequest((STOCK,), start - timedelta(days=1), DAYS[-1])
    with pytest.raises(ResearchDatasetError, match="range_exceeds_366_days"):
        publish_verified_interval_dataset(
            tmp_path / "research", too_long, db=db, job_ids=()
        )


def test_exact_successful_jobs_publish_replayable_verified_interval(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    root = tmp_path / "research"
    refs = [_verified_day(root, day) for day in DAYS]
    job_ids = tuple(
        _finished_job(db, day, ref.dataset_id)
        for day, ref in zip(DAYS, refs, strict=True)
    )

    summary = publish_verified_interval_dataset(
        root, _request(), db=db, job_ids=tuple(reversed(job_ids))
    )
    store = ContentAddressedObjectStore(root / "objects")
    interval = read_daily_bar_dataset(
        store, DatasetCatalog(root).get(summary["dataset_id"]).ref
    )

    assert summary["partition_count"] == len(DAYS)
    assert summary["cross_source_verified"] is True
    assert summary["point_in_time_verified"] is False
    assert interval.snapshot.verification_bound
    assert tuple(bar.session_date for bar in interval.bars) == DAYS
    assert all(
        partition.verification_id is not None
        for partition in interval.snapshot.partitions
    )
    bars, preview_snapshot = load_signal_preview_bars(
        StrategySignalPreviewRequest(
            dataset_id=summary["dataset_id"],
            symbol=STOCK.symbol,
            asset_class="stock",
            start_date=DAYS[0].isoformat(),
            end_date=DAYS[-1].isoformat(),
        ),
        None,
        db,
    )
    assert len(bars) == len(DAYS)
    assert preview_snapshot["immutable_dataset_id"] == summary["dataset_id"]
    assert preview_snapshot["cross_source_verified"] is True
    assert preview_snapshot["point_in_time_verified"] is False
    assert preview_snapshot["price_basis"] == "unadjusted"
    assert (
        publish_verified_interval_dataset(root, _request(), db=db, job_ids=job_ids)[
            "dataset_id"
        ]
        == summary["dataset_id"]
    )


def test_verified_interval_http_publishes_only_explicit_completed_jobs(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    root = tmp_path / "research"
    refs = [_verified_day(root, day) for day in DAYS]
    job_ids = [
        _finished_job(db, day, ref.dataset_id)
        for day, ref in zip(DAYS, refs, strict=True)
    ]
    state = AppState()
    state.db = db
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(create_router())
    payload = {
        "symbol": STOCK.symbol,
        "instrument_type": STOCK.instrument_type.value,
        "start_date": DAYS[0].isoformat(),
        "end_date": DAYS[-1].isoformat(),
        "job_ids": job_ids,
    }

    with TestClient(app) as client:
        incomplete = client.post(
            "/api/backtest/datasets/verified-interval",
            json={**payload, "job_ids": job_ids[:1]},
        )
        published = client.post(
            "/api/backtest/datasets/verified-interval", json=payload
        )

    assert incomplete.status_code == 409, incomplete.text
    assert incomplete.json()["detail"] == "verified_interval_job_coverage_invalid"
    assert published.status_code == 200, published.text
    summary = published.json()
    assert summary["cross_source_verified"] is True
    assert summary["point_in_time_verified"] is False
    assert summary["partition_count"] == len(DAYS)
    ref = DatasetCatalog(root).get(summary["dataset_id"]).ref
    assert (
        tuple(
            bar.session_date
            for bar in read_daily_bar_dataset(
                ContentAddressedObjectStore(root / "objects"), ref
            ).bars
        )
        == DAYS
    )


def test_interval_requires_all_verified_trading_days_and_completed_jobs(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    root = tmp_path / "research"
    first = _verified_day(root, DAYS[0])
    first_job = _finished_job(db, DAYS[0], first.dataset_id)
    second = _verified_day(root, DAYS[1])
    calendar_ref = validate_verified_market_calendar(db.calendar_row).evidence_ref
    assert calendar_ref is not None
    pending = SQLiteJobStore(db.path).enqueue(
        VERIFIED_DAILY_MARKET_JOB,
        VerifiedDailyMarketJobRequest(
            trade_date=DAYS[1],
            instruments=(STOCK,),
            source_policy_id=POLICY_ID,
            calendar_evidence_refs=(calendar_ref,),
        ).to_payload(),
        now=NOW,
    )
    assert second.dataset_id.startswith("sha256:")

    with pytest.raises(ResearchDatasetError, match="job_coverage_invalid"):
        publish_verified_interval_dataset(root, _request(), db=db, job_ids=(first_job,))
    with pytest.raises(ResearchDatasetError, match="job_incomplete"):
        publish_verified_interval_dataset(
            root, _request(), db=db, job_ids=(first_job, pending.job_id)
        )
    assert DatasetCatalog(root).list_daily_bar_datasets()[0].partition_count == 1


def test_interval_rejects_wrong_job_result_and_legacy_daily_dataset(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    root = tmp_path / "research"
    first = _verified_day(root, DAYS[0])
    second = _verified_day(root, DAYS[1])
    first_job = _finished_job(db, DAYS[0], first.dataset_id)
    wrong_job = _finished_job(db, DAYS[1], first.dataset_id)
    with pytest.raises(ResearchDatasetError, match="daily_dataset_mismatch"):
        publish_verified_interval_dataset(
            root, _request(), db=db, job_ids=(first_job, wrong_job)
        )

    store = ContentAddressedObjectStore(root / "objects")
    verified = read_daily_bar_dataset(store, second).snapshot
    legacy = publish_daily_bar_dataset_manifest(
        store,
        replace(
            verified,
            partitions=(replace(verified.partitions[0], verification_id=None),),
        ),
    )
    calendar_ref = validate_verified_market_calendar(db.calendar_row).evidence_ref
    assert calendar_ref is not None
    alternate = SQLiteJobStore(db.path).enqueue(
        VERIFIED_DAILY_MARKET_JOB,
        VerifiedDailyMarketJobRequest(
            trade_date=DAYS[1],
            instruments=(STOCK,),
            source_policy_id=POLICY_ID,
            calendar_evidence_refs=(calendar_ref,),
            observation_round="post_close.v2",
        ).to_payload(),
        now=NOW,
    )
    claimed = SQLiteJobStore(db.path).claim(
        VERIFIED_DAILY_MARKET_JOB, "test-worker", now=NOW
    )
    assert claimed is not None and claimed.job_id == alternate.job_id
    SQLiteJobStore(db.path).finish(
        claimed.lease, now=NOW, result_ref=f"dataset:{legacy.dataset_id}"
    )
    with pytest.raises(ResearchDatasetError, match="daily_dataset_mismatch"):
        publish_verified_interval_dataset(
            root, _request(), db=db, job_ids=(first_job, alternate.job_id)
        )
    assert all(
        entry.partition_count == 1
        for entry in DatasetCatalog(root).list_daily_bar_datasets()
    )


def test_interval_rejects_verification_after_daily_cutoff(tmp_path: Path) -> None:
    db = _db(tmp_path)
    root = tmp_path / "research"
    first = _verified_day(root, DAYS[0])
    second = _verified_day(root, DAYS[1])
    store = ContentAddressedObjectStore(root / "objects")
    second_snapshot = read_daily_bar_dataset(store, second).snapshot
    early_cutoff = second_snapshot.cutoff - timedelta(minutes=1)
    too_early = publish_daily_bar_dataset_manifest(
        store, replace(second_snapshot, cutoff=early_cutoff)
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="dataset_reader_verification_after_cutoff"
    ):
        read_daily_bar_dataset(store, too_early)
    job_ids = (
        _finished_job(db, DAYS[0], first.dataset_id),
        _finished_job(db, DAYS[1], too_early.dataset_id),
    )

    with pytest.raises(ResearchDatasetError, match="daily_dataset_unreadable"):
        publish_verified_interval_dataset(root, _request(), db=db, job_ids=job_ids)
    assert all(
        entry.partition_count == 1
        for entry in DatasetCatalog(root).list_daily_bar_datasets()
    )
