"""Typed state shared by controlled-execution repository capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from server.persistence.connection import SQLiteRepository


class ValuationFacts(Protocol):
    """Persisted-fact reads required to revalidate a correction in-transaction."""

    def list_quote_selection_candidates_sync(self) -> list[dict[str, Any]]: ...

    def get_market_bar_on_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_latest_market_bar_before_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_latest_daily_close_before_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_latest_quote_before_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_ledger_entries_sync(
        self, *, limit: int = 500, offset: int = 0
    ) -> list[dict[str, Any]]: ...


class ControlledExecutionRepositoryAccess(SQLiteRepository):
    """Repository path, clock, and read-only valuation facts."""

    _valuation_facts: ValuationFacts
