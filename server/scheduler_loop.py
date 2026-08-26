"""Runtime orchestration for the background trading scheduler."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from typing import Any, Callable

from core.events import MarketEvent, SignalEvent
from core.types import AssetClass, Symbol
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.scheduler_contracts import (
    SchedulerConfig,
    SchedulerDatabase,
    SchedulerDataManager,
    SchedulerEventBus,
    SchedulerFeed,
    SchedulerLoopState,
    SchedulerPortfolioRebuild,
    SchedulerRuntimeContext,
    SchedulerStrategy,
    SchedulerStrategyPublisher,
)
from server.scheduler_values import (
    SchedulerQuoteEvidence,
    is_complete_quote_batch,
    optional_float,
    quote_fetch_metadata,
    scheduler_quote_evidence,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerLoopDependencies:
    """Late-bound factories used by the scheduler runtime.

    The scheduler module builds this value for each run so tests and composition
    roots can replace factories without the runtime module owning global seams.
    """

    event_bus_factory: Callable[[], SchedulerEventBus]
    runtime_context_factory: Callable[[SchedulerConfig], SchedulerRuntimeContext]
    live_data_feed_factory: Callable[..., SchedulerFeed]
    portfolio_rebuilder: Callable[..., SchedulerPortfolioRebuild | None]
    strategy_factory: Callable[
        [SchedulerConfig, SchedulerStrategyPublisher], SchedulerStrategy
    ]
    now: Callable[[], datetime]
    afternoon_close: time
    config: SchedulerConfig
    database: SchedulerDatabase | None
    bridge_rebinder: Callable[[SchedulerEventBus], None]
    warmup_strategy: Callable[[SchedulerDataManager, SchedulerStrategy], None]
    signal_handler: Callable[[SignalEvent], None]
    evaluate_controlled_session_pauses: Callable[[], Any]
    retry_pending_valuation_publication: Callable[[], bool]
    is_market_open: Callable[[], bool]
    is_post_close_refresh_window: Callable[[datetime], bool]
    refresh_post_close_valuation_data: Callable[..., bool]
    backfill_historical_bars: Callable[..., None]
    sync_fund_nav_quotes: Callable[[], None]
    sync_market_index_quotes: Callable[[object, object | None], None]
    poll_watchlist_quotes: Callable[[SchedulerFeed], tuple[list[MarketEvent], str]]
    finish_persisted_quote_fetch_run: Callable[
        [str, list[MarketEvent], list[str]], bool
    ]
    finish_quote_fetch_run: Callable[..., bool]


@dataclass(frozen=True)
class SchedulerRuntime:
    source: object
    fallback_source: object | None
    feed: SchedulerFeed
    data_manager: SchedulerDataManager
    strategy: SchedulerStrategy
    strategy_events: "BufferedStrategyEventPublisher"


@dataclass(frozen=True)
class StagedSchedulerQuote:
    symbol: str
    runtime_quote: dict[str, Any]
    strategy_eligible: bool


class DiscardingEventPublisher:
    """Prevent provider responses from entering the domain bus before persistence."""

    def publish(self, _event: object) -> None:
        return None


class BufferedStrategyEventPublisher:
    """Stage signal evidence until its complete market-input batch is durable."""

    def __init__(self) -> None:
        self._events: list[SignalEvent] = []

    def publish(self, event: object) -> None:
        if not isinstance(event, SignalEvent):
            raise TypeError("scheduler strategies may publish only SignalEvent")
        self._events.append(event)

    def discard(self) -> None:
        self._events.clear()

    def flush_into(self, event_bus: SchedulerEventBus) -> None:
        pending = list(self._events)
        self._events.clear()
        for event in pending:
            event_bus.publish(event)


class SchedulerLoop:
    """Initialize and advance one scheduler's background runtime."""

    def __init__(
        self,
        state: SchedulerLoopState,
        dependencies: SchedulerLoopDependencies,
    ) -> None:
        self._state = state
        self._dependencies = dependencies

    def run(self) -> None:
        runtime = self._initialize_runtime()
        if runtime is None:
            return

        try:
            logger.info(
                "Trading loop started, watching %d symbols, interval=%ds",
                len(self._state.watchlist),
                self._dependencies.config.live_poll_interval,
            )
            while self._state.scheduler_should_continue():
                if not self._run_iteration(runtime):
                    continue
                self._state.wait_for_scheduler_stop(
                    timeout=self._dependencies.config.live_poll_interval
                )
        finally:
            runtime.feed.close()

    def _initialize_runtime(self) -> SchedulerRuntime | None:
        state = self._state
        dependencies = self._dependencies
        state.install_runtime_event_bus(dependencies.event_bus_factory())
        runtime = dependencies.runtime_context_factory(dependencies.config)
        source = runtime.sources.get(dependencies.config.data_source)
        if source is None:
            raise RuntimeError(
                "configured scheduler data source is unavailable: "
                f"{dependencies.config.data_source}"
            )
        fallback_source = None
        if dependencies.config.data_source != "akshare":
            fallback_source = runtime.sources.get("akshare")
        feed = dependencies.live_data_feed_factory(
            source,
            DiscardingEventPublisher(),
            fallback_source=fallback_source,
            prefer_fallback_asset_classes=(
                {AssetClass.FUND} if fallback_source is not None else None
            ),
        )
        try:
            self._restore_watchlist(runtime, runtime.data_manager)
            self._restore_quotes()
            self._restore_portfolio()
            if not state.watchlist:
                logger.warning("No watchlist configured, stopping scheduler")
                state.request_scheduler_stop()
                feed.close()
                return None
            strategy, strategy_events = self._wire_event_processing(
                runtime.data_manager
            )
        except Exception:
            feed.close()
            raise
        return SchedulerRuntime(
            source=source,
            fallback_source=fallback_source,
            feed=feed,
            data_manager=runtime.data_manager,
            strategy=strategy,
            strategy_events=strategy_events,
        )

    def _restore_watchlist(
        self,
        runtime: SchedulerRuntimeContext,
        data_manager: SchedulerDataManager,
    ) -> None:
        state = self._state
        database = self._dependencies.database
        persisted_watchlist: list[dict[str, Any]] = []
        if database is not None:
            read_watchlist = getattr(database, "list_watchlist_assets_sync", None)
            if not callable(read_watchlist):
                raise RuntimeError(
                    "scheduler database cannot restore the persisted watchlist"
                )
            try:
                persisted_watchlist = read_watchlist()
            except Exception as exc:
                raise RuntimeError(
                    "persisted scheduler watchlist could not be restored"
                ) from exc

        if not persisted_watchlist:
            state.replace_runtime_assets(
                list(runtime.watchlist),
                dict(runtime.instruments),
            )
            state.replace_runtime_quotes({})
            return

        restored_watchlist: list[tuple[Symbol, AssetClass]] = []
        restored_instruments: dict[Symbol, Instrument] = {}
        watched_symbols: set[Symbol] = set()
        supported_asset_classes = {
            "stock": AssetClass.STOCK,
            "fund": AssetClass.FUND,
            "etf": AssetClass.FUND,
            "gold": AssetClass.GOLD,
            "bond": AssetClass.BOND,
        }
        for asset in persisted_watchlist:
            symbol = Symbol(str(asset.get("symbol") or "").strip())
            if not str(symbol):
                raise RuntimeError("persisted scheduler watchlist contains no symbol")
            raw_asset_class = str(asset.get("asset_class") or "").strip().lower()
            asset_class = supported_asset_classes.get(raw_asset_class)
            if asset_class is None:
                raise RuntimeError(
                    "persisted scheduler watchlist contains unsupported asset class: "
                    f"{raw_asset_class or '<empty>'}"
                )
            if symbol in watched_symbols:
                continue
            restored_watchlist.append((symbol, asset_class))
            restored_instruments[symbol] = data_manager.get_instrument(
                symbol,
                asset_class,
            )
            watched_symbols.add(symbol)

        state.replace_runtime_assets(restored_watchlist, restored_instruments)
        state.replace_runtime_quotes({})

    def _restore_quotes(self) -> None:
        database = self._dependencies.database
        if database is None:
            return
        try:
            persisted_quotes = database.get_latest_quotes_sync()
            restored_quotes = {
                quote["symbol"]: self._restored_quote(quote)
                for quote in persisted_quotes
            }
            self._state.replace_runtime_quotes(restored_quotes)
        except Exception:
            logger.warning("恢复实时行情快照失败，将忽略", exc_info=True)

    @staticmethod
    def _restored_quote(quote: dict[str, Any]) -> dict[str, Any]:
        quote_source = (
            quote.get("quote_source")
            or quote.get("source")
            or quote.get("provider_name")
            or quote.get("provider")
        )
        return {
            "price": float(quote["price"]),
            "volume": (float(quote["volume"]) if quote["volume"] is not None else None),
            "timestamp": quote["timestamp"],
            "asset_class": quote["asset_class"],
            "quote_source": quote_source,
            "provider_name": quote.get("provider_name"),
            "quote_status": quote.get("quote_status"),
            "stale_reason": quote.get("stale_reason"),
            "provider_status": quote.get("provider_status"),
            "captured_reason": quote.get("captured_reason"),
            "nav_date": quote.get("nav_date"),
        }

    def _restore_portfolio(self) -> None:
        dependencies = self._dependencies
        state = self._state
        rebuilt = (
            dependencies.portfolio_rebuilder(
                dependencies.config,
                dependencies.database,
                latest_quotes=state.latest_quotes,
            )
            if dependencies.database is not None
            else None
        )
        portfolio = (
            rebuilt.portfolio
            if rebuilt is not None
            else Portfolio(
                state.runtime_event_bus(),
                initial_cash=dependencies.config.initial_cash,
            )
        )
        if rebuilt is not None:
            watchlist, instruments = self._merged_runtime_assets(rebuilt.instruments)
            state.replace_runtime_assets(watchlist, instruments)
        for instrument in state.instruments.values():
            portfolio.add_instrument(instrument)
        state.install_runtime_portfolio(portfolio)

    def _merged_runtime_assets(
        self,
        rebuilt_instruments: dict[Symbol, Instrument],
    ) -> tuple[list[tuple[Symbol, AssetClass]], dict[Symbol, Instrument]]:
        instruments = self._state.instruments
        instruments.update(rebuilt_instruments)
        watchlist = self._state.watchlist
        watched_symbols = {symbol for symbol, _ in watchlist}
        for symbol, instrument in rebuilt_instruments.items():
            if symbol in watched_symbols:
                continue
            raw_asset_class = getattr(instrument, "asset_class", AssetClass.STOCK)
            if isinstance(raw_asset_class, AssetClass):
                asset_class = raw_asset_class
            else:
                raw_value = getattr(raw_asset_class, "value", raw_asset_class)
                try:
                    asset_class = AssetClass(str(raw_value))
                except ValueError:
                    asset_class = AssetClass.STOCK
            watchlist.append((symbol, asset_class))
            watched_symbols.add(symbol)
        return watchlist, instruments

    def _wire_event_processing(
        self,
        data_manager: SchedulerDataManager,
    ) -> tuple[SchedulerStrategy, BufferedStrategyEventPublisher]:
        state = self._state
        dependencies = self._dependencies
        event_bus = state.runtime_event_bus()
        strategy_events = BufferedStrategyEventPublisher()
        strategy = dependencies.strategy_factory(
            dependencies.config,
            strategy_events,
        )
        strategy.on_init([symbol for symbol, _ in state.watchlist])
        dependencies.warmup_strategy(data_manager, strategy)
        strategy_events.discard()
        dependencies.bridge_rebinder(event_bus)
        event_bus.subscribe(SignalEvent, dependencies.signal_handler)
        return strategy, strategy_events

    def _run_iteration(self, runtime: SchedulerRuntime) -> bool:
        state = self._state
        dependencies = self._dependencies
        current = self._dependencies.now()
        dependencies.evaluate_controlled_session_pauses()
        dependencies.retry_pending_valuation_publication()

        if not dependencies.is_market_open():
            if dependencies.is_post_close_refresh_window(current):
                dependencies.refresh_post_close_valuation_data(
                    runtime.data_manager,
                    now=current,
                )
            else:
                dependencies.backfill_historical_bars(
                    runtime.data_manager,
                    now=current,
                )
            state.wait_for_scheduler_stop(timeout=30)
            return False

        dependencies.sync_fund_nav_quotes()
        dependencies.sync_market_index_quotes(
            runtime.source,
            runtime.fallback_source,
        )
        self._poll_and_process(runtime, now=current)
        return True

    def _poll_and_process(
        self,
        runtime: SchedulerRuntime,
        *,
        now: datetime,
    ) -> None:
        state = self._state
        dependencies = self._dependencies
        quote_fetch_run_id = None
        staged_quotes: list[StagedSchedulerQuote] = []
        try:
            events, quote_fetch_run_id = dependencies.poll_watchlist_quotes(
                runtime.feed
            )
            for market_event in events:
                snapshot = (
                    runtime.feed.get_last_snapshot(
                        market_event.symbol,
                        market_event.asset_class,
                    )
                    or {}
                )
                staged_quotes.append(
                    self._record_market_event(
                        market_event=market_event,
                        snapshot=snapshot,
                        quote_fetch_run_id=quote_fetch_run_id,
                        now=now,
                    )
                )
            completed = dependencies.finish_persisted_quote_fetch_run(
                quote_fetch_run_id,
                events,
                [str(quote.runtime_quote["quote_status"]) for quote in staged_quotes],
            )
        except Exception as exc:
            self._finish_failed_poll(quote_fetch_run_id, exc)
            logger.exception("Error in trading loop iteration")
            runtime.strategy_events.discard()
            return

        if not completed:
            runtime.strategy_events.discard()
            return

        self._publish_runtime_batch(staged_quotes)
        if (
            not events
            or not is_complete_quote_batch(state.watchlist, events)
            or not all(quote.strategy_eligible for quote in staged_quotes)
        ):
            runtime.strategy_events.discard()
            return

        self._mark_to_market()
        try:
            for market_event in events:
                if market_event.asset_class is not AssetClass.FUND:
                    runtime.strategy.on_data(market_event)
        except Exception:
            runtime.strategy_events.discard()
            logger.exception("Strategy rejected persisted scheduler market batch")
            return
        event_bus = state.runtime_event_bus()
        runtime.strategy_events.flush_into(event_bus)
        event_bus.drain()

    def _record_market_event(
        self,
        *,
        market_event: MarketEvent,
        snapshot: dict[str, Any],
        quote_fetch_run_id: str | None,
        now: datetime,
    ) -> StagedSchedulerQuote:
        dependencies = self._dependencies
        database = dependencies.database
        if database is None:
            raise RuntimeError("scheduler database is unavailable")
        evidence = scheduler_quote_evidence(
            market_event,
            snapshot,
            now=now,
            live_poll_interval=dependencies.config.live_poll_interval,
        )
        command = self._quote_ingestion_command(
            market_event=market_event,
            snapshot=snapshot,
            quote_fetch_run_id=quote_fetch_run_id,
            now=now,
            evidence=evidence,
        )
        database.persist_quote_ingestion_sync(command)
        runtime_quote = command.valuation_row()
        display_name = str(command.display_name or "").strip()
        if display_name:
            runtime_quote.update(
                {
                    "display_name": display_name,
                    "name": display_name,
                }
            )
        return StagedSchedulerQuote(
            symbol=command.symbol,
            runtime_quote=runtime_quote,
            strategy_eligible=evidence.strategy_eligible,
        )

    def _quote_ingestion_command(
        self,
        *,
        market_event: MarketEvent,
        snapshot: dict[str, Any],
        quote_fetch_run_id: str | None,
        now: datetime,
        evidence: SchedulerQuoteEvidence,
    ) -> QuoteIngestionCommand:
        previous_close = optional_float(snapshot.get("previous_close"))
        previous_close_date = str(snapshot.get("previous_close_date") or "").strip()
        daily_close_price: float | None = None
        daily_close_date: str | None = None
        daily_close_source: str | None = None
        if previous_close is not None and previous_close_date:
            daily_close_price = previous_close
            daily_close_date = previous_close_date
            daily_close_source = "reported_previous_close"
        elif market_event.timestamp.time() >= self._dependencies.afternoon_close:
            daily_close_price = float(market_event.close)
            daily_close_date = evidence.quote_timestamp.split("T")[0]
            daily_close_source = "scheduler_close"

        raw_metadata = snapshot.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        return QuoteIngestionCommand(
            symbol=str(market_event.symbol),
            asset_type=market_event.asset_class.value,
            price=float(market_event.close),
            volume=float(market_event.volume),
            previous_close=previous_close,
            previous_close_date=previous_close_date or None,
            change=optional_float(
                snapshot.get("change") or snapshot.get("day_change_value")
            ),
            change_percent=optional_float(
                snapshot.get("change_percent")
                or snapshot.get("daily_change_pct")
                or snapshot.get("day_change_pct")
                or snapshot.get("pct_chg")
            ),
            turnover=optional_float(snapshot.get("turnover")),
            quote_timestamp=evidence.quote_timestamp,
            quote_source=evidence.quote_source,
            provider_name=evidence.provider_name,
            provider_status=evidence.provider_status,
            quote_status=evidence.quote_status,
            stale_reason=evidence.stale_reason,
            captured_at=now.isoformat(),
            captured_reason="scheduler_poll",
            nav_date=snapshot.get("nav_date"),
            fetch_run_id=quote_fetch_run_id,
            display_name=str(
                snapshot.get("display_name")
                or snapshot.get("name")
                or snapshot.get("asset_name")
                or ""
            ).strip()
            or None,
            provider_symbol=str(snapshot.get("provider_symbol") or market_event.symbol),
            exchange=(
                str(snapshot.get("exchange")).strip()
                if snapshot.get("exchange") not in {None, ""}
                else None
            ),
            market=(
                str(snapshot.get("market")).strip()
                if snapshot.get("market") not in {None, ""}
                else None
            ),
            source=str(snapshot.get("source") or evidence.provider_name),
            metadata=metadata,
            daily_close_price=daily_close_price,
            daily_close_date=daily_close_date,
            daily_close_source=daily_close_source,
        )

    def _publish_runtime_batch(
        self,
        staged_quotes: list[StagedSchedulerQuote],
    ) -> None:
        quotes = self._state.latest_quotes
        for staged in staged_quotes:
            quotes[staged.symbol] = dict(staged.runtime_quote)
        self._state.replace_runtime_quotes(quotes)

    def _mark_to_market(self) -> None:
        latest_quotes = self._state.latest_quotes
        prices = {
            symbol: Decimal(str(latest_quotes.get(str(symbol), {}).get("price", 0)))
            for symbol, _ in self._state.watchlist
        }
        portfolio = self._state.portfolio
        if portfolio is None:
            raise RuntimeError("scheduler portfolio is unavailable")
        portfolio.mark_to_market(prices)

    def _finish_failed_poll(
        self,
        quote_fetch_run_id: str | None,
        exc: Exception,
    ) -> None:
        state = self._state
        dependencies = self._dependencies
        if quote_fetch_run_id is None:
            return
        failed_symbols = [str(symbol) for symbol, _ in state.watchlist]
        metadata = quote_fetch_metadata(
            dependencies.config,
            state.watchlist,
            provider_status="failed",
            success_symbols=[],
            failed_symbols=failed_symbols,
            error_message=str(exc),
        )
        dependencies.finish_quote_fetch_run(
            run_id=quote_fetch_run_id,
            finished_at=self._dependencies.now().isoformat(),
            status="failed",
            success_count=0,
            failure_count=len(state.watchlist),
            metadata=metadata,
            error_message=str(exc),
        )


def run_scheduler_loop(
    state: SchedulerLoopState,
    dependencies: SchedulerLoopDependencies,
) -> None:
    """Run the scheduler with a stable dependency snapshot."""

    SchedulerLoop(state, dependencies).run()
