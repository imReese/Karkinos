"""Clock-bound admission for provider-free account qualification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from server.services.ai_shadow_research_qualification_support import (
    qualification_clock_time,
    qualification_market_open_blackout,
)
from server.services.market_hours import get_shanghai_now


class QualificationAdmissionDeferred(Exception):
    """Signal that a previously admitted run reached the blackout boundary."""


@dataclass(frozen=True)
class QualificationAdmission:
    """Bound one run to the next Shanghai market-open blackout."""

    clock: Callable[[], datetime | str]
    deadline: datetime

    @classmethod
    def admit(cls, clock: Callable[[], datetime | str]) -> QualificationAdmission:
        current = get_shanghai_now(qualification_clock_time(clock))
        if qualification_market_open_blackout(current):
            raise QualificationAdmissionDeferred
        deadline = current.replace(hour=9, minute=0, second=0, microsecond=0)
        if current >= deadline:
            deadline += timedelta(days=1)
        return cls(clock=clock, deadline=deadline)

    def require_open(self) -> datetime:
        current = get_shanghai_now(qualification_clock_time(self.clock))
        if current >= self.deadline or qualification_market_open_blackout(current):
            raise QualificationAdmissionDeferred
        return current

    def timestamp(self) -> str:
        return self.require_open().isoformat()


__all__ = ["QualificationAdmission", "QualificationAdmissionDeferred"]
