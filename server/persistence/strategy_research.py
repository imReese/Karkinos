"""Compatibility repository façade for AI strategy research audit evidence."""

from __future__ import annotations

from pathlib import Path

from server.persistence.strategy_research_backtests import (
    StrategyResearchBacktestRepositoryMixin,
)
from server.persistence.strategy_research_critiques import (
    StrategyResearchCritiqueRepositoryMixin,
)
from server.persistence.strategy_research_events import (
    StrategyResearchEventRepositoryMixin,
)
from server.persistence.strategy_research_schema import StrategyResearchSchemaMixin
from server.persistence.strategy_research_sessions import (
    StrategyResearchSessionRepositoryMixin,
)
from server.persistence.strategy_research_uow import StrategyResearchUnitOfWorkMixin


class StrategyResearchAuditStore(
    StrategyResearchSchemaMixin,
    StrategyResearchSessionRepositoryMixin,
    StrategyResearchBacktestRepositoryMixin,
    StrategyResearchCritiqueRepositoryMixin,
    StrategyResearchEventRepositoryMixin,
    StrategyResearchUnitOfWorkMixin,
):
    """Additive research-only storage with terminal replay and hash events."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
