"""Trading scheduler domain package.

Consolidates lifecycle management, quote ingestion runs, post-close reconciliation,
and runtime execution loop into a cohesive subsystem.
"""

from __future__ import annotations

from datetime import datetime

from data.live import LiveDataFeed
from server.bootstrap import build_strategy, create_runtime_context
from server.scheduler.contracts import (
    SchedulerConfig,
    SchedulerDatabase,
    SchedulerDataManager,
    SchedulerEventBus,
    SchedulerFeed,
    SchedulerLoopState,
    SchedulerNotifier,
    SchedulerPortfolioRebuild,
    SchedulerRuntimeContext,
    SchedulerSignalDatabase,
    SchedulerStrategy,
    SchedulerStrategyPublisher,
)
from server.scheduler.lifecycle import SchedulerLifecycleMixin
from server.scheduler.loop import (
    BufferedStrategyEventPublisher,
    DiscardingEventPublisher,
    SchedulerLoop,
    SchedulerLoopDependencies,
    SchedulerRuntime,
    StagedSchedulerQuote,
    run_scheduler_loop,
)
from server.scheduler.post_close import SchedulerPostCloseMixin
from server.scheduler.quote_restore import (
    INSTRUMENT_ASSET_CLASS_MAP,
    runtime_quote_from_persisted,
    runtime_quotes_from_persisted,
)
from server.scheduler.quote_runs import SchedulerQuoteRunMixin
from server.scheduler.service import TradingScheduler, scheduler_now
from server.scheduler.signals import handle_scheduler_signal
from server.scheduler.values import (
    SchedulerQuoteEvidence,
    configured_symbol_set,
    is_complete_quote_batch,
    optional_float,
    provider_status_for_quote_run,
    quote_fetch_asset_type,
    quote_fetch_metadata,
    quote_fetch_started_metadata,
    quote_fetch_status,
    scheduler_quote_evidence,
    scheduler_quote_provider_names,
)
from server.services.portfolio.ledger import rebuild_portfolio_from_ledger

_SCHEDULER_STOP_TIMEOUT_SECONDS = 10.0

__all__ = [
    "BufferedStrategyEventPublisher",
    "DiscardingEventPublisher",
    "INSTRUMENT_ASSET_CLASS_MAP",
    "LiveDataFeed",
    "SchedulerConfig",
    "SchedulerDataManager",
    "SchedulerDatabase",
    "SchedulerEventBus",
    "SchedulerFeed",
    "SchedulerLifecycleMixin",
    "SchedulerLoop",
    "SchedulerLoopDependencies",
    "SchedulerLoopState",
    "SchedulerNotifier",
    "SchedulerPortfolioRebuild",
    "SchedulerPostCloseMixin",
    "SchedulerQuoteEvidence",
    "SchedulerQuoteRunMixin",
    "SchedulerRuntime",
    "SchedulerRuntimeContext",
    "SchedulerSignalDatabase",
    "SchedulerStrategy",
    "SchedulerStrategyPublisher",
    "StagedSchedulerQuote",
    "TradingScheduler",
    "build_strategy",
    "configured_symbol_set",
    "create_runtime_context",
    "handle_scheduler_signal",
    "is_complete_quote_batch",
    "optional_float",
    "provider_status_for_quote_run",
    "quote_fetch_asset_type",
    "quote_fetch_metadata",
    "quote_fetch_started_metadata",
    "quote_fetch_status",
    "rebuild_portfolio_from_ledger",
    "run_scheduler_loop",
    "runtime_quote_from_persisted",
    "runtime_quotes_from_persisted",
    "scheduler_now",
    "scheduler_quote_evidence",
    "scheduler_quote_provider_names",
]
