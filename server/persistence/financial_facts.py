"""Composed SQLite repository for canonical financial facts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from server.persistence.connection import DateTimeNow, SQLiteRepository
from server.persistence.financial_facts_ledger import LedgerFactsRepositoryMixin
from server.persistence.financial_facts_portfolio import PortfolioFactsRepositoryMixin
from server.persistence.financial_facts_quote_runs import QuoteFetchRunRepositoryMixin
from server.persistence.financial_facts_quotes import QuoteFactsRepositoryMixin
from server.persistence.financial_facts_valuation import ValuationFactsRepositoryMixin
from server.persistence.runtime_controls import RuntimeControlRepository


class FinancialFactsRepository(
    ValuationFactsRepositoryMixin,
    QuoteFetchRunRepositoryMixin,
    QuoteFactsRepositoryMixin,
    PortfolioFactsRepositoryMixin,
    LedgerFactsRepositoryMixin,
    SQLiteRepository,
):
    """Own the composed persistence surface for canonical financial facts."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        runtime_controls: RuntimeControlRepository,
        valuation_publisher: Callable[[], dict[str, Any]],
        now: DateTimeNow | None = None,
    ) -> None:
        super().__init__(database_path, now=now)
        self._runtime_controls = runtime_controls
        self._valuation_publisher = valuation_publisher


__all__ = ["FinancialFactsRepository"]
