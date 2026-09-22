"""Point-in-time Security Master lifecycle value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum

from core.types import InstrumentKey

SECURITY_MASTER_POLICY_ID = "karkinos.security_master.lifecycle.v1"


class LifecycleEventType(str, Enum):
    """Lifecycle changes whose effective date affects universe membership."""

    LISTED = "listed"
    DELISTED = "delisted"


class AvailabilityEvidenceKind(str, Enum):
    """How an information-availability timestamp is justified."""

    SOURCE_TIMESTAMP = "source_timestamp"
    CAPTURE_FALLBACK = "capture_fallback"


@dataclass(frozen=True, slots=True)
class InstrumentLifecycleEvent:
    """One bitemporal lifecycle fact for an instrument."""

    instrument: InstrumentKey
    event_type: LifecycleEventType
    effective_on: date
    exchange: str
    available_at: datetime
    captured_at: datetime
    provider: str
    source_revision: str
    availability_evidence_ref: str
    availability_evidence_kind: AvailabilityEvidenceKind

    def __post_init__(self) -> None:
        _require_instrument(self.instrument)
        if not isinstance(self.event_type, LifecycleEventType):
            raise TypeError("security_master_event_type_invalid")
        _require_date(self.effective_on, field="effective_on")
        exchange = _require_text(self.exchange, field="exchange").upper()
        provider = _require_text(self.provider, field="provider")
        source_revision = _require_text(self.source_revision, field="source_revision")
        evidence_ref = _require_text(
            self.availability_evidence_ref, field="availability_evidence_ref"
        )
        _require_evidence_kind(self.availability_evidence_kind)
        available_at = _utc_instant(self.available_at, field="available_at")
        captured_at = _utc_instant(self.captured_at, field="captured_at")
        _validate_availability(
            available_at=available_at,
            captured_at=captured_at,
            kind=self.availability_evidence_kind,
        )
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "availability_evidence_ref", evidence_ref)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "captured_at", captured_at)

    @property
    def strict_pit(self) -> bool:
        return (
            self.availability_evidence_kind is AvailabilityEvidenceKind.SOURCE_TIMESTAMP
        )


@dataclass(frozen=True, slots=True)
class LifecycleCoverageEvidence:
    """Evidence that lifecycle facts are complete through a business date."""

    instrument: InstrumentKey
    covered_through: date
    available_at: datetime
    captured_at: datetime
    provider: str
    source_revision: str
    availability_evidence_ref: str
    availability_evidence_kind: AvailabilityEvidenceKind

    def __post_init__(self) -> None:
        _require_instrument(self.instrument)
        _require_date(self.covered_through, field="covered_through")
        _require_evidence_kind(self.availability_evidence_kind)
        provider = _require_text(self.provider, field="provider")
        source_revision = _require_text(self.source_revision, field="source_revision")
        evidence_ref = _require_text(
            self.availability_evidence_ref, field="availability_evidence_ref"
        )
        available_at = _utc_instant(self.available_at, field="available_at")
        captured_at = _utc_instant(self.captured_at, field="captured_at")
        _validate_availability(
            available_at=available_at,
            captured_at=captured_at,
            kind=self.availability_evidence_kind,
        )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "availability_evidence_ref", evidence_ref)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "captured_at", captured_at)

    @property
    def strict_pit(self) -> bool:
        return (
            self.availability_evidence_kind is AvailabilityEvidenceKind.SOURCE_TIMESTAMP
        )


def _require_instrument(value: object) -> None:
    if not isinstance(value, InstrumentKey):
        raise TypeError("security_master_instrument_must_be_instrument_key")


def _require_date(value: object, *, field: str) -> None:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"security_master_{field}_must_be_date")


def _require_evidence_kind(value: object) -> None:
    if not isinstance(value, AvailabilityEvidenceKind):
        raise TypeError("security_master_availability_evidence_kind_invalid")


def _utc_instant(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"security_master_{field}_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"security_master_{field}_must_be_timezone_aware")
    return value.astimezone(timezone.utc)


def _validate_availability(
    *,
    available_at: datetime,
    captured_at: datetime,
    kind: AvailabilityEvidenceKind,
) -> None:
    if available_at > captured_at:
        raise ValueError("security_master_captured_before_available")
    if (
        kind is AvailabilityEvidenceKind.CAPTURE_FALLBACK
        and available_at != captured_at
    ):
        raise ValueError("security_master_capture_fallback_time_mismatch")


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"security_master_{field}_must_be_text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"security_master_{field}_missing")
    return normalized
