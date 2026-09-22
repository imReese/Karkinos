from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from core.types import InstrumentKey, InstrumentType
from data.security_master import (
    AvailabilityEvidenceKind,
    InstrumentLifecycleEvent,
    LifecycleCoverageEvidence,
    LifecycleEventType,
    LifecycleStatus,
    SecurityMasterResolutionError,
    resolve_instrument_lifecycle,
)

INSTRUMENT = InstrumentKey("600519", InstrumentType.STOCK)
TZ8 = timezone(timedelta(hours=8))


def _event(
    event_type: LifecycleEventType,
    effective_on: date,
    *,
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
    revision: str = "r1",
    evidence_ref: str = "fixture:event",
    kind: AvailabilityEvidenceKind = AvailabilityEvidenceKind.SOURCE_TIMESTAMP,
) -> InstrumentLifecycleEvent:
    available_at = available_at or datetime(2026, 9, 1, 9, tzinfo=TZ8)
    captured_at = captured_at or datetime(2026, 9, 1, 10, tzinfo=TZ8)
    return InstrumentLifecycleEvent(
        instrument=INSTRUMENT,
        event_type=event_type,
        effective_on=effective_on,
        exchange="sh",
        available_at=available_at,
        captured_at=captured_at,
        provider="fixture",
        source_revision=revision,
        availability_evidence_ref=evidence_ref,
        availability_evidence_kind=kind,
    )


def _coverage(
    *,
    covered_through: date = date(2026, 9, 30),
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
    kind: AvailabilityEvidenceKind = AvailabilityEvidenceKind.SOURCE_TIMESTAMP,
) -> LifecycleCoverageEvidence:
    available_at = available_at or datetime(2026, 9, 1, 9, tzinfo=TZ8)
    captured_at = captured_at or datetime(2026, 9, 1, 10, tzinfo=TZ8)
    return LifecycleCoverageEvidence(
        instrument=INSTRUMENT,
        covered_through=covered_through,
        available_at=available_at,
        captured_at=captured_at,
        provider="fixture",
        source_revision="coverage-r1",
        availability_evidence_ref="fixture:coverage",
        availability_evidence_kind=kind,
    )


def _resolve(
    *events: InstrumentLifecycleEvent,
    as_of_date: date = date(2026, 9, 20),
    cutoff: datetime = datetime(2026, 9, 20, 16, tzinfo=TZ8),
    coverage: LifecycleCoverageEvidence | None = None,
):
    return resolve_instrument_lifecycle(
        instrument=INSTRUMENT,
        as_of_date=as_of_date,
        cutoff=cutoff,
        events=events,
        coverage=coverage or _coverage(),
    )


def test_lifecycle_values_canonicalize_time_and_exchange() -> None:
    event = _event(LifecycleEventType.LISTED, date(2001, 8, 27))
    assert event.exchange == "SH"
    assert event.available_at.tzinfo is timezone.utc
    assert event.captured_at.tzinfo is timezone.utc
    assert event.strict_pit is True


def test_capture_fallback_requires_capture_time() -> None:
    with pytest.raises(ValueError, match="capture_fallback_time_mismatch"):
        _event(
            LifecycleEventType.LISTED,
            date(2001, 8, 27),
            kind=AvailabilityEvidenceKind.CAPTURE_FALLBACK,
        )


def test_resolve_active_membership_from_complete_pit_evidence() -> None:
    result = _resolve(_event(LifecycleEventType.LISTED, date(2001, 8, 27)))
    assert result.status is LifecycleStatus.ACTIVE
    assert result.is_member is True
    assert result.listed_on == date(2001, 8, 27)
    assert result.delisted_on is None
    assert result.pit_grade == "strict"
    assert result.evidence_refs == ("fixture:coverage", "fixture:event")


def test_resolve_not_yet_listed_and_delisted() -> None:
    listed = _event(LifecycleEventType.LISTED, date(2026, 9, 10))
    before = _resolve(listed, as_of_date=date(2026, 9, 9))
    assert before.status is LifecycleStatus.NOT_YET_LISTED
    delisted = _event(
        LifecycleEventType.DELISTED,
        date(2026, 9, 18),
        evidence_ref="fixture:delisted",
    )
    after = _resolve(listed, delisted, as_of_date=date(2026, 9, 20))
    assert after.status is LifecycleStatus.DELISTED
    assert after.is_member is False
    assert after.delisted_on == date(2026, 9, 18)


def test_resolution_requires_coverage_available_by_cutoff() -> None:
    late = _coverage(
        available_at=datetime(2026, 9, 21, 9, tzinfo=TZ8),
        captured_at=datetime(2026, 9, 21, 10, tzinfo=TZ8),
    )
    with pytest.raises(SecurityMasterResolutionError, match="coverage_after_cutoff"):
        _resolve(
            _event(LifecycleEventType.LISTED, date(2001, 8, 27)),
            coverage=late,
        )


def test_resolution_requires_coverage_through_business_date() -> None:
    with pytest.raises(SecurityMasterResolutionError, match="coverage_incomplete"):
        _resolve(
            _event(LifecycleEventType.LISTED, date(2001, 8, 27)),
            coverage=_coverage(covered_through=date(2026, 9, 19)),
        )


def test_conflicting_listing_evidence_fails_closed() -> None:
    with pytest.raises(
        SecurityMasterResolutionError, match="listing_evidence_conflict"
    ):
        _resolve(
            _event(LifecycleEventType.LISTED, date(2001, 8, 27)),
            _event(
                LifecycleEventType.LISTED,
                date(2001, 8, 28),
                revision="r2",
                evidence_ref="fixture:other",
            ),
        )


def test_late_event_is_invisible_to_earlier_cutoff() -> None:
    listed = _event(LifecycleEventType.LISTED, date(2001, 8, 27))
    late_delisting = _event(
        LifecycleEventType.DELISTED,
        date(2026, 9, 18),
        available_at=datetime(2026, 9, 21, 9, tzinfo=TZ8),
        captured_at=datetime(2026, 9, 21, 10, tzinfo=TZ8),
    )
    result = _resolve(listed, late_delisting)
    assert result.status is LifecycleStatus.ACTIVE


def test_capture_fallback_downgrades_pit_grade() -> None:
    captured = datetime(2026, 9, 1, 10, tzinfo=TZ8)
    listed = _event(
        LifecycleEventType.LISTED,
        date(2001, 8, 27),
        available_at=captured,
        captured_at=captured,
        kind=AvailabilityEvidenceKind.CAPTURE_FALLBACK,
    )
    result = _resolve(listed)
    assert result.pit_grade == "capture_fallback"
