from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.market.contracts import MarketDataProviderDescriptor
from data.market.normalize import normalize_daily_bar
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import publish_market_quality_evidence
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    reconcile_daily_bar_revisions,
)
from data.market.revision import publish_daily_bar_revision
from data.market.verification_evidence import (
    MarketVerificationEvidenceError,
    MarketVerificationEvidenceIntegrityError,
    MarketVerificationStatus,
    publish_market_verification_evidence,
    read_market_verification_evidence,
)
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.providers.tushare_daily import TUSHARE_DAILY_BAR_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 15)
CHECKED_AT = datetime(2026, 9, 15, 8, 5, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey("600000", InstrumentType.STOCK)


def _side(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    close: str = "10.48",
    expected=(INSTRUMENT,),
):
    captured = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
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
        started_at=captured - timedelta(seconds=1),
        completed_at=captured,
        record_count=1,
    )
    bar = normalize_daily_bar(
        instrument=INSTRUMENT,
        session_date=DAY,
        event_time=datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc),
        available_at=captured,
        captured_at=captured,
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
        expected_instruments=expected,
        checked_at=CHECKED_AT,
    )
    quality = publish_market_quality_evidence(store, report)
    return revision, materialization, quality


def _verification(
    store: ContentAddressedObjectStore,
    *,
    comparison_close: str = "10.48",
    comparison_descriptor: MarketDataProviderDescriptor = TUSHARE_DAILY_BAR_DESCRIPTOR,
):
    primary_revision, primary_materialization, primary_quality = _side(
        store, provider="tdx"
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
    evidence = publish_market_verification_evidence(
        store,
        report=report,
        primary_quality=primary_quality,
        comparison_quality=comparison_quality,
        primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
        comparison_descriptor=comparison_descriptor,
        policy=STRICT_DAILY_RECONCILIATION,
        checked_at=CHECKED_AT,
    )
    return evidence, primary_quality, comparison_quality


def test_matched_verification_round_trips_with_quality_lineage(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    evidence, primary_quality, comparison_quality = _verification(store)

    replayed = read_market_verification_evidence(store, evidence.ref)

    assert replayed == evidence
    assert replayed.status is MarketVerificationStatus.MATCHED
    assert replayed.primary_quality_id == primary_quality.quality_id
    assert replayed.comparison_quality_id == comparison_quality.quality_id
    assert (
        replayed.primary_materialization_id == primary_quality.report.materialization_id
    )
    assert (
        replayed.comparison_materialization_id
        == comparison_quality.report.materialization_id
    )


def test_conflict_is_preserved_as_immutable_verification_evidence(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    evidence, _, _ = _verification(store, comparison_close="10.49")

    replayed = read_market_verification_evidence(store, evidence.ref)

    assert replayed.status is MarketVerificationStatus.CONFLICT
    assert replayed.report.difference_count == 1
    assert replayed.report.differences[0].field == "close"
    assert replayed.report.differences[0].primary_value == "10.48000000"
    assert replayed.report.differences[0].comparison_value == "10.49000000"


def test_same_verification_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    first, primary_quality, comparison_quality = _verification(store)
    second = publish_market_verification_evidence(
        store,
        report=first.report,
        primary_quality=primary_quality,
        comparison_quality=comparison_quality,
        primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
        comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
        policy=STRICT_DAILY_RECONCILIATION,
        checked_at=CHECKED_AT,
    )

    assert second == first


def test_verification_rejects_same_upstream_group(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    same_upstream = replace(TUSHARE_DAILY_BAR_DESCRIPTOR, upstream_group="tdx")

    with pytest.raises(
        MarketVerificationEvidenceError,
        match="market_verification_upstream_groups_not_independent",
    ):
        _verification(store, comparison_descriptor=same_upstream)


def test_verification_requires_passing_quality_on_both_sides(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    primary_revision, primary_materialization, primary_quality = _side(
        store, provider="tdx"
    )
    comparison_revision, comparison_materialization, comparison_quality = _side(
        store,
        provider="tushare",
        expected=(
            INSTRUMENT,
            InstrumentKey("000001", InstrumentType.STOCK),
        ),
    )
    report = reconcile_daily_bar_revisions(
        store,
        primary_revision=primary_revision,
        primary_materialization=primary_materialization,
        comparison_revision=comparison_revision,
        comparison_materialization=comparison_materialization,
    )

    with pytest.raises(
        MarketVerificationEvidenceError,
        match="market_verification_comparison_quality_not_passing",
    ):
        publish_market_verification_evidence(
            store,
            report=report,
            primary_quality=primary_quality,
            comparison_quality=comparison_quality,
            primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
            comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
            policy=STRICT_DAILY_RECONCILIATION,
            checked_at=CHECKED_AT,
        )


def test_verification_replay_fails_if_referenced_quality_is_corrupted(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    evidence, _, comparison_quality = _verification(store)
    quality_path = (
        store.root
        / "sha256"
        / comparison_quality.ref.digest[:2]
        / comparison_quality.ref.digest[2:]
    )
    quality_path.chmod(0o644)
    quality_path.write_bytes(b"corrupted")

    with pytest.raises(
        MarketVerificationEvidenceIntegrityError,
        match="market_verification_quality_unreadable",
    ):
        read_market_verification_evidence(store, evidence.ref)
