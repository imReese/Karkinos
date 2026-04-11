"""测试 LiveDataFeed。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import AssetClass, Symbol
from data.live import LiveDataFeed
from data.source import DataSource


class StubSource(DataSource):
    """测试用 DataSource stub。"""

    def __init__(self, snapshot=None):
        self._snapshot = snapshot

    def fetch_bars(self, symbol, start, end, frequency=None, asset_class=None):
        return MagicMock()

    def fetch_ticks(self, symbol, start, end):
        raise NotImplementedError

    def list_symbols(self):
        return []

    def fetch_latest(self, symbol, asset_class=AssetClass.STOCK):
        return self._snapshot


class TestLiveDataFeed:
    """LiveDataFeed 测试。"""

    def test_poll_latest_publishes_market_event(self):
        """poll_latest 成功时应发布 MarketEvent。"""
        snapshot = {"price": 1850.0, "volume": 5000000.0, "timestamp": "10:30:00"}
        source = StubSource(snapshot)
        bus = EventBus()
        feed = LiveDataFeed(source, bus)

        events_received = []
        bus.subscribe(MarketEvent, lambda e: events_received.append(e))

        result = feed.poll_latest(Symbol("600519"), AssetClass.STOCK)

        assert result is not None
        assert result.symbol == Symbol("600519")
        assert float(result.close) == pytest.approx(1850.0)

        # publish 入队，需 drain 才触发回调
        bus.drain()
        assert len(events_received) == 1

    def test_poll_latest_returns_none_on_failure(self):
        """fetch_latest 返回 None 时 poll_latest 返回 None。"""
        source = StubSource(None)
        bus = EventBus()
        feed = LiveDataFeed(source, bus)

        result = feed.poll_latest(Symbol("600519"), AssetClass.STOCK)
        assert result is None

    def test_poll_all_returns_events(self):
        """poll_all 轮询多个标的。"""
        snapshot = {"price": 100.0, "volume": 1000.0, "timestamp": "10:30:00"}
        source = StubSource(snapshot)
        bus = EventBus()
        feed = LiveDataFeed(source, bus)

        watchlist = [
            (Symbol("600519"), AssetClass.STOCK),
            (Symbol("510300"), AssetClass.FUND),
        ]
        events = feed.poll_all(watchlist)
        assert len(events) == 2

    def test_poll_all_skips_failures(self):
        """poll_all 在某个标的失败时跳过。"""
        source = StubSource(None)  # 总是返回 None
        bus = EventBus()
        feed = LiveDataFeed(source, bus)

        watchlist = [(Symbol("600519"), AssetClass.STOCK)]
        events = feed.poll_all(watchlist)
        assert len(events) == 0
