"""Structural ports shared by scheduler composition and runtime modules."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Protocol

from core.events import Event, MarketEvent
from core.types import AssetClass, Symbol
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from server.contracts.quote_ingestion import QuoteIngestionCommand


class SchedulerConfig(Protocol):
    @property
    def data_source(self) -> str: ...

    @property
    def live_poll_interval(self) -> int: ...

    @property
    def initial_cash(self) -> Decimal: ...


class SchedulerEventBus(Protocol):
    def publish(self, event: Event) -> None: ...

    def subscribe(
        self,
        event_type: type[Event],
        handler: Callable[[Any], None],
        priority: int = 0,
    ) -> None: ...

    def drain(self) -> int: ...


class SchedulerStrategyPublisher(Protocol):
    def publish(self, event: Event) -> None: ...


class SchedulerDataManager(Protocol):
    def get_instrument(
        self,
        symbol: Symbol,
        asset_class: AssetClass,
    ) -> Instrument: ...


class SchedulerRuntimeContext(Protocol):
    @property
    def sources(self) -> dict[str, object]: ...

    @property
    def data_manager(self) -> SchedulerDataManager: ...

    @property
    def watchlist(self) -> list[tuple[Symbol, AssetClass]]: ...

    @property
    def instruments(self) -> dict[Symbol, Instrument]: ...


class SchedulerFeed(Protocol):
    def poll_all(
        self,
        watchlist: list[tuple[Symbol, AssetClass]],
    ) -> list[MarketEvent]: ...

    def get_last_snapshot(
        self,
        symbol: Symbol,
        asset_class: AssetClass,
    ) -> dict[str, Any] | None: ...

    def close(self) -> None: ...


class SchedulerStrategy(Protocol):
    def on_init(self, symbols: list[Symbol]) -> None: ...

    def on_data(self, event: MarketEvent) -> None: ...


class SchedulerPortfolioRebuild(Protocol):
    portfolio: Portfolio
    instruments: dict[Symbol, Instrument]


class SchedulerDatabase(Protocol):
    def list_watchlist_assets_sync(self) -> list[dict[str, Any]]: ...

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]: ...

    def create_quote_fetch_run(
        self,
        *,
        run_id: str,
        started_at: str,
        trigger: str,
        status: str,
        provider: str | None = None,
        asset_type: str | None = None,
        symbol_count: int = 0,
        metadata: dict[str, Any] | str | None = None,
    ) -> int: ...

    def finish_quote_fetch_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int = 0,
        failure_count: int = 0,
        cache_hit_count: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None: ...

    def persist_quote_ingestion_sync(
        self,
        command: QuoteIngestionCommand,
    ) -> dict[str, Any]: ...

    def publish_current_valuation_snapshot_sync(
        self,
        *,
        valuation_policy: str | None = None,
    ) -> dict[str, Any]: ...

    def upsert_instrument_metadata_sync(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...

    def save_signal_sync(self, **kwargs: Any) -> int: ...

    def upsert_action_task_sync(self, **kwargs: Any) -> Any: ...


class SchedulerSignalDatabase(Protocol):
    def save_signal_sync(self, **kwargs: Any) -> int: ...

    def upsert_action_task_sync(self, **kwargs: Any) -> Any: ...


class SchedulerNotifier(Protocol):
    def send(self, *, title: str, message: str) -> Any: ...


class SchedulerLoopState(Protocol):
    @property
    def portfolio(self) -> Portfolio | None: ...

    @property
    def watchlist(self) -> list[tuple[Symbol, AssetClass]]: ...

    @property
    def instruments(self) -> dict[Symbol, Instrument]: ...

    @property
    def latest_quotes(self) -> dict[str, dict[str, Any]]: ...

    def scheduler_should_continue(self) -> bool: ...

    def scheduler_activation_guarded(self) -> bool: ...

    def mark_scheduler_initialized(self) -> None: ...

    def mark_scheduler_uninitialized(self) -> None: ...

    def mark_scheduler_iteration_completed(self) -> None: ...

    def wait_for_scheduler_stop(self, timeout: float) -> bool: ...

    def runtime_event_bus(self) -> SchedulerEventBus: ...

    def install_runtime_event_bus(self, event_bus: SchedulerEventBus) -> None: ...

    def replace_runtime_assets(
        self,
        watchlist: list[tuple[Symbol, AssetClass]],
        instruments: dict[Symbol, Instrument],
    ) -> None: ...

    def replace_runtime_quotes(self, quotes: dict[str, dict[str, Any]]) -> None: ...

    def publish_runtime_quote(
        self,
        symbol: str,
        quote: dict[str, Any],
    ) -> None: ...

    def install_runtime_portfolio(self, portfolio: Portfolio) -> None: ...
