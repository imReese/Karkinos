"""Aggregate controlled-execution repository compatibility boundary."""

from __future__ import annotations

from pathlib import Path

from server.persistence.connection import DateTimeNow
from server.persistence.controlled_broker_intents import (
    ControlledBrokerIntentRepositoryMixin,
)
from server.persistence.controlled_clearance_uow import (
    ControlledClearanceUnitOfWorkMixin,
)
from server.persistence.controlled_execution_access import ValuationFacts
from server.persistence.controlled_ledger_correction_uow import (
    ControlledLedgerCorrectionUnitOfWorkMixin,
)
from server.persistence.controlled_ledger_posting_uow import (
    ControlledLedgerPostingUnitOfWorkMixin,
)
from server.persistence.controlled_ledger_queries import (
    ControlledLedgerQueryRepositoryMixin,
)


class ControlledExecutionRepository(
    ControlledBrokerIntentRepositoryMixin,
    ControlledLedgerQueryRepositoryMixin,
    ControlledLedgerCorrectionUnitOfWorkMixin,
    ControlledLedgerPostingUnitOfWorkMixin,
    ControlledClearanceUnitOfWorkMixin,
):
    """Compose transactionally cohesive controlled-execution capabilities."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        valuation_facts: ValuationFacts,
        now: DateTimeNow | None = None,
    ) -> None:
        super().__init__(database_path, now=now)
        self._valuation_facts = valuation_facts
