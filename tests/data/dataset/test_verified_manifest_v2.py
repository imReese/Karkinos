from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MANIFEST_SCHEMA_VERSION_V2,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetPartition, DailyBarDatasetSnapshot
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import (
    publish_market_quality_evidence,
    read_market_quality_evidence,
)
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    reconcile_daily_bar_revisions,
)
from data.market.revision import (
    publish_daily_bar_revision,
    read_market_revision_materialization,
)
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market.verification_evidence import publish_market_verification_evidence
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.providers.tushare import TUSHARE_DAILY_BAR_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 15)
CAPTURED = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
CHECKED = datetime(2026, 9, 15, 8, 5, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey("600000", InstrumentType.STOCK)


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
            "instruments": [
                {
                    "symbol": INSTRUMENT.symbol,
                    "instrument_type": INSTRUMENT.instrument_type.value,
                }
            ],
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
    quality = publish_market_quality_evidence(
        store,
        evaluate_daily_bar_revision(
            store,
            revision=revision,
            materialization=materialization,
            policy=RESEARCH_STRICT_DAILY,
            expected_instruments=(INSTRUMENT,),
            checked_at=CHECKED,
        ),
    )
    return revision, materialization, quality


def _verified_snapshot(
    store: ContentAddressedObjectStore,
    *,
    comparison_close: str = "10.48",
):
    primary_revision, primary_materialization, primary_quality = _side(
        store, provider="tdx", close="10.48"
    )
    comparison_revision, comparison_materialization, comparison_quality = _side(
        store, provider="tushare", close=comparison_close
    )
    report = reconcile_daily_bar_revisions(
        store,
        primary_revision=primary_revision,
        primary_materialization=primary_materialization,
        comparison_revision=comparison_revision,
        comparison_materialization=comparison_materialization,
        policy=STRICT_DAILY_RECONCILIATION,
    )
    verification = publish_market_verification_evidence(
        store,
        report=report,
        primary_quality=primary_quality,
        comparison_quality=comparison_quality,
        primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
        comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
        policy=STRICT_DAILY_RECONCILIATION,
        checked_at=CHECKED,
    )
    snapshot = DailyBarDatasetSnapshot(
        start_date=DAY,
        end_date=DAY,
        cutoff=CHECKED,
        instruments=(INSTRUMENT,),
        resolver_policy_id="karkinos.dataset.verified.fixture.v1",
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=(
            DailyBarDatasetPartition(
                partition_date=DAY,
                provider="tdx",
                revision_id=primary_revision.ref.revision_id,
                materialization_id=primary_materialization.materialization_id,
                verification_id=verification.verification_id,
            ),
        ),
    )
    return snapshot, verification


def test_verified_snapshot_publishes_manifest_v2_and_replays(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    snapshot, verification = _verified_snapshot(store)

    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    payload = json.loads(store.read_bytes(ref.manifest_ref))
    replayed = read_daily_bar_dataset(store, ref)

    assert DATASET_MANIFEST_SCHEMA_VERSION == "karkinos.dataset_manifest.v1"
    assert payload["schema_version"] == DATASET_MANIFEST_SCHEMA_VERSION_V2
    assert payload["partitions"][0]["verification_id"] == verification.verification_id
    assert replayed.snapshot == snapshot
    assert replayed.bars[0].close == replayed.bars[0].close.__class__("10.48000000")


def test_manifest_v2_rejects_verification_after_snapshot_cutoff(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    snapshot, verification = _verified_snapshot(store)
    ref = publish_daily_bar_dataset_manifest(
        store, replace(snapshot, cutoff=verification.checked_at - timedelta(seconds=1))
    )

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_verification_after_cutoff",
    ):
        read_daily_bar_dataset(store, ref)


def test_manifest_v2_rejects_conflict_verification_on_replay(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    snapshot, _ = _verified_snapshot(store, comparison_close="10.49")
    ref = publish_daily_bar_dataset_manifest(store, snapshot)

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_verification_not_matched",
    ):
        read_daily_bar_dataset(store, ref)


def test_manifest_v2_rejects_verification_bound_to_different_lineage(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    snapshot, verification = _verified_snapshot(store)
    other_revision, other_materialization, _ = _side(
        store, provider="tdx", close="10.50"
    )
    forged = DailyBarDatasetSnapshot(
        start_date=DAY,
        end_date=DAY,
        cutoff=CHECKED,
        instruments=(INSTRUMENT,),
        resolver_policy_id=snapshot.resolver_policy_id,
        market_schema_version=snapshot.market_schema_version,
        partitions=(
            DailyBarDatasetPartition(
                partition_date=DAY,
                provider="tdx",
                revision_id=other_revision.ref.revision_id,
                materialization_id=other_materialization.materialization_id,
                verification_id=verification.verification_id,
            ),
        ),
    )
    ref = publish_daily_bar_dataset_manifest(store, forged)

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_verification_lineage_mismatch",
    ):
        read_daily_bar_dataset(store, ref)


def test_verified_replay_rejects_corrupt_comparison_materialization(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    snapshot, verification = _verified_snapshot(store)
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    assert read_daily_bar_dataset(store, ref).snapshot == snapshot

    comparison = read_market_revision_materialization(
        store, store.resolve_ref(verification.comparison_materialization_id)
    )
    digest = comparison.artifact.object_ref.digest
    artifact_path = store.root / "sha256" / digest[:2] / digest[2:]
    artifact_path.chmod(0o600)
    artifact_path.write_bytes(b"broken comparison parquet")

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_verification_materialization_unreadable",
    ):
        read_daily_bar_dataset(store, ref)


def test_verified_replay_recomputes_cross_source_conclusion(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    conflicted, verification = _verified_snapshot(store, comparison_close="10.49")
    assert verification.report.differences

    forged = publish_market_verification_evidence(
        store,
        report=replace(verification.report, differences=()),
        primary_quality=read_market_quality_evidence(
            store, store.resolve_ref(verification.primary_quality_id)
        ),
        comparison_quality=read_market_quality_evidence(
            store, store.resolve_ref(verification.comparison_quality_id)
        ),
        primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
        comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
        policy=verification.policy,
        checked_at=verification.checked_at,
    )
    forged_snapshot = replace(
        conflicted,
        partitions=(
            replace(conflicted.partitions[0], verification_id=forged.verification_id),
        ),
    )
    ref = publish_daily_bar_dataset_manifest(store, forged_snapshot)

    with pytest.raises(
        DatasetReaderIntegrityError,
        match="dataset_reader_verification_report_mismatch",
    ):
        read_daily_bar_dataset(store, ref)


def test_snapshot_rejects_mixed_verified_and_legacy_partitions() -> None:
    fake = lambda digit: f"sha256:{digit * 64}"
    with pytest.raises(ValueError, match="dataset_partition_verification_mixed"):
        DailyBarDatasetSnapshot(
            start_date=date(2026, 9, 15),
            end_date=date(2026, 9, 16),
            cutoff=CAPTURED,
            instruments=(INSTRUMENT,),
            resolver_policy_id="fixture",
            market_schema_version=DAILY_BAR_SCHEMA_VERSION,
            partitions=(
                DailyBarDatasetPartition(
                    partition_date=date(2026, 9, 15),
                    provider="tdx",
                    revision_id=fake("1"),
                    materialization_id=fake("2"),
                    verification_id=fake("3"),
                ),
                DailyBarDatasetPartition(
                    partition_date=date(2026, 9, 16),
                    provider="tdx",
                    revision_id=fake("4"),
                    materialization_id=fake("5"),
                ),
            ),
        )
