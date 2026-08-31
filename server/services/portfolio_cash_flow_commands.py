"""Typed application commands for ledger-owned portfolio cash flows."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from server.contracts.portfolio_cash_flows import (
    CashFlowCorrectionResult,
    CashFlowCorrectionWrite,
    CashFlowWrite,
    CashFlowWriteResult,
)
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

logger = logging.getLogger(__name__)


class PortfolioCashFlowDatabase(Protocol):
    def record_cash_flow_sync(self, command: CashFlowWrite) -> CashFlowWriteResult: ...

    def correct_cash_flow_sync(
        self, command: CashFlowCorrectionWrite
    ) -> CashFlowCorrectionResult: ...


class RuntimePortfolioInstaller(Protocol):
    @property
    def is_running(self) -> bool: ...

    @property
    def latest_quotes(self) -> dict[str, dict[str, Any]]: ...

    def install_runtime_portfolio(self, portfolio: Any) -> None: ...


class PortfolioCashFlowState(Protocol):
    config: Any
    db: PortfolioCashFlowDatabase
    scheduler: RuntimePortfolioInstaller | None


class PortfolioCashFlowCommandService:
    """Delegate every mutation to the atomic cash-flow UoW."""

    def __init__(self, state: PortfolioCashFlowState) -> None:
        if state.db is None:
            raise RuntimeError("application database is not initialized")
        if state.config is None:
            raise RuntimeError("runtime configuration is not initialized")
        self._state = state
        self._db = state.db

    def record(self, command: CashFlowWrite) -> CashFlowWriteResult:
        result = self._db.record_cash_flow_sync(command)
        self._refresh_runtime_projection()
        return result

    def correct(self, command: CashFlowCorrectionWrite) -> CashFlowCorrectionResult:
        result = self._db.correct_cash_flow_sync(command)
        self._refresh_runtime_projection()
        return result

    def _refresh_runtime_projection(self) -> None:
        scheduler = self._state.scheduler
        if scheduler is None or not scheduler.is_running:
            return
        try:
            rebuilt = rebuild_portfolio_from_ledger(
                self._state.config,
                self._db,
                scheduler.latest_quotes,
            )
            scheduler.install_runtime_portfolio(rebuilt.portfolio)
        except Exception:
            logger.exception(
                "Canonical cash flow committed but runtime projection refresh failed"
            )


__all__ = ["PortfolioCashFlowCommandService"]
