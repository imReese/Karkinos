"""LiveDataFeed — 实时行情推送（轮询模式）。"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, Symbol
from data.source import DataSource

logger = logging.getLogger(__name__)


class LiveDataFeed:
    """实时行情推送。

    轮询 DataSource.fetch_latest 获取最新行情，
    发布 MarketEvent 到 EventBus。
    """

    def __init__(
        self,
        source: DataSource,
        event_bus: EventBus,
        fallback_source: DataSource | None = None,
        prefer_fallback_asset_classes: set[AssetClass] | None = None,
        poll_timeout_seconds: float = 8.0,
        max_workers: int = 8,
    ) -> None:
        self.source = source
        self.fallback_source = fallback_source
        self.prefer_fallback_asset_classes = frozenset(
            prefer_fallback_asset_classes or set()
        )
        self.event_bus = event_bus
        self.poll_timeout_seconds = max(float(poll_timeout_seconds), 0.01)
        self._executor = ThreadPoolExecutor(
            max_workers=max(int(max_workers), 1),
            thread_name_prefix="karkinos-live-feed",
        )
        self._lifecycle_lock = threading.Lock()
        self._closed: bool = False
        self._inflight: dict[tuple[Symbol, AssetClass], Future] = {}
        self._last_prices: dict[tuple[Symbol, AssetClass], float] = {}
        self._last_snapshots: dict[tuple[Symbol, AssetClass], dict] = {}

    @staticmethod
    def _snapshot_datetime(snapshot: dict) -> datetime | None:
        raw_timestamp = snapshot.get("timestamp")
        if raw_timestamp in {None, ""}:
            return None

        timestamp = str(raw_timestamp).strip()
        try:
            if len(timestamp) == 10:
                return datetime.fromisoformat(f"{timestamp}T15:00:00")
            if len(timestamp) == 8 and timestamp.count(":") == 2:
                return datetime.combine(
                    datetime.now().date(),
                    datetime.strptime(timestamp, "%H:%M:%S").time(),
                )
            return datetime.fromisoformat(timestamp)
        except ValueError:
            return None

    def close(self) -> None:
        """Reject new polls and cancel work that has not started yet."""

        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            executor = self._executor
        executor.shutdown(wait=False, cancel_futures=True)

    @property
    def is_closed(self) -> bool:
        with self._lifecycle_lock:
            return self._closed

    def _publish_if_open(
        self,
        event: MarketEvent,
        snapshot: dict,
        *,
        price: float,
    ) -> bool:
        with self._lifecycle_lock:
            if self._closed:
                return False
            self.event_bus.publish(event)
            self._last_prices[(event.symbol, event.asset_class)] = price
            self._last_snapshots[(event.symbol, event.asset_class)] = dict(snapshot)
            return True

    def get_last_snapshot(
        self, symbol: Symbol, asset_class: AssetClass = AssetClass.STOCK
    ) -> dict | None:
        with self._lifecycle_lock:
            snapshot = self._last_snapshots.get((symbol, asset_class))
            return None if snapshot is None else dict(snapshot)

    @staticmethod
    def _should_try_fallback_snapshot(
        snapshot: dict | None,
        asset_class: AssetClass,
    ) -> bool:
        if snapshot is None or asset_class != AssetClass.STOCK:
            return False
        quote_source = str(
            snapshot.get("quote_source")
            or snapshot.get("source")
            or snapshot.get("provider")
            or ""
        ).strip()
        if quote_source != "tushare_daily":
            return False
        timestamp = LiveDataFeed._snapshot_datetime(snapshot)
        if timestamp is None:
            return True
        return timestamp.date() < datetime.now().date()

    def _fetch_fallback_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass,
    ) -> dict | None:
        if self.fallback_source is None or self.fallback_source is self.source:
            return None
        try:
            return self.fallback_source.fetch_latest(symbol, asset_class)
        except Exception:
            logger.warning(
                "备用行情源获取实时行情失败: %s (%s)",
                symbol,
                asset_class.value,
                exc_info=True,
            )
            return None

    def _fetch_primary_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass,
    ) -> dict | None:
        try:
            return self.source.fetch_latest(symbol, asset_class)
        except Exception:
            logger.warning(
                "主行情源获取实时行情失败: %s (%s)",
                symbol,
                asset_class.value,
                exc_info=True,
            )
            return None

    def poll_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> MarketEvent | None:
        """拉取最新行情快照，发布 MarketEvent。"""
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("live data feed is closed")
        prefer_fallback = (
            asset_class in self.prefer_fallback_asset_classes
            and self.fallback_source is not None
            and self.fallback_source is not self.source
        )
        if prefer_fallback:
            snapshot = self._fetch_fallback_latest(symbol, asset_class)
            if snapshot is None:
                snapshot = self._fetch_primary_latest(symbol, asset_class)
        else:
            snapshot = self._fetch_primary_latest(symbol, asset_class)
        if (
            not prefer_fallback
            and snapshot is not None
            and self._should_try_fallback_snapshot(snapshot, asset_class)
        ):
            fallback_snapshot = self._fetch_fallback_latest(symbol, asset_class)
            if fallback_snapshot is not None:
                snapshot = fallback_snapshot
        if snapshot is None and not prefer_fallback:
            snapshot = self._fetch_fallback_latest(symbol, asset_class)
        if snapshot is None:
            logger.warning("获取实时行情失败: %s (%s)", symbol, asset_class.value)
            return None

        price = snapshot["price"]
        if price is None or price <= 0:
            return None

        event_timestamp = self._snapshot_datetime(snapshot)
        if event_timestamp is None:
            logger.warning(
                "行情时间戳缺失或无效，拒绝发布: %s (%s)",
                symbol,
                asset_class.value,
            )
            return None

        # 用当前价构造 OHLC（实时快照全部用最新价）
        event = MarketEvent(
            timestamp=event_timestamp,
            symbol=symbol,
            open=Decimal(str(price)),
            high=Decimal(str(price)),
            low=Decimal(str(price)),
            close=Decimal(str(price)),
            volume=Decimal(str(snapshot.get("volume") or 0)),
            frequency=BarFrequency.DAILY,
            asset_class=asset_class,
        )

        if not self._publish_if_open(event, snapshot, price=price):
            return None
        logger.info("实时行情: %s (%s) price=%.2f", symbol, asset_class.value, price)
        return event

    def poll_all(self, watchlist: list[tuple[Symbol, AssetClass]]) -> list[MarketEvent]:
        """轮询所有关注标的最新的行情。"""
        if not watchlist:
            return []

        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("live data feed is closed")
            futures: dict[Future, tuple[Symbol, AssetClass]] = {}
            for symbol, asset_class in watchlist:
                key = (symbol, asset_class)
                previous = self._inflight.get(key)
                if previous is not None and not previous.done():
                    logger.warning(
                        "上一轮行情请求仍在执行，跳过重复请求: %s (%s)",
                        symbol,
                        asset_class.value,
                    )
                    continue
                future = self._executor.submit(
                    self.poll_latest,
                    symbol,
                    asset_class,
                )
                self._inflight[key] = future
                futures[future] = key
                future.add_done_callback(
                    lambda completed, *, inflight_key=key: self._forget_inflight(
                        inflight_key,
                        completed,
                    )
                )
        if not futures:
            return []
        done, pending = wait(futures, timeout=self.poll_timeout_seconds)

        for future in pending:
            symbol, asset_class = futures[future]
            future.cancel()
            logger.warning(
                "实时行情轮询超时，跳过本轮: %s (%s)",
                symbol,
                asset_class.value,
            )

        events: list[MarketEvent] = []
        for future, _context in futures.items():
            if future not in done:
                continue
            try:
                event = future.result()
            except Exception:
                symbol, asset_class = futures[future]
                logger.warning(
                    "实时行情轮询异常，跳过本轮: %s (%s)",
                    symbol,
                    asset_class.value,
                    exc_info=True,
                )
                continue
            if event is not None:
                events.append(event)
        return events

    def _forget_inflight(
        self,
        key: tuple[Symbol, AssetClass],
        completed: Future,
    ) -> None:
        with self._lifecycle_lock:
            if self._inflight.get(key) is completed:
                self._inflight.pop(key, None)
