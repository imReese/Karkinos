"""TradingScheduler — 后台线程运行交易循环。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from core.event_bus import EventBus
from core.events import SignalEvent
from core.types import AssetClass, Symbol
from data.live import LiveDataFeed
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from execution.gateway import ManualConfirmGateway
from notification.notifier import build_notifier, format_signal_message
from risk.pre_trade import PreTradePolicy, PreTradeRiskManager
from server.bootstrap import build_strategy, create_runtime_context
from server.bridge import EventBusBridge
from server.services.live_context import LiveContextProvider
from server.services.market_hours import is_cn_trading_session
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.trading_controls import TradingControlState

if TYPE_CHECKING:
    from config import ServerConfig

logger = logging.getLogger(__name__)

# A 股交易时段（上午 9:30-11:30，下午 13:00-15:00）
_MORNING_OPEN = time(9, 30)
_MORNING_CLOSE = time(11, 30)
_AFTERNOON_OPEN = time(13, 0)
_AFTERNOON_CLOSE = time(15, 0)


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
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._notifier = notifier
        self._db = db
        self._trading_controls = trading_controls or TradingControlState(db=db)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

        # 运行时状态（由后台线程修改，API 线程读取）
        self._event_bus: EventBus | None = None
        self._portfolio: Portfolio | None = None
        self._watchlist: list[tuple[Symbol, AssetClass]] = []
        self._instruments: dict[Symbol, Instrument] = {}
        self._latest_quotes: dict[str, dict] = {}  # 报价缓存

        # Bug 3: 线程安全锁
        self._lock = threading.Lock()

    def start(self) -> None:
        """启动后台交易线程。"""
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("TradingScheduler started")

    def stop(self) -> None:
        """停止后台交易线程。"""
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
                        sym, start=start_date, end=end_date, asset_class=ac
                    )
                    for market_event in handler:
                        strategy.on_data(market_event)
                    logger.info("策略预热完成: %s (%d bars)", sym, handler.total_bars)
                except Exception:
                    logger.warning("策略预热失败: %s，将跳过", sym, exc_info=True)
        except Exception:
            logger.warning("策略预热整体失败，将跳过", exc_info=True)

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

        # 构建关注列表
        with self._lock:
            self._watchlist = list(runtime.watchlist)
            self._instruments = dict(runtime.instruments)
            self._latest_quotes = {}

        if not self._watchlist:
            logger.warning("No watchlist configured, stopping scheduler")
            self._running.clear()
            return

        if self._db is not None:
            try:
                persisted_quotes = self._db.get_latest_quotes_sync()
                with self._lock:
                    for quote in persisted_quotes:
                        self._latest_quotes[quote["symbol"]] = {
                            "price": float(quote["price"]),
                            "volume": float(quote["volume"]) if quote["volume"] is not None else None,
                            "timestamp": quote["timestamp"],
                            "asset_class": quote["asset_class"],
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
            for inst in self._instruments.values():
                self._portfolio.add_instrument(inst)

        # 实盘安全链路：OrderIntentEvent -> PreTradeRiskManager -> OrderEvent
        # -> ManualConfirmGateway -> SQLite pending confirmation.
        context_provider = LiveContextProvider(
            portfolio_getter=lambda: self.portfolio,
            controls=self._trading_controls,
            blacklist_getter=self._configured_symbol_set("blacklist", "symbol_blacklist"),
            st_symbols_getter=self._configured_symbol_set("st_symbols", "st_blacklist"),
        )
        PreTradeRiskManager(
            self._event_bus,
            context_provider,
            PreTradePolicy(execution_mode="manual"),
            db=self._db,
        )
        ManualConfirmGateway(self._event_bus, db=self._db)

        # 创建策略（使用注册表）
        strategy = build_strategy(self._config, self._event_bus)
        strategy.on_init([sym for sym, _ in self._watchlist])

        # Bug 6: 历史数据预热
        self._warmup_strategy(data_manager, strategy)

        # Bug 2: 重新绑定 bridge 到新 EventBus（复用同一对象）
        self._bridge.rebind(self._event_bus)

        # 订阅信号 → 通知
        if self._notifier is not None:
            self._event_bus.subscribe(SignalEvent, self._on_signal)

        logger.info(
            "Trading loop started, watching %d symbols, interval=%ds",
            len(self._watchlist),
            self._config.live_poll_interval,
        )

        # 主循环
        while self._running.is_set():
            # Bug 7: 非交易时段跳过轮询
            if not self._is_market_open():
                self._running.wait(timeout=30)
                continue

            try:
                events = feed.poll_all(self._watchlist)
                if events:
                    for market_event in events:
                        snapshot = feed.get_last_snapshot(
                            market_event.symbol, market_event.asset_class
                        ) or {}
                        snapshot_timestamp = str(
                            snapshot.get("timestamp") or market_event.timestamp.isoformat()
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
                                "previous_close_date": snapshot.get("previous_close_date"),
                            }
                        if self._db is not None:
                            self._db.save_quote_snapshot_sync(
                                symbol=sym_str,
                                asset_class=market_event.asset_class.value,
                                price=float(market_event.close),
                                volume=float(market_event.volume),
                                timestamp=snapshot_timestamp,
                            )
                            previous_close = snapshot.get("previous_close")
                            previous_close_date = snapshot.get("previous_close_date")
                            if previous_close not in {None, ""} and previous_close_date not in {
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
            except Exception:
                logger.exception("Error in trading loop iteration")

            # 使用 wait 替代 sleep，允许立即停止
            self._running.wait(timeout=self._config.live_poll_interval)

    def _on_signal(self, event: SignalEvent) -> None:
        """信号回调：推送通知。"""
        direction = "买入" if event.target_weight > 0 else "卖出"
        ac_str = "stock"
        for sym, ac in self._watchlist:
            if sym == event.symbol:
                ac_str = ac.value
                break

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
