"""SQLite 持久化 — 信号历史、回测结果、组合快照。"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from server.persistence.automation_alerts import AutomationAlertRepository
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.backtest_results import BacktestResultsRepository
from server.persistence.controlled_execution import ControlledExecutionRepository
from server.persistence.controlled_session import ControlledSessionRepository
from server.persistence.event_log import (
    EventLogRepository,
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)
from server.persistence.execution_reconciliation import (
    ExecutionReconciliationRepository,
)
from server.persistence.facades import (
    ArtifactDatabaseFacade,
    ControlledSessionDatabaseFacade,
    ExecutionDatabaseFacade,
    FinancialFactDatabaseFacade,
    ReferenceDataDatabaseFacade,
    ResearchDatabaseFacade,
    SignalAutomationDatabaseFacade,
    StrategyTradingDatabaseFacade,
)
from server.persistence.financial_facts import FinancialFactsRepository
from server.persistence.initializer import initialize_database
from server.persistence.instrument_metadata import InstrumentMetadataRepository
from server.persistence.market_calendar import MarketCalendarRepository
from server.persistence.oms import OmsRepository
from server.persistence.paper_trading import PaperTradingRepository
from server.persistence.research_notes import ResearchNotesRepository
from server.persistence.runtime_controls import RuntimeControlRepository
from server.persistence.schema_v1 import (
    initialize_v1_baseline_schema as _initialize_v1_baseline_schema,
)
from server.persistence.signal_journal import SignalJournalRepository
from server.persistence.strategy_promotion import StrategyPromotionRepository
from server.persistence.watchlist import WatchlistRepository
from server.runtime_paths import resolve_data_dir

logger = logging.getLogger(__name__)

_DB_DIR = Path("data/store")
_DB_PATH = _DB_DIR / "app.db"


class AppDatabase(
    ReferenceDataDatabaseFacade,
    SignalAutomationDatabaseFacade,
    ExecutionDatabaseFacade,
    StrategyTradingDatabaseFacade,
    ArtifactDatabaseFacade,
    ControlledSessionDatabaseFacade,
    FinancialFactDatabaseFacade,
    ResearchDatabaseFacade,
):
    """应用数据库。

    后台线程用同步 sqlite3 写入，API 层用 aiosqlite 读取。
    WAL 模式支持并发读写。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = (
            Path(db_path)
            if db_path is not None
            else Path(resolve_data_dir()) / _DB_PATH.name
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._automation_alerts = AutomationAlertRepository(
            self._path,
            utc_now=lambda: datetime.now(timezone.utc).isoformat(),
            local_now=lambda: datetime.now().isoformat(),
        )
        self._backtest_results = BacktestResultsRepository(self._path)
        self._event_log = EventLogRepository(self._path)
        self._instrument_metadata = InstrumentMetadataRepository(self._path)
        self._market_calendar = MarketCalendarRepository(self._path)
        self._research_notes = ResearchNotesRepository(self._path)
        self._watchlist = WatchlistRepository(self._path)
        self._runtime_controls = RuntimeControlRepository(self._path)
        self._signal_journal = SignalJournalRepository(
            self._path, now=lambda tz=None: datetime.now(tz)
        )
        self._automation_runs = AutomationRunRepository(
            self._path, now=lambda tz=None: datetime.now(tz)
        )
        self._oms = OmsRepository(self._path, now=lambda tz=None: datetime.now(tz))
        self._execution_reconciliation = ExecutionReconciliationRepository(
            self._path, now=lambda tz=None: datetime.now(tz)
        )
        self._strategy_promotion = StrategyPromotionRepository(
            self._path, now=lambda tz=None: datetime.now(tz)
        )
        self._paper_trading = PaperTradingRepository(
            self._path, now=lambda tz=None: datetime.now(tz)
        )
        self._financial_facts = FinancialFactsRepository(
            self._path,
            runtime_controls=self._runtime_controls,
            valuation_publisher=lambda: self.publish_current_valuation_snapshot_sync(),
            now=lambda tz=None: datetime.now(tz),
        )
        self._controlled_execution = ControlledExecutionRepository(
            self._path,
            valuation_facts=self._financial_facts,
            now=lambda tz=None: datetime.now(tz),
        )
        self._controlled_session = ControlledSessionRepository(
            self._path, now=lambda tz=None: datetime.now(tz)
        )

    @property
    def path(self) -> Path:
        """Public database identity for repositories sharing this SQLite store."""
        return self._path

    async def init(self) -> None:
        """初始化数据库表。"""
        self.init_sync()
        logger.info("Database initialized: %s", self._path)

    def init_sync(self) -> None:
        """同步初始化数据库表。"""
        initialize_database(self._path)
        logger.info("Database initialized: %s", self._path)
