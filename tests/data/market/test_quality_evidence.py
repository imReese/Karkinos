from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import (
    MarketQualityEvidenceIntegrityError,
    publish_market_quality_evidence,
    read_market_quality_evidence,
)
from data.market.revision import publish_daily_bar_revision
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 15)
CHECKED_AT = datetime(2026, 9, 15, 8, 1, tzinfo=timezone.utc)


def _report(store: ContentAddressedObjectStore, *, checked_at=CHECKED_AT):
    captured = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
    capture = capture_provider_payload(
        store,
        provider="tdx",
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": DAY.isoformat(),
            "end_date": DAY.isoformat(),
            "instruments": [{"symbol": "600000", "instrument_type": "stock"}],
        },
        raw_payload=b"fixture",
        payload_format="fixture.v1",
        adapter_version="fixture.v1",
        started_at=captured - timedelta(seconds=1),
        completed_at=captured,
        record_count=1,
    )
    bar = normalize_daily_bar(
        instrument=InstrumentKey("600000", InstrumentType.STOCK),
        session_date=DAY,
        event_time=datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc),
        available_at=captured,
        captured_at=captured,
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
    return evaluate_daily_bar_revision(
        store,
        revision=revision,
        materialization=materialization,
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=(bar.instrument,),
        checked_at=checked_at,
    )


def test_quality_evidence_round_trips_from_immutable_store(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    report = _report(store)
    evidence = publish_market_quality_evidence(store, report)
    replayed = read_market_quality_evidence(store, evidence.ref)
    assert replayed == evidence
    assert replayed.report == report
    assert replayed.quality_id.startswith("sha256:")


def test_quality_evidence_publication_is_idempotent(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    report = _report(store)
    first = publish_market_quality_evidence(store, report)
    second = publish_market_quality_evidence(store, report)
    assert first == second


def test_quality_evidence_checked_at_is_part_of_exact_decision(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    first = publish_market_quality_evidence(store, _report(store))
    second = publish_market_quality_evidence(
        store, _report(store, checked_at=CHECKED_AT + timedelta(seconds=1))
    )
    assert first.quality_id != second.quality_id


def test_quality_evidence_rejects_corrupted_object(tmp_path: Path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    evidence = publish_market_quality_evidence(store, _report(store))
    path = store.root / "sha256" / evidence.ref.digest[:2] / evidence.ref.digest[2:]
    path.chmod(0o644)
    path.write_bytes(b"corrupted")
    with pytest.raises(
        MarketQualityEvidenceIntegrityError,
        match="market_quality_evidence_object_unreadable",
    ):
        read_market_quality_evidence(store, evidence.ref)
