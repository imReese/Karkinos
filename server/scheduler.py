"""TradingScheduler — 后台线程运行交易循环。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Callable

from core.event_bus import EventBus
from core.events import SignalEvent
from core.types import AssetClass, BarFrequency, Symbol
from data.live import LiveDataFeed
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from server.bootstrap import build_strategy, create_runtime_context
from server.bridge import EventBusBridge
from server.scheduler_lifecycle import SchedulerLifecycleMixin
from server.scheduler_loop import SchedulerLoopDependencies, run_scheduler_loop
from server.scheduler_quote_runs import SchedulerQuoteRunMixin
from server.scheduler_signals import handle_scheduler_signal
from server.scheduler_values import optional_float
from server.services.fund_nav_sync import refresh_fund_nav_quotes
from server.services.market_hours import is_cn_trading_session
from server.services.market_indices import default_market_index_assets
from server.services.market_quote_ingestion import (
    build_quote_ingestion_command,
    persist_quote_ingestion,
)
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.trading_controls import TradingControlState

if TYPE_CHECKING:
    from server.config import ServerConfig

logger = logging.getLogger(__name__)

# A 股交易时段（上午 9:30-11:30，下午 13:00-15:00）
_MORNING_OPEN = time(9, 30)
_MORNING_CLOSE = time(11, 30)
_AFTERNOON_OPEN = time(13, 0)
_AFTERNOON_CLOSE = time(15, 0)
_POST_CLOSE_MARKET_REFRESH_TIME = time(16, 0)
_POST_CLOSE_FUND_NAV_REFRESH_TIME = time(21, 30)
_SCHEDULER_STOP_TIMEOUT_SECONDS = 10.0


def scheduler_now() -> datetime:
    return datetime.now()


class TradingScheduler(SchedulerLifecycleMixin, SchedulerQuoteRunMixin):
    """后台交易调度器。

    将 live.py 的 while-True 循环封装为可控后台线程，
    通过 threading.Event 实现优雅启停。
    """

    def __init__(
        self,
        config: ServerConfig,
        bridge: EventBusBridge,
        notifier=None,
        db=None,
        trading_controls: TradingControlState | None = None,
        controlled_session_pause_runner: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._notifier = notifier
        self._db = db
        self._trading_controls = trading_controls or TradingControlState(db=db)
        self._controlled_session_pause_runner = controlled_session_pause_runner
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._stopping = False
        self._scheduler_clock = scheduler_now

        # 运行时状态（由后台线程修改，API 线程读取）
        self._event_bus: EventBus | None = None
        self._portfolio: Portfolio | None = None
        self._watchlist: list[tuple[Symbol, AssetClass]] = []
        self._instruments: dict[Symbol, Instrument] = {}
        self._latest_quotes: dict[str, dict[str, Any]] = {}  # 报价缓存
        self._last_historical_bar_backfill_key: str | None = None
        self._last_post_close_market_refresh_date: str | None = None
        self._last_post_close_fund_nav_refresh_date: str | None = None
        self._pending_valuation_publication_reason: str | None = None
        self._stop_requested = threading.Event()

        # Bug 3: 线程安全锁
        self._lock = threading.Lock()

    @staticmethod
    def scheduler_stop_timeout_seconds() -> float:
        return _SCHEDULER_STOP_TIMEOUT_SECONDS

    @property
    def is_market_open(self) -> bool:
        """当前是否在 A 股交易时段。"""
        return self._is_market_open()

    @property
    def portfolio(self) -> Portfolio | None:
        with self._lock:
            return self._portfolio

    @property
    def event_bus(self) -> EventBus | None:
        return self._event_bus

    @property
    def watchlist(self) -> list[tuple[Symbol, AssetClass]]:
        with self._lock:
            return list(self._watchlist)

    @property
    def instruments(self) -> dict[Symbol, Instrument]:
        with self._lock:
            return dict(self._instruments)

    @property
    def latest_quotes(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._latest_quotes)

    def scheduler_should_continue(self) -> bool:
        return self._running.is_set()

    def request_scheduler_stop(self) -> None:
        self._stop_requested.set()
        self._running.clear()

    def wait_for_scheduler_stop(self, timeout: float) -> bool:
        return self._stop_requested.wait(timeout=timeout)

    def runtime_event_bus(self) -> EventBus:
        event_bus = self._event_bus
        if event_bus is None:
            raise RuntimeError("scheduler event bus is unavailable")
        return event_bus

    def install_runtime_event_bus(self, event_bus: EventBus) -> None:
        with self._lock:
            self._event_bus = event_bus

    def replace_runtime_assets(
        self,
        watchlist: list[tuple[Symbol, AssetClass]],
        instruments: dict[Symbol, Instrument],
    ) -> None:
        with self._lock:
            self._watchlist = list(watchlist)
            self._instruments = dict(instruments)

    def replace_runtime_quotes(self, quotes: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            self._latest_quotes = dict(quotes)

    def publish_runtime_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        """Publish one already-persisted quote into the runtime cache."""

        with self._lock:
            self._latest_quotes[symbol] = dict(quote)

    def install_runtime_portfolio(self, portfolio: Portfolio) -> None:
        with self._lock:
            self._portfolio = portfolio

    @staticmethod
    def _is_market_open() -> bool:
        """Bug 7: 判断当前是否在 A 股交易时段内。"""
        return is_cn_trading_session()

    def _warmup_strategy(self, data_manager, strategy) -> None:
        """Bug 6: 用历史日线预热策略，避免前 N 个周期信号不准。

        非交易时段跳过预热，避免 AKShare 不稳定时阻塞线程。
        """
        if not self._is_market_open():
            logger.info("非交易时段，跳过策略预热")
            return

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=60)  # 取近 60 天日线

            for sym, ac in self._watchlist:
                try:
                    handler = data_manager.get_bars(
                        sym,
                        start=start_date,
                        end=end_date,
                        asset_class=ac,
                        allow_remote_refresh=False,
                        degrade_to_cache=True,
                    )
                    for market_event in handler:
                        strategy.on_data(market_event)
                    logger.info("策略预热完成: %s (%d bars)", sym, handler.total_bars)
                except Exception:
                    logger.warning("策略预热失败: %s，将跳过", sym, exc_info=True)
        except Exception:
            logger.warning("策略预热整体失败，将跳过", exc_info=True)

    def _historical_bar_backfill_range(
        self, now: datetime
    ) -> tuple[datetime, datetime]:
        end_day = now.date()
        if now.time() < _AFTERNOON_CLOSE:
            end_day = (now - timedelta(days=1)).date()

        start_day = end_day - timedelta(days=365)
        configured_start = getattr(self._config, "start_date", None)
        if configured_start:
            try:
                start_day = min(
                    start_day,
                    datetime.fromisoformat(str(configured_start)).date(),
                )
            except ValueError:
                logger.warning(
                    "Invalid start_date for bar backfill: %s",
                    configured_start,
                )

        return (
            datetime.combine(start_day, time.min),
            datetime.combine(end_day, time.min),
        )

    def _maybe_backfill_historical_bars(
        self,
        data_manager,
        *,
        now: datetime | None = None,
    ) -> None:
        """Backfill daily OHLCV bars once per effective close date."""
        current = now or datetime.now()
        start_date, end_date = self._historical_bar_backfill_range(current)
        run_key = f"{BarFrequency.DAILY.value}:{end_date.date().isoformat()}"
        if self._last_historical_bar_backfill_key == run_key:
            self._retry_pending_valuation_publication()
            return

        with self._lock:
            targets = list(self._watchlist)
        if not targets:
            return

        updated = 0
        failed = 0
        for symbol, asset_class in targets:
            try:
                handler = data_manager.get_bars(
                    symbol,
                    start=start_date,
                    end=end_date,
                    frequency=BarFrequency.DAILY,
                    asset_class=asset_class,
                    allow_remote_refresh=True,
                    refresh_ttl_seconds=0,
                    degrade_to_cache=True,
                )
                updated += 1
                logger.info(
                    "历史行情补齐完成: %s (%s) %s~%s, bars=%d",
                    symbol,
                    asset_class.value,
                    start_date.date(),
                    end_date.date(),
                    getattr(handler, "total_bars", 0),
                )
            except Exception:
                failed += 1
                logger.warning(
                    "历史行情补齐失败: %s (%s) %s~%s",
                    symbol,
                    asset_class.value,
                    start_date.date(),
                    end_date.date(),
                    exc_info=True,
                )

        self._last_historical_bar_backfill_key = run_key
        self._publish_current_valuation_snapshot(
            reason=f"historical_bar_backfill:{run_key}"
        )
        logger.info(
            "历史行情补齐批次完成: date=%s, updated=%d, failed=%d",
            end_date.date(),
            updated,
            failed,
        )

    def _publish_current_valuation_snapshot(self, *, reason: str) -> bool:
        """Publish one identity after a persisted valuation-input batch."""
        if self._db is None or not hasattr(
            self._db, "publish_current_valuation_snapshot_sync"
        ):
            return False
        try:
            self._db.publish_current_valuation_snapshot_sync()
        except Exception:
            self._pending_valuation_publication_reason = reason
            logger.exception(
                "估值快照发布失败，将保持财务读取阻断并重试: reason=%s",
                reason,
            )
            return False
        self._pending_valuation_publication_reason = None
        return True

    def _retry_pending_valuation_publication(self) -> bool:
        reason = self._pending_valuation_publication_reason
        if reason is None:
            return True
        return self._publish_current_valuation_snapshot(reason=reason)

    @staticmethod
    def _is_post_close_valuation_refresh_window(now: datetime) -> bool:
        """Return whether same-day close data should wait for fixed refresh."""
        return now.weekday() < 5 and now.time() >= _AFTERNOON_CLOSE

    def _should_refresh_post_close_market_data(self, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        if now.time() < _POST_CLOSE_MARKET_REFRESH_TIME:
            return False
        run_date = now.date().isoformat()
        return self._last_post_close_market_refresh_date != run_date

    def _should_refresh_post_close_fund_nav_data(self, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        if now.time() < _POST_CLOSE_FUND_NAV_REFRESH_TIME:
            return False
        run_date = now.date().isoformat()
        return self._last_post_close_fund_nav_refresh_date != run_date

    def _maybe_refresh_post_close_valuation_data(
        self,
        data_manager,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Refresh close-driven valuation inputs once after the fixed close time."""
        current = now or datetime.now()
        run_date = current.date().isoformat()
        refreshed = False

        if self._should_refresh_post_close_market_data(current):
            self._maybe_backfill_historical_bars(data_manager, now=current)
            self._last_post_close_market_refresh_date = run_date
            logger.info(
                "收盘后行情刷新完成: date=%s, scheduled_time=%s",
                run_date,
                _POST_CLOSE_MARKET_REFRESH_TIME.isoformat(timespec="minutes"),
            )
            refreshed = True

        if self._should_refresh_post_close_fund_nav_data(current):
            self._sync_fund_nav_quotes(confirmation_only=True)
            self._last_post_close_fund_nav_refresh_date = run_date
            logger.info(
                "收盘后基金净值确认刷新完成: date=%s, scheduled_time=%s",
                run_date,
                _POST_CLOSE_FUND_NAV_REFRESH_TIME.isoformat(timespec="minutes"),
            )
            refreshed = True

        return refreshed

    def _sync_fund_nav_quotes(self, *, confirmation_only: bool = False) -> None:
        """Refresh fund NAV/estimate quotes independently from stock quote polling."""
        if self._db is None:
            return
        with self._lock:
            watchlist = list(self._watchlist)
            latest_quotes = dict(self._latest_quotes)
        if not any(asset_class is AssetClass.FUND for _, asset_class in watchlist):
            return

        try:
            refresh_kwargs = {"confirmation_only": True} if confirmation_only else {}
            result = refresh_fund_nav_quotes(
                self._config,
                self._db,
                watchlist,
                latest_quotes,
                **refresh_kwargs,
            )
        except Exception:
            logger.warning("基金净值/估值同步失败，将保留已有快照", exc_info=True)
            return

        if result.quotes:
            with self._lock:
                self._latest_quotes.update(result.quotes)
        if "__valuation_snapshot__" in result.failed:
            self._pending_valuation_publication_reason = "fund_nav_sync"

    def _fetch_market_index_snapshot(
        self,
        source,
        fallback_source,
        symbol: Symbol,
    ) -> dict | None:
        for candidate_source in (source, fallback_source):
            if candidate_source is None or not hasattr(
                candidate_source, "fetch_latest"
            ):
                continue
            try:
                snapshot = candidate_source.fetch_latest(symbol, AssetClass.INDEX)
            except Exception:
                logger.warning(
                    "默认指数行情同步失败: %s (%s)",
                    symbol,
                    AssetClass.INDEX.value,
                    exc_info=True,
                )
                snapshot = None
            if snapshot is not None:
                return snapshot
        return None

    def _sync_default_market_index_quotes(self, source, fallback_source=None) -> None:
        """Refresh broad-market index quotes without feeding them to strategies."""
        current = datetime.now()
        for asset in default_market_index_assets():
            symbol = Symbol(asset["symbol"])
            snapshot = self._fetch_market_index_snapshot(
                source,
                fallback_source,
                symbol,
            )
            if snapshot is None:
                continue
            price = snapshot.get("price")
            if price in {None, ""}:
                continue
            try:
                price_value = float(price)
            except (TypeError, ValueError):
                continue
            if price_value <= 0:
                continue

            timestamp = str(snapshot.get("timestamp") or current.isoformat())
            quote_source = str(
                snapshot.get("quote_source")
                or snapshot.get("source")
                or snapshot.get("provider")
                or self._config.data_source
            )
            provider_name = str(
                snapshot.get("provider_name")
                or snapshot.get("provider")
                or snapshot.get("source")
                or self._config.data_source
            )
            display_name = str(
                snapshot.get("display_name")
                or snapshot.get("name")
                or asset["display_name"]
            ).strip()
            cached_quote = {
                "price": price_value,
                "volume": optional_float(snapshot.get("volume")) or 0,
                "timestamp": timestamp,
                "asset_class": AssetClass.INDEX.value,
                "quote_source": quote_source,
                "provider_name": provider_name,
                "quote_status": "live",
                "provider_status": "live",
                "captured_reason": "scheduler_market_index_sync",
                "display_name": display_name,
                "name": display_name,
                "daily_change": optional_float(
                    snapshot.get("daily_change") or snapshot.get("change")
                ),
                "daily_change_pct": optional_float(
                    snapshot.get("daily_change_pct")
                    or snapshot.get("change_pct")
                    or snapshot.get("pct_chg")
                ),
            }
            if self._db is None:
                continue
            command = build_quote_ingestion_command(
                symbol=str(symbol),
                asset_type=AssetClass.INDEX.value,
                snapshot={
                    **snapshot,
                    "price": price_value,
                    "volume": cached_quote["volume"],
                    "timestamp": timestamp,
                    "change": cached_quote["daily_change"],
                    "change_percent": cached_quote["daily_change_pct"],
                    "display_name": display_name,
                    "provider_symbol": str(symbol),
                },
                quote_source=quote_source,
                provider_name=provider_name,
                provider_status="live",
                quote_status="live",
                captured_reason="scheduler_market_index_sync",
                fetch_run_id=None,
                captured_at=current.isoformat(),
            )
            persist_quote_ingestion(self._db, command)
            self.publish_runtime_quote(str(symbol), cached_quote)

    def _run_loop(self) -> None:
        """Run the background loop with late-bound composition dependencies."""
        run_scheduler_loop(
            self,
            SchedulerLoopDependencies(
                event_bus_factory=EventBus,
                runtime_context_factory=create_runtime_context,
                live_data_feed_factory=LiveDataFeed,
                portfolio_rebuilder=rebuild_portfolio_from_ledger,
                strategy_factory=build_strategy,
                now=self._scheduler_clock,
                afternoon_close=_AFTERNOON_CLOSE,
                config=self._config,
                database=self._db,
                bridge_rebinder=self._bridge.rebind,
                warmup_strategy=self._warmup_strategy,
                signal_handler=self._on_signal,
                evaluate_controlled_session_pauses=(
                    self._evaluate_controlled_session_pauses
                ),
                retry_pending_valuation_publication=(
                    self._retry_pending_valuation_publication
                ),
                is_market_open=self._is_market_open,
                is_post_close_refresh_window=(
                    self._is_post_close_valuation_refresh_window
                ),
                refresh_post_close_valuation_data=(
                    self._maybe_refresh_post_close_valuation_data
                ),
                backfill_historical_bars=self._maybe_backfill_historical_bars,
                sync_fund_nav_quotes=self._sync_fund_nav_quotes,
                sync_market_index_quotes=self._sync_default_market_index_quotes,
                poll_watchlist_quotes=self._poll_watchlist_quotes,
                finish_persisted_quote_fetch_run=(
                    self._finish_persisted_quote_fetch_run
                ),
                finish_quote_fetch_run=self._finish_scheduler_quote_fetch_run,
            ),
        )

    def _evaluate_controlled_session_pauses(self) -> dict[str, Any] | None:
        """Run fail-closed session gate checks when live monitoring is explicit."""
        if not callable(self._controlled_session_pause_runner):
            return None
        try:
            result = self._controlled_session_pause_runner() or {}
        except Exception:
            logger.exception("Controlled-session automatic-pause evaluation failed")
            return {
                "status": "failed",
                "failure_count": 1,
                "broker_submission_enabled": False,
            }
        if int(result.get("paused_count") or 0):
            logger.warning(
                "Automatically paused %d controlled session(s)",
                int(result.get("paused_count") or 0),
            )
        if int(result.get("failure_count") or 0):
            logger.warning(
                "Controlled-session pause evaluation had %d failure(s)",
                int(result.get("failure_count") or 0),
            )
        return result

    def _on_signal(self, event: SignalEvent) -> None:
        """Persist and project a signal without granting execution authority."""
        handle_scheduler_signal(
            event,
            watchlist=self.watchlist,
            database=self._db,
            portfolio=self.portfolio,
            notifier=self._notifier,
        )
