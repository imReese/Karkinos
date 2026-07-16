"""TradingScheduler — 后台线程运行交易循环。"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable

from core.event_bus import EventBus
from core.events import SignalEvent
from core.types import AssetClass, BarFrequency, Symbol
from data.live import LiveDataFeed
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from execution.connector import PaperExecutionConnector
from execution.gateway import ManualConfirmGateway
from notification.notifier import build_notifier, format_signal_message
from risk.pre_trade import PreTradePolicy, PreTradeRiskManager
from server.bootstrap import build_strategy, create_runtime_context
from server.bridge import EventBusBridge
from server.services.fund_nav_sync import refresh_fund_nav_quotes
from server.services.live_context import LiveContextProvider
from server.services.market_hours import is_cn_trading_session
from server.services.market_indices import default_market_index_assets
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.recommendation_flow import build_recommendation_cycle
from server.services.trading_controls import TradingControlState
from server.services.valuation_snapshot import build_current_valuation_snapshot

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


class TradingScheduler:
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

        # 运行时状态（由后台线程修改，API 线程读取）
        self._event_bus: EventBus | None = None
        self._portfolio: Portfolio | None = None
        self._watchlist: list[tuple[Symbol, AssetClass]] = []
        self._instruments: dict[Symbol, Instrument] = {}
        self._latest_quotes: dict[str, dict] = {}  # 报价缓存
        self._last_historical_bar_backfill_key: str | None = None
        self._last_post_close_market_refresh_date: str | None = None
        self._last_post_close_fund_nav_refresh_date: str | None = None
        self._stop_requested = threading.Event()

        # Bug 3: 线程安全锁
        self._lock = threading.Lock()

    def start(self) -> None:
        """启动后台交易线程。"""
        if self._running.is_set():
            return
        self._stop_requested.clear()
        self._running.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("TradingScheduler started")

    def stop(self) -> None:
        """停止后台交易线程。"""
        self._stop_requested.set()
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("TradingScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

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
    def latest_quotes(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._latest_quotes)

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
        logger.info(
            "历史行情补齐批次完成: date=%s, updated=%d, failed=%d",
            end_date.date(),
            updated,
            failed,
        )

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

    def _scheduler_quote_fetch_asset_type(self) -> str | None:
        asset_types = {asset_class.value for _, asset_class in self._watchlist}
        if not asset_types:
            return None
        if len(asset_types) == 1:
            return next(iter(asset_types))
        return "mixed"

    def _scheduler_quote_fetch_metadata(
        self,
        *,
        provider_status: str,
        success_symbols: list[str],
        failed_symbols: list[str],
        error_message: str | None = None,
    ) -> dict:
        success_count = len(success_symbols)
        failure_count = len(failed_symbols)
        return {
            "trigger": "scheduler_poll",
            "provider": self._config.data_source,
            "provider_status": provider_status,
            "market_open": True,
            "poll_interval_seconds": self._config.live_poll_interval,
            "symbols": [str(symbol) for symbol, _ in self._watchlist],
            "asset_types": [asset_class.value for _, asset_class in self._watchlist],
            "success_symbols": success_symbols,
            "failed_symbols": failed_symbols,
            "symbol_count": len(self._watchlist),
            "success_count": success_count,
            "failure_count": failure_count,
            "cache_hit_count": 0,
            "quote_status_counts": {"live": success_count} if success_count else {},
            "stale_reason_counts": {},
            "error_message": error_message,
        }

    def _scheduler_quote_fetch_status(
        self, *, success_count: int, failure_count: int
    ) -> str:
        if success_count == len(self._watchlist) and failure_count == 0:
            return "success"
        if success_count > 0:
            return "partial_success"
        return "failed"

    def _provider_status_for_scheduler_run(
        self, *, success_count: int, failure_count: int
    ) -> str:
        if success_count == len(self._watchlist) and failure_count == 0:
            return "live"
        if success_count > 0:
            return "partial"
        return "failed"

    def _create_scheduler_quote_fetch_run(
        self, *, run_id: str, started_at: str
    ) -> None:
        if self._db is None or not hasattr(self._db, "create_quote_fetch_run"):
            return
        try:
            self._db.create_quote_fetch_run(
                run_id=run_id,
                started_at=started_at,
                trigger="scheduler_poll",
                provider=self._config.data_source,
                asset_type=self._scheduler_quote_fetch_asset_type(),
                symbol_count=len(self._watchlist),
                status="running",
                metadata={
                    "trigger": "scheduler_poll",
                    "provider": self._config.data_source,
                    "market_open": True,
                    "poll_interval_seconds": self._config.live_poll_interval,
                    "symbols": [str(symbol) for symbol, _ in self._watchlist],
                    "asset_types": [
                        asset_class.value for _, asset_class in self._watchlist
                    ],
                },
            )
        except Exception:
            logger.warning("Failed to create scheduler quote fetch run", exc_info=True)

    def _finish_scheduler_quote_fetch_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int,
        failure_count: int,
        metadata: dict,
        error_message: str | None = None,
    ) -> None:
        if self._db is None or not hasattr(self._db, "finish_quote_fetch_run"):
            return
        try:
            self._db.finish_quote_fetch_run(
                run_id=run_id,
                finished_at=finished_at,
                status=status,
                success_count=success_count,
                failure_count=failure_count,
                cache_hit_count=0,
                error_message=error_message,
                metadata=metadata,
            )
        except Exception:
            logger.warning("Failed to finish scheduler quote fetch run", exc_info=True)

    def _poll_watchlist_quotes(self, feed: LiveDataFeed) -> tuple[list, str]:
        """Poll live quotes once and return the still-open ingestion run id."""
        started_at_dt = datetime.now()
        run_id = f"scheduler_poll:{started_at_dt.isoformat()}:{uuid.uuid4().hex}"
        self._create_scheduler_quote_fetch_run(
            run_id=run_id,
            started_at=started_at_dt.isoformat(),
        )
        try:
            events = feed.poll_all(self._watchlist)
        except Exception as exc:
            failed_symbols = [str(symbol) for symbol, _ in self._watchlist]
            metadata = self._scheduler_quote_fetch_metadata(
                provider_status="failed",
                success_symbols=[],
                failed_symbols=failed_symbols,
                error_message=str(exc),
            )
            self._finish_scheduler_quote_fetch_run(
                run_id=run_id,
                finished_at=datetime.now().isoformat(),
                status="failed",
                success_count=0,
                failure_count=len(self._watchlist),
                metadata=metadata,
                error_message=str(exc),
            )
            raise

        return events, run_id

    def _finish_persisted_quote_fetch_run(self, run_id: str, events: list) -> None:
        """Complete a quote run only after its observations are persisted."""
        success_symbols = [str(event.symbol) for event in events]
        success_symbol_set = set(success_symbols)
        failed_symbols = [
            str(symbol)
            for symbol, _ in self._watchlist
            if str(symbol) not in success_symbol_set
        ]
        success_count = len(events)
        failure_count = len(self._watchlist) - success_count
        status = self._scheduler_quote_fetch_status(
            success_count=success_count,
            failure_count=failure_count,
        )
        provider_status = self._provider_status_for_scheduler_run(
            success_count=success_count,
            failure_count=failure_count,
        )
        metadata = self._scheduler_quote_fetch_metadata(
            provider_status=provider_status,
            success_symbols=success_symbols,
            failed_symbols=failed_symbols,
        )
        self._finish_scheduler_quote_fetch_run(
            run_id=run_id,
            finished_at=datetime.now().isoformat(),
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            metadata=metadata,
        )

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

    @staticmethod
    def _optional_float(value) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(str(value).replace("%", "").strip())
        except (TypeError, ValueError):
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
                "volume": self._optional_float(snapshot.get("volume")) or 0,
                "timestamp": timestamp,
                "asset_class": AssetClass.INDEX.value,
                "quote_source": quote_source,
                "provider_name": provider_name,
                "quote_status": "live",
                "provider_status": "live",
                "captured_reason": "scheduler_market_index_sync",
                "display_name": display_name,
                "name": display_name,
                "daily_change": self._optional_float(
                    snapshot.get("daily_change") or snapshot.get("change")
                ),
                "daily_change_pct": self._optional_float(
                    snapshot.get("daily_change_pct")
                    or snapshot.get("change_pct")
                    or snapshot.get("pct_chg")
                ),
            }
            with self._lock:
                self._latest_quotes[str(symbol)] = cached_quote

            if self._db is None:
                continue
            self._db.save_quote_snapshot_sync(
                symbol=str(symbol),
                asset_class=AssetClass.INDEX.value,
                price=price_value,
                volume=cached_quote["volume"],
                timestamp=timestamp,
                quote_source=quote_source,
                provider_name=provider_name,
                quote_status="live",
                provider_status="live",
                captured_reason="scheduler_market_index_sync",
            )
            if hasattr(self._db, "upsert_latest_quote_sync"):
                self._db.upsert_latest_quote_sync(
                    symbol=str(symbol),
                    asset_type=AssetClass.INDEX.value,
                    price=price_value,
                    change=cached_quote["daily_change"],
                    change_percent=cached_quote["daily_change_pct"],
                    volume=cached_quote["volume"],
                    quote_timestamp=timestamp,
                    quote_source=quote_source,
                    provider_name=provider_name,
                    provider_status="live",
                    quote_status="live",
                    captured_at=current.isoformat(),
                    captured_reason="scheduler_market_index_sync",
                    metadata={
                        "source": snapshot.get("source") or quote_source,
                        "display_name": display_name,
                        "daily_change": cached_quote["daily_change"],
                        "daily_change_pct": cached_quote["daily_change_pct"],
                    },
                )
            if hasattr(self._db, "upsert_instrument_metadata_sync"):
                self._db.upsert_instrument_metadata_sync(
                    symbol=str(symbol),
                    asset_type=AssetClass.INDEX.value,
                    display_name=display_name,
                    provider_symbol=str(symbol),
                    provider_name=provider_name,
                    source="default_market_index",
                    fetched_at=timestamp,
                    metadata={
                        "source": snapshot.get("source") or quote_source,
                        "quote_source": quote_source,
                    },
                )

    def _run_loop(self) -> None:
        """后台线程主循环。"""
        # 初始化组件
        self._event_bus = EventBus()
        runtime = create_runtime_context(self._config)
        source = runtime.sources.get(
            self._config.data_source, runtime.sources["akshare"]
        )
        fallback_source = None
        if self._config.data_source != "akshare":
            fallback_source = runtime.sources.get("akshare")
        feed = LiveDataFeed(source, self._event_bus, fallback_source=fallback_source)
        data_manager = runtime.data_manager

        persisted_watchlist = []
        if self._db is not None and hasattr(self._db, "list_watchlist_assets_sync"):
            try:
                persisted_watchlist = self._db.list_watchlist_assets_sync()
            except Exception:
                logger.warning("恢复数据库关注列表失败，将忽略", exc_info=True)

        # 构建关注列表
        with self._lock:
            self._watchlist = [] if persisted_watchlist else list(runtime.watchlist)
            self._instruments = {} if persisted_watchlist else dict(runtime.instruments)
            self._latest_quotes = {}

        if persisted_watchlist:
            try:
                with self._lock:
                    watched_symbols = {symbol for symbol, _ in self._watchlist}
                    for asset in persisted_watchlist:
                        symbol = Symbol(str(asset.get("symbol") or "").strip())
                        if not str(symbol) or symbol in watched_symbols:
                            continue
                        raw_asset_class = str(asset.get("asset_class") or "stock")
                        asset_class = {
                            "stock": AssetClass.STOCK,
                            "fund": AssetClass.FUND,
                            "etf": AssetClass.FUND,
                            "gold": AssetClass.GOLD,
                            "bond": AssetClass.BOND,
                        }.get(raw_asset_class, AssetClass.STOCK)
                        self._watchlist.append((symbol, asset_class))
                        self._instruments.setdefault(
                            symbol,
                            data_manager.get_instrument(symbol, asset_class),
                        )
                        watched_symbols.add(symbol)
            except Exception:
                logger.warning("应用数据库关注列表失败，将忽略", exc_info=True)

        if self._db is not None:
            try:
                persisted_quotes = self._db.get_latest_quotes_sync()
                with self._lock:
                    for quote in persisted_quotes:
                        quote_source = (
                            quote.get("quote_source")
                            or quote.get("source")
                            or quote.get("provider_name")
                            or quote.get("provider")
                        )
                        self._latest_quotes[quote["symbol"]] = {
                            "price": float(quote["price"]),
                            "volume": (
                                float(quote["volume"])
                                if quote["volume"] is not None
                                else None
                            ),
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
            except Exception:
                logger.warning("恢复实时行情快照失败，将忽略", exc_info=True)

        # 创建组合
        with self._lock:
            rebuilt = (
                rebuild_portfolio_from_ledger(
                    self._config,
                    self._db,
                    latest_quotes=self._latest_quotes,
                )
                if self._db is not None
                else None
            )
            self._portfolio = (
                rebuilt.portfolio
                if rebuilt is not None
                else Portfolio(
                    self._event_bus,
                    initial_cash=self._config.initial_cash,
                )
            )
            if rebuilt is not None:
                self._instruments.update(rebuilt.instruments)
                watched_symbols = {symbol for symbol, _ in self._watchlist}
                for symbol, instrument in rebuilt.instruments.items():
                    if symbol in watched_symbols:
                        continue
                    raw_asset_class = getattr(
                        instrument,
                        "asset_class",
                        AssetClass.STOCK,
                    )
                    if isinstance(raw_asset_class, AssetClass):
                        asset_class = raw_asset_class
                    else:
                        raw_value = getattr(raw_asset_class, "value", raw_asset_class)
                        try:
                            asset_class = AssetClass(str(raw_value))
                        except ValueError:
                            asset_class = AssetClass.STOCK
                    self._watchlist.append((symbol, asset_class))
                    watched_symbols.add(symbol)
            for inst in self._instruments.values():
                self._portfolio.add_instrument(inst)

        if not self._watchlist:
            logger.warning("No watchlist configured, stopping scheduler")
            self._running.clear()
            return

        # 实盘安全链路：OrderIntentEvent -> PreTradeRiskManager -> OrderEvent
        # -> execution connector/gateway -> SQLite order/fill facts.
        context_provider = LiveContextProvider(
            portfolio_getter=lambda: self.portfolio,
            controls=self._trading_controls,
            blacklist_getter=self._configured_symbol_set(
                "blacklist", "symbol_blacklist"
            ),
            st_symbols_getter=self._configured_symbol_set("st_symbols", "st_blacklist"),
        )
        PreTradeRiskManager(
            self._event_bus,
            context_provider,
            PreTradePolicy(execution_mode="manual"),
            db=self._db,
        )
        ManualConfirmGateway(self._event_bus, db=self._db)
        PaperExecutionConnector(event_bus=self._event_bus, db=self._db)

        # 创建策略（使用注册表）
        strategy = build_strategy(self._config, self._event_bus)
        strategy.on_init([sym for sym, _ in self._watchlist])

        # Bug 6: 历史数据预热
        self._warmup_strategy(data_manager, strategy)

        # Bug 2: 重新绑定 bridge 到新 EventBus（复用同一对象）
        self._bridge.rebind(self._event_bus)

        # 订阅信号 → 通知
        self._event_bus.subscribe(SignalEvent, self._on_signal)

        logger.info(
            "Trading loop started, watching %d symbols, interval=%ds",
            len(self._watchlist),
            self._config.live_poll_interval,
        )

        # 主循环
        while self._running.is_set():
            current = datetime.now()
            self._evaluate_controlled_session_pauses()

            # Bug 7: 非交易时段跳过轮询
            if not self._is_market_open():
                if self._is_post_close_valuation_refresh_window(current):
                    self._maybe_refresh_post_close_valuation_data(
                        data_manager,
                        now=current,
                    )
                else:
                    self._maybe_backfill_historical_bars(data_manager, now=current)
                self._stop_requested.wait(timeout=30)
                continue

            self._sync_fund_nav_quotes()
            self._sync_default_market_index_quotes(source, fallback_source)

            quote_fetch_run_id = None
            try:
                events, quote_fetch_run_id = self._poll_watchlist_quotes(feed)
                if events:
                    for market_event in events:
                        snapshot = (
                            feed.get_last_snapshot(
                                market_event.symbol, market_event.asset_class
                            )
                            or {}
                        )
                        snapshot_timestamp = str(
                            snapshot.get("timestamp")
                            or market_event.timestamp.isoformat()
                        )
                        # 更新报价缓存
                        sym_str = str(market_event.symbol)
                        with self._lock:
                            self._latest_quotes[sym_str] = {
                                "price": float(market_event.close),
                                "volume": float(market_event.volume),
                                "timestamp": snapshot_timestamp,
                                "asset_class": market_event.asset_class.value,
                                "previous_close": snapshot.get("previous_close"),
                                "previous_close_date": snapshot.get(
                                    "previous_close_date"
                                ),
                            }
                        if self._db is not None:
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
                            self._db.save_quote_snapshot_sync(
                                symbol=sym_str,
                                asset_class=market_event.asset_class.value,
                                price=float(market_event.close),
                                volume=float(market_event.volume),
                                timestamp=snapshot_timestamp,
                                quote_source=quote_source,
                                provider_name=provider_name,
                                quote_status="live",
                                provider_status="live",
                                captured_reason="scheduler_poll",
                                nav_date=snapshot.get("nav_date"),
                                fetch_run_id=quote_fetch_run_id,
                            )
                            previous_close = snapshot.get("previous_close")
                            previous_close_date = snapshot.get("previous_close_date")
                            if previous_close not in {
                                None,
                                "",
                            } and previous_close_date not in {
                                None,
                                "",
                            }:
                                self._db.save_daily_close_snapshot_sync(
                                    symbol=sym_str,
                                    asset_class=market_event.asset_class.value,
                                    trade_date=str(previous_close_date),
                                    close_price=float(previous_close),
                                    source="reported_previous_close",
                                )
                            elif market_event.timestamp.time() >= _AFTERNOON_CLOSE:
                                self._db.save_daily_close_snapshot_sync(
                                    symbol=sym_str,
                                    asset_class=market_event.asset_class.value,
                                    trade_date=str(snapshot_timestamp).split("T")[0],
                                    close_price=float(market_event.close),
                                    source="scheduler_close",
                                )
                            if hasattr(self._db, "upsert_latest_quote_sync"):
                                try:
                                    self._db.upsert_latest_quote_sync(
                                        symbol=sym_str,
                                        asset_type=market_event.asset_class.value,
                                        price=float(market_event.close),
                                        previous_close=(
                                            None
                                            if previous_close in {None, ""}
                                            else float(previous_close)
                                        ),
                                        volume=float(market_event.volume),
                                        quote_timestamp=snapshot_timestamp,
                                        quote_source=quote_source,
                                        provider_name=provider_name,
                                        provider_status="live",
                                        quote_status="live",
                                        captured_at=datetime.now().isoformat(),
                                        captured_reason="scheduler_poll",
                                        nav_date=snapshot.get("nav_date"),
                                        fetch_run_id=quote_fetch_run_id,
                                        metadata={
                                            "source": snapshot.get("source"),
                                            "previous_close_date": previous_close_date,
                                        },
                                    )
                                except Exception:
                                    logger.warning(
                                        "Failed to upsert latest quote for %s",
                                        sym_str,
                                        exc_info=True,
                                    )
                            display_name = str(
                                snapshot.get("display_name")
                                or snapshot.get("name")
                                or snapshot.get("asset_name")
                                or ""
                            ).strip()
                            if display_name and hasattr(
                                self._db, "upsert_instrument_metadata_sync"
                            ):
                                try:
                                    self._db.upsert_instrument_metadata_sync(
                                        symbol=sym_str,
                                        asset_type=market_event.asset_class.value,
                                        display_name=display_name,
                                        provider_symbol=sym_str,
                                        exchange=snapshot.get("exchange"),
                                        market=snapshot.get("market"),
                                        provider_name=provider_name,
                                        source="quote",
                                        fetched_at=snapshot_timestamp,
                                        metadata={
                                            "source": snapshot.get("source"),
                                            "quote_source": quote_source,
                                        },
                                    )
                                except Exception:
                                    logger.warning(
                                        "Failed to upsert instrument metadata for %s",
                                        sym_str,
                                        exc_info=True,
                                    )
                        strategy.on_data(market_event)
                    self._event_bus.drain()

                    # 盯市更新
                    with self._lock:
                        prices = {
                            sym: Decimal(
                                str(
                                    self._latest_quotes.get(str(sym), {}).get(
                                        "price", 0
                                    )
                                )
                            )
                            for sym, _ in self._watchlist
                        }
                    self._portfolio.mark_to_market(prices)
                if self._db is not None:
                    build_current_valuation_snapshot(self._db)
                self._finish_persisted_quote_fetch_run(quote_fetch_run_id, events)
            except Exception as exc:
                if quote_fetch_run_id is not None:
                    failed_symbols = [str(symbol) for symbol, _ in self._watchlist]
                    metadata = self._scheduler_quote_fetch_metadata(
                        provider_status="failed",
                        success_symbols=[],
                        failed_symbols=failed_symbols,
                        error_message=str(exc),
                    )
                    self._finish_scheduler_quote_fetch_run(
                        run_id=quote_fetch_run_id,
                        finished_at=datetime.now().isoformat(),
                        status="failed",
                        success_count=0,
                        failure_count=len(self._watchlist),
                        metadata=metadata,
                        error_message=str(exc),
                    )
                logger.exception("Error in trading loop iteration")

            # 使用 wait 替代 sleep，允许立即停止
            self._stop_requested.wait(timeout=self._config.live_poll_interval)

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
        """信号回调：持久化候选动作并按需推送通知。"""
        direction = "买入" if event.target_weight > 0 else "卖出"
        action_direction = "buy" if event.target_weight > 0 else "sell"
        ac_str = "stock"
        for sym, ac in self._watchlist:
            if sym == event.symbol:
                ac_str = ac.value
                break

        if self._db is not None:
            signal_id = self._db.save_signal_sync(
                timestamp=str(event.timestamp),
                strategy_id=event.strategy_id,
                symbol=str(event.symbol),
                direction=action_direction,
                target_weight=float(event.target_weight),
                price=float(event.price) if event.price else None,
                asset_class=ac_str,
            )
            cycle = build_recommendation_cycle(
                signals=[
                    {
                        "id": signal_id,
                        "timestamp": str(event.timestamp),
                        "strategy_id": event.strategy_id,
                        "symbol": str(event.symbol),
                        "direction": action_direction,
                        "target_weight": float(event.target_weight),
                        "price": float(event.price) if event.price else None,
                        "asset_class": ac_str,
                    }
                ],
                available_cash=(
                    0.0 if self._portfolio is None else float(self._portfolio.cash)
                ),
                existing_positions=(
                    {}
                    if self._portfolio is None
                    else {
                        str(symbol): position
                        for symbol, position in self._portfolio.positions.items()
                    }
                ),
            )
            for task in cycle.tasks:
                self._db.upsert_action_task_sync(
                    source_signal_id=task.source_signal_id,
                    symbol=task.symbol,
                    title=task.title,
                    detail=task.detail,
                    direction=task.direction,
                    urgency=(
                        "high"
                        if task.direction == "buy" and task.target_weight > 0
                        else "medium"
                    ),
                    target_weight=task.target_weight,
                    price=task.price,
                    strategy_id=task.strategy_id,
                    timestamp=task.timestamp,
                    asset_class=task.asset_class,
                )

        if self._notifier is None:
            return

        message = format_signal_message(
            symbol=str(event.symbol),
            direction=direction,
            target_weight=float(event.target_weight),
            price=float(event.price) if event.price else None,
            strategy_id=event.strategy_id,
            asset_class=ac_str,
            timestamp=str(event.timestamp),
        )
        self._notifier.send(title=f"Karkinos 信号: {event.symbol}", message=message)

    def _configured_symbol_set(self, *attribute_names: str):
        """Return a getter for optional symbol lists on runtime config."""

        def getter() -> set[str]:
            values: set[str] = set()
            for name in attribute_names:
                raw = getattr(self._config, name, None)
                if raw is None:
                    continue
                if isinstance(raw, dict):
                    raw = raw.keys()
                if isinstance(raw, str):
                    values.add(raw)
                    continue
                try:
                    values.update(str(item) for item in raw)
                except TypeError:
                    values.add(str(raw))
            return values

        return getter
