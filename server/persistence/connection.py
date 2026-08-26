"""Shared SQLite repository connection identity."""

from __future__ import annotations

from datetime import datetime, tzinfo
from pathlib import Path
from typing import Protocol


class DateTimeNow(Protocol):
    def __call__(self, tz: tzinfo | None = None) -> datetime: ...


def _system_now(tz: tzinfo | None = None) -> datetime:
    return datetime.now(tz)


class SQLiteRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        now: DateTimeNow | None = None,
    ) -> None:
        self._path = Path(database_path)
        self._now = now or _system_now

    @property
    def path(self) -> Path:
        """Expose the repository's immutable SQLite identity to composition code."""

        return self._path
