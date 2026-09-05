"""Durable job identity and attempt fencing, independent of task handlers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


def job_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("job clock must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class JobLease:
    job_id: str
    lease_owner: str
    attempt: int


@dataclass(frozen=True)
class JobRun:
    job_id: str
    kind: str
    input_fingerprint: str
    payload: dict[str, Any]
    status: str
    attempt: int
    lease_owner: str | None
    lease_expires_at: str | None
    heartbeat_at: str | None
    result_ref: str | None
    error: str | None

    @property
    def lease(self) -> JobLease:
        if self.status != "running" or not self.lease_owner:
            raise ValueError("job is not leased")
        return JobLease(self.job_id, self.lease_owner, self.attempt)


class JobStore(Protocol):
    def enqueue(
        self, kind: str, payload: dict[str, Any], *, now: datetime
    ) -> JobRun: ...
    def claim(
        self, kind: str, owner: str, *, now: datetime, lease_seconds: int = 60
    ) -> JobRun | None: ...
    def heartbeat(
        self, lease: JobLease, *, now: datetime, lease_seconds: int = 60
    ) -> None: ...
    def finish(self, lease: JobLease, *, now: datetime, result_ref: str) -> None: ...
    def fail(
        self, lease: JobLease, *, now: datetime, error: str, retry_seconds: int = 60
    ) -> None: ...
