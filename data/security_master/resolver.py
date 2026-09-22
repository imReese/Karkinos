"""Point-in-time resolution for Security Master lifecycle facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Iterable

from core.types import InstrumentKey
from data.security_master.model import (
    InstrumentLifecycleEvent,
    LifecycleCoverageEvidence,
    LifecycleEventType,
)


class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    NOT_YET_LISTED = "not_yet_listed"
    DELISTED = "delisted"


class SecurityMasterResolutionError(ValueError):
    """Lifecycle evidence cannot support a deterministic PIT answer."""


@dataclass(frozen=True, slots=True)
class ResolvedInstrumentLifecycle:
    instrument: InstrumentKey
    as_of_date: date
    cutoff: datetime
    status: LifecycleStatus
    listed_on: date
    delisted_on: date | None
    pit_grade: str
    evidence_refs: tuple[str, ...]

    @property
    def is_member(self) -> bool:
        return self.status is LifecycleStatus.ACTIVE


def resolve_instrument_lifecycle(
    *,
    instrument: InstrumentKey,
    as_of_date: date,
    cutoff: datetime,
    events: Iterable[InstrumentLifecycleEvent],
    coverage: LifecycleCoverageEvidence,
) -> ResolvedInstrumentLifecycle:
    """Resolve membership using only evidence available by the cutoff."""

    if not isinstance(instrument, InstrumentKey):
        raise TypeError("security_master_instrument_must_be_instrument_key")
    if isinstance(as_of_date, datetime) or not isinstance(as_of_date, date):
        raise TypeError("security_master_as_of_date_must_be_date")
    cutoff = _utc_instant(cutoff)
    if coverage.instrument != instrument:
        raise SecurityMasterResolutionError(
            "security_master_coverage_instrument_mismatch"
        )
    if coverage.available_at > cutoff:
        raise SecurityMasterResolutionError("security_master_coverage_after_cutoff")
    if coverage.covered_through < as_of_date:
        raise SecurityMasterResolutionError("security_master_coverage_incomplete")

    visible = tuple(
        event
        for event in events
        if event.instrument == instrument and event.available_at <= cutoff
    )
    listed_dates = {
        event.effective_on
        for event in visible
        if event.event_type is LifecycleEventType.LISTED
    }
    delisted_dates = {
        event.effective_on
        for event in visible
        if event.event_type is LifecycleEventType.DELISTED
    }

    if not listed_dates:
        raise SecurityMasterResolutionError("security_master_listing_evidence_missing")
    if len(listed_dates) != 1:
        raise SecurityMasterResolutionError("security_master_listing_evidence_conflict")
    if len(delisted_dates) > 1:
        raise SecurityMasterResolutionError(
            "security_master_delisting_evidence_conflict"
        )

    listed_on = next(iter(listed_dates))
    delisted_on = next(iter(delisted_dates), None)
    if delisted_on is not None and delisted_on < listed_on:
        raise SecurityMasterResolutionError(
            "security_master_lifecycle_chronology_invalid"
        )

    if as_of_date < listed_on:
        status = LifecycleStatus.NOT_YET_LISTED
    elif delisted_on is not None and as_of_date >= delisted_on:
        status = LifecycleStatus.DELISTED
    else:
        status = LifecycleStatus.ACTIVE

    relevant_events = tuple(
        event
        for event in visible
        if event.event_type is LifecycleEventType.LISTED
        or (delisted_on is not None and event.event_type is LifecycleEventType.DELISTED)
    )
    strict = coverage.strict_pit and all(event.strict_pit for event in relevant_events)
    refs = tuple(
        sorted(
            {
                coverage.availability_evidence_ref,
                *(event.availability_evidence_ref for event in relevant_events),
            }
        )
    )
    return ResolvedInstrumentLifecycle(
        instrument=instrument,
        as_of_date=as_of_date,
        cutoff=cutoff,
        status=status,
        listed_on=listed_on,
        delisted_on=delisted_on,
        pit_grade="strict" if strict else "capture_fallback",
        evidence_refs=refs,
    )


def _utc_instant(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("security_master_cutoff_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("security_master_cutoff_must_be_timezone_aware")
    return value.astimezone(timezone.utc)
