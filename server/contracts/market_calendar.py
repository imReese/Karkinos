"""Typed commands for market-calendar verification and publication."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_VERIFICATION_STATUSES = frozenset({"unverified", "needs_review", "verified"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class MarketCalendarVerificationCommand:
    """Bind one verification decision to exact provider and official evidence."""

    exchange: str
    year: int
    source_fingerprint: str
    verification_status: str
    official_source_url: str | None = None
    official_source_fingerprint: str | None = None
    verified_by: str | None = None
    review_notes: str | None = None
    day_labels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        exchange = self.exchange.strip().upper()
        source_fingerprint = self.source_fingerprint.strip()
        status = self.verification_status.strip().lower()
        if not exchange:
            raise ValueError("market calendar exchange must not be empty")
        if self.year < 2000:
            raise ValueError("market calendar year is invalid")
        if not source_fingerprint:
            raise ValueError("market calendar source fingerprint must not be empty")
        if not _SHA256.fullmatch(source_fingerprint):
            raise ValueError("market calendar source fingerprint must be sha256")
        if status not in _VERIFICATION_STATUSES:
            raise ValueError("market calendar verification status is invalid")
        if status == "verified" and not all(
            (
                str(self.official_source_url or "").strip(),
                str(self.official_source_fingerprint or "").strip(),
                str(self.verified_by or "").strip(),
            )
        ):
            raise ValueError(
                "verified market calendar requires exact official source evidence"
            )
        official_fingerprint = str(self.official_source_fingerprint or "").strip()
        if official_fingerprint and not _SHA256.fullmatch(official_fingerprint):
            raise ValueError("official market calendar fingerprint must be sha256")
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "source_fingerprint", source_fingerprint)
        object.__setattr__(self, "verification_status", status)


@dataclass(frozen=True, slots=True)
class MarketCalendarAutomationPublication:
    """Publish an optional snapshot and its terminal automation audit atomically."""

    run: dict[str, Any]
    snapshot: dict[str, Any] | None = None
    verification: MarketCalendarVerificationCommand | None = None

    def __post_init__(self) -> None:
        if not str(self.run.get("run_id") or "").strip():
            raise ValueError("market calendar automation run_id must not be empty")
        if (self.snapshot is None) != (self.verification is None):
            raise ValueError(
                "market calendar snapshot and verification must be published together"
            )
        if self.snapshot is None:
            return
        assert self.verification is not None
        snapshot_fingerprint = str(
            self.snapshot.get("source_fingerprint") or ""
        ).strip()
        if snapshot_fingerprint != self.verification.source_fingerprint:
            raise ValueError(
                "market calendar publication fingerprint does not match snapshot"
            )


__all__ = [
    "MarketCalendarAutomationPublication",
    "MarketCalendarVerificationCommand",
]
