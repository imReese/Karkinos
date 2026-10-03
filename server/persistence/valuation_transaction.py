"""Typed transaction seam for publishing valuation identities with fact writes."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Protocol


class ValuationTransactionWriter(Protocol):
    def __call__(
        self,
        conn: sqlite3.Connection,
        *,
        candidate_ledger_rows: list[dict[str, Any]] | None = None,
        quote_fetch_run_id: str | None = None,
        valuation_policy: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...


__all__ = ["ValuationTransactionWriter"]
