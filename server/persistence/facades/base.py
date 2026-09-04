"""Repository capabilities required by database compatibility facades."""

from __future__ import annotations

from server.persistence.automation_alerts import AutomationAlertRepository
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.backtest_results import BacktestResultsRepository
from server.persistence.controlled_execution import ControlledExecutionRepository
from server.persistence.controlled_session import ControlledSessionRepository
from server.persistence.event_log import EventLogRepository
from server.persistence.execution_reconciliation import (
    ExecutionReconciliationRepository,
)
from server.persistence.financial_facts import FinancialFactsRepository
from server.persistence.instrument_metadata import InstrumentMetadataRepository
from server.persistence.market_calendar import MarketCalendarRepository
from server.persistence.market_calendar_publication_uow import (
    MarketCalendarPublicationUnitOfWork,
)
from server.persistence.oms import OmsRepository
from server.persistence.paper_trading import PaperTradingRepository
from server.persistence.pre_trade_risk_uow import PreTradeRiskUnitOfWork
from server.persistence.research_notes import ResearchNotesRepository
from server.persistence.runtime_controls import RuntimeControlRepository
from server.persistence.signal_journal import SignalJournalRepository
from server.persistence.strategy_promotion import StrategyPromotionRepository
from server.persistence.watchlist import WatchlistRepository


class DatabaseRepositoryAccess:
    """Typed repository wiring shared by capability-scoped facade mixins."""

    _automation_alerts: AutomationAlertRepository
    _automation_runs: AutomationRunRepository
    _backtest_results: BacktestResultsRepository
    _controlled_execution: ControlledExecutionRepository
    _controlled_session: ControlledSessionRepository
    _event_log: EventLogRepository
    _execution_reconciliation: ExecutionReconciliationRepository
    _financial_facts: FinancialFactsRepository
    _instrument_metadata: InstrumentMetadataRepository
    _market_calendar: MarketCalendarRepository
    _market_calendar_publication: MarketCalendarPublicationUnitOfWork
    _oms: OmsRepository
    _paper_trading: PaperTradingRepository
    _pre_trade_risk: PreTradeRiskUnitOfWork
    _research_notes: ResearchNotesRepository
    _runtime_controls: RuntimeControlRepository
    _signal_journal: SignalJournalRepository
    _strategy_promotion: StrategyPromotionRepository
    _watchlist: WatchlistRepository
