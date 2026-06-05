"""LiveDataFeed — 实时行情推送（轮询模式）。"""

from __future__ import annotations

import logging
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
        poll_timeout_seconds: float = 8.0,
        max_workers: int = 8,
    ) -> None:
        self.source = source
        self.fallback_source = fallback_source
        self.event_bus = event_bus
        self.poll_timeout_seconds = max(float(poll_timeout_seconds), 0.1)
        self._executor = ThreadPoolExecutor(
            max_workers=max(int(max_workers), 1),
            thread_name_prefix="karkinos-live-feed",
        )
        self._last_prices: dict[tuple[Symbol, AssetClass], float] = {}
        self._last_snapshots: dict[tuple[Symbol, AssetClass], dict] = {}

    @staticmethod
    def _snapshot_datetime(snapshot: dict) -> datetime:
        raw_timestamp = snapshot.get("timestamp")
        if raw_timestamp in {None, ""}:
            return datetime.now()

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
            return datetime.now()

    def get_last_snapshot(
        self, symbol: Symbol, asset_class: AssetClass = AssetClass.STOCK
    ) -> dict | None:
        return self._last_snapshots.get((symbol, asset_class))

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

    def poll_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> MarketEvent | None:
        """拉取最新行情快照，发布 MarketEvent。"""
        try:
            snapshot = self.source.fetch_latest(symbol, asset_class)
        except Exception:
            logger.warning(
                "主行情源获取实时行情失败: %s (%s)",
                symbol,
                asset_class.value,
                exc_info=True,
            )
            snapshot = None
        if (
            snapshot is not None
            and self._should_try_fallback_snapshot(snapshot, asset_class)
        ):
            fallback_snapshot = self._fetch_fallback_latest(symbol, asset_class)
            if fallback_snapshot is not None:
                snapshot = fallback_snapshot
        if snapshot is None:
            snapshot = self._fetch_fallback_latest(symbol, asset_class)
        if snapshot is None:
            logger.warning("获取实时行情失败: %s (%s)", symbol, asset_class.value)
            return None

        price = snapshot["price"]
        if price is None or price <= 0:
            return None

        event_timestamp = self._snapshot_datetime(snapshot)

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

        self.event_bus.publish(event)
        self._last_prices[(symbol, asset_class)] = price
        self._last_snapshots[(symbol, asset_class)] = dict(snapshot)
        logger.info("实时行情: %s (%s) price=%.2f", symbol, asset_class.value, price)
        return event

    def poll_all(self, watchlist: list[tuple[Symbol, AssetClass]]) -> list[MarketEvent]:
        """轮询所有关注标的最新的行情。"""
        if not watchlist:
            return []

        futures: dict[Future, tuple[Symbol, AssetClass]] = {
            self._executor.submit(self.poll_latest, symbol, asset_class): (
                symbol,
                asset_class,
            )
            for symbol, asset_class in watchlist
        }
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
