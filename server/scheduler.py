"""TradingScheduler — 后台线程运行交易循环。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import AssetClass, Symbol
from data.live import LiveDataFeed
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from notification.notifier import build_notifier, format_signal_message
from server.bridge import EventBusBridge

if TYPE_CHECKING:
    from config import ServerConfig

logger = logging.getLogger(__name__)

# 配置中的 asset_class 字符串 → AssetClass 枚举
_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}

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
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._notifier = notifier
        self._db = db
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
        now = datetime.now().time()
        return (
            _MORNING_OPEN <= now <= _MORNING_CLOSE
            or _AFTERNOON_OPEN <= now <= _AFTERNOON_CLOSE
        )

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
        from data.manager import DataManager, build_sources

        # 初始化组件
        self._event_bus = EventBus()
        sources = build_sources(
            data_source=self._config.data_source,
            tushare_token=self._config.tushare_token,
        )
        source = sources.get(self._config.data_source, sources["akshare"])
        feed = LiveDataFeed(source, self._event_bus)
        store = None
        try:
            from data.store import DataStore

            store = DataStore()
        except Exception:
            pass

        data_manager = DataManager(
            sources=sources,
            store=store,
            default_source=self._config.data_source,
        )

        # 构建关注列表
        with self._lock:
            self._watchlist = []
            self._instruments = {}
            for asset_cfg in self._config.assets:
                sym = Symbol(asset_cfg["symbol"])
                ac = _ASSET_CLASS_MAP.get(asset_cfg["asset_class"], AssetClass.STOCK)
                self._watchlist.append((sym, ac))
                instrument = DataManager.get_instrument(sym, ac)
                self._instruments[sym] = instrument

        if not self._watchlist:
            logger.warning("No watchlist configured, stopping scheduler")
            self._running.clear()
            return

        # 创建组合
        with self._lock:
            self._portfolio = Portfolio(
                self._event_bus,
                initial_cash=self._config.initial_cash,
            )
            for inst in self._instruments.values():
                self._portfolio.add_instrument(inst)

            # 恢复历史入金（调度器重启时重新应用）
            if self._db:
                try:
                    total_deposits = self._db.get_total_deposits_sync()
                    if total_deposits > 0:
                        self._portfolio.deposit(Decimal(str(total_deposits)))
                        logger.info("恢复历史入金: %.2f", total_deposits)
                except Exception:
                    logger.warning("恢复历史入金失败，将跳过", exc_info=True)

        # 创建策略（使用注册表）
        import strategy.examples  # noqa: F401 — 触发注册
        from strategy.registry import StrategyRegistry

        strategy_info = StrategyRegistry.get(self._config.strategy)
        if strategy_info:
            param_names = {p["name"] for p in strategy_info["params"]}
            strategy_kwargs = {
                k: v for k, v in self._config.__dict__.items() if k in param_names
            }
        else:
            strategy_kwargs = {
                "short_period": self._config.short_period,
                "long_period": self._config.long_period,
            }

        strategy = StrategyRegistry.create(
            self._config.strategy, self._event_bus, **strategy_kwargs
        )
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
                        # 更新报价缓存
                        sym_str = str(market_event.symbol)
                        with self._lock:
                            self._latest_quotes[sym_str] = {
                                "price": float(market_event.close),
                                "volume": float(market_event.volume),
                                "timestamp": market_event.timestamp.isoformat(),
                            }
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
        self._notifier.send(title=f"MyQuant 信号: {event.symbol}", message=message)
