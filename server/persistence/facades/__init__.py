"""Capability-scoped compatibility facades for the legacy database API."""

from server.persistence.facades.artifacts import ArtifactDatabaseFacade
from server.persistence.facades.controlled_sessions import (
    ControlledSessionDatabaseFacade,
)
from server.persistence.facades.execution import ExecutionDatabaseFacade
from server.persistence.facades.financial_facts import FinancialFactDatabaseFacade
from server.persistence.facades.reference_data import ReferenceDataDatabaseFacade
from server.persistence.facades.research import ResearchDatabaseFacade
from server.persistence.facades.signal_automation import SignalAutomationDatabaseFacade
from server.persistence.facades.strategy_trading import StrategyTradingDatabaseFacade

__all__ = [
    "ArtifactDatabaseFacade",
    "ControlledSessionDatabaseFacade",
    "ExecutionDatabaseFacade",
    "FinancialFactDatabaseFacade",
    "ReferenceDataDatabaseFacade",
    "ResearchDatabaseFacade",
    "SignalAutomationDatabaseFacade",
    "StrategyTradingDatabaseFacade",
]
