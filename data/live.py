"""LiveDataFeed — 实时行情推送（轮询模式）。"""

from __future__ import annotations

import logging
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
    ) -> None:
        self.source = source
        self.fallback_source = fallback_source
        self.event_bus = event_bus
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

    def poll_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> MarketEvent | None:
        """拉取最新行情快照，发布 MarketEvent。"""
        snapshot = self.source.fetch_latest(symbol, asset_class)
        if (
            snapshot is None
            and asset_class == AssetClass.FUND
            and self.fallback_source is not None
            and self.fallback_source is not self.source
        ):
            snapshot = self.fallback_source.fetch_latest(symbol, asset_class)
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
        events: list[MarketEvent] = []
        for symbol, asset_class in watchlist:
            event = self.poll_latest(symbol, asset_class)
            if event is not None:
                events.append(event)
        return events
