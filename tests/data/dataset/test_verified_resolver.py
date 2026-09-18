from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import read_daily_bar_dataset
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    DailyBarResolutionCandidate,
    DatasetPartitionUnresolvedError,
    DatasetResolverIntegrityError,
    resolve_daily_bar_dataset,
)
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import publish_market_quality_evidence
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    reconcile_daily_bar_revisions,
)
from data.market.revision import publish_daily_bar_revision
from data.market.verification_evidence import publish_market_verification_evidence
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.providers.tushare_daily import TUSHARE_DAILY_BAR_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 15)
CAPTURED = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
CHECKED = datetime(2026, 9, 15, 8, 5, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey("600000", InstrumentType.STOCK)
POLICY = DailyBarDatasetResolverPolicy(
    policy_id="karkinos.dataset.pit.verified.v1",
    provider_priority=("tdx", "tushare"),
    required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
)


def _side(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    close: str,
):
    capture = capture_provider_payload(
        store,
        provider=provider,
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": DAY.isoformat(),
            "end_date": DAY.isoformat(),
            "instruments": [{"symbol": INSTRUMENT.symbol, "instrument_type": "stock"}],
        },
        raw_payload=f"{provider}:{close}".encode(),
        payload_format=f"{provider}.fixture.v1",
        adapter_version=f"karkinos.{provider}.fixture.v1",
        started_at=CAPTURED - timedelta(seconds=1),
        completed_at=CAPTURED,
        record_count=1,
    )
    bar = normalize_daily_bar(
        instrument=INSTRUMENT,
        session_date=DAY,
        event_time=datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc),
        available_at=CAPTURED,
        captured_at=CAPTURED,
        open_value="10.31",
        high_value="10.52",
        low_value="10.20",
        close_value=close,
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
    report = evaluate_daily_bar_revision(
        store,
        revision=revision,
        materialization=materialization,
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=(INSTRUMENT,),
        checked_at=CHECKED,
    )
    quality = publish_market_quality_evidence(store, report)
    return revision, materialization, quality


def _pair(
    store: ContentAddressedObjectStore,
    *,
    comparison_close: str = "10.48",
):
    primary = _side(store, provider="tdx", close="10.48")
    comparison = _side(store, provider="tushare", close=comparison_close)
    report = reconcile_daily_bar_revisions(
        store,
        primary_revision=primary[0],
        primary_materialization=primary[1],
        comparison_revision=comparison[0],
        comparison_materialization=comparison[1],
        policy=STRICT_DAILY_RECONCILIATION,
    )
    verification = publish_market_verification_evidence(
        store,
        report=report,
        primary_quality=primary[2],
        comparison_quality=comparison[2],
        primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
        comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
        policy=STRICT_DAILY_RECONCILIATION,
        checked_at=CHECKED,
    )
    return primary, comparison, verification


def _resolve(
    store: ContentAddressedObjectStore,
    candidate: DailyBarResolutionCandidate,
):
    return resolve_daily_bar_dataset(
        store,
        candidates=(candidate,),
        start_date=DAY,
        end_date=DAY,
        cutoff=CAPTURED,
        instruments=(INSTRUMENT,),
        expected_partition_dates=(DAY,),
        policy=POLICY,
    )


def test_resolver_propagates_matched_verification_into_manifest_v2(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    primary, _, verification = _pair(store)
    candidate = DailyBarResolutionCandidate(
        revision=primary[0],
        materialization=primary[1],
        quality=primary[2].report,
        verification=verification,
    )

    snapshot = _resolve(store, candidate)
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    replayed = read_daily_bar_dataset(store, ref)

    assert snapshot.verification_bound
    assert snapshot.partitions[0].verification_id == verification.verification_id
    assert replayed.snapshot == snapshot


def test_resolver_does_not_publish_conflict_verification(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    primary, _, verification = _pair(store, comparison_close="10.49")
    candidate = DailyBarResolutionCandidate(
        revision=primary[0],
        materialization=primary[1],
        quality=primary[2].report,
        verification=verification,
    )

    with pytest.raises(DatasetPartitionUnresolvedError):
        _resolve(store, candidate)


def test_resolver_rejects_verification_from_different_lineage(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    _, _, verification = _pair(store)
    unrelated = _side(store, provider="tdx", close="10.50")
    candidate = DailyBarResolutionCandidate(
        revision=unrelated[0],
        materialization=unrelated[1],
        quality=unrelated[2].report,
        verification=verification,
    )

    with pytest.raises(
        DatasetResolverIntegrityError,
        match="dataset_resolver_verification_lineage_mismatch",
    ):
        _resolve(store, candidate)
