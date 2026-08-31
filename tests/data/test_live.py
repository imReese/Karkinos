"""测试 LiveDataFeed。"""

from __future__ import annotations

import threading
import time
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


class SequenceSource(DataSource):
    """按资产返回快照的测试 source。"""

    def __init__(self, snapshots):
        self._snapshots = snapshots
        self.calls: list[tuple[str, AssetClass]] = []

    def fetch_bars(self, symbol, start, end, frequency=None, asset_class=None):
        return MagicMock()

    def fetch_ticks(self, symbol, start, end):
        raise NotImplementedError

    def list_symbols(self):
        return []

    def fetch_latest(self, symbol, asset_class=AssetClass.STOCK):
        self.calls.append((str(symbol), asset_class))
        return self._snapshots.get((str(symbol), asset_class))


class RaisingSource(SequenceSource):
    """Source that records calls and raises for latest quote requests."""

    def __init__(self, error: Exception):
        super().__init__({})
        self._error = error

    def fetch_latest(self, symbol, asset_class=AssetClass.STOCK):
        self.calls.append((str(symbol), asset_class))
        raise self._error


class SlowMixedSource(DataSource):
    """One slow fund quote should not block a fast stock quote."""

    def fetch_bars(self, symbol, start, end, frequency=None, asset_class=None):
        return MagicMock()

    def fetch_ticks(self, symbol, start, end):
        raise NotImplementedError

    def list_symbols(self):
        return []

    def fetch_latest(self, symbol, asset_class=AssetClass.STOCK):
        if asset_class == AssetClass.FUND:
            time.sleep(0.2)
            return {"price": 1.1, "volume": None, "timestamp": "2026-01-12"}
        return {"price": 8.76, "volume": 123456.0, "timestamp": "10:30:00"}


class BlockingSource(DataSource):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def fetch_bars(self, symbol, start, end, frequency=None, asset_class=None):
        return MagicMock()

    def fetch_ticks(self, symbol, start, end):
        raise NotImplementedError

    def list_symbols(self):
        return []

    def fetch_latest(self, symbol, asset_class=AssetClass.STOCK):
        self.started.set()
        self.release.wait(timeout=1)
        self.finished.set()
        return {"price": 8.76, "volume": 100.0, "timestamp": "10:30:00"}


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

    def test_poll_latest_rejects_snapshot_without_timestamp(self):
        source = StubSource({"price": 100.0, "volume": 1000.0})
        feed = LiveDataFeed(source, EventBus())

        try:
            assert feed.poll_latest(Symbol("600519"), AssetClass.STOCK) is None
        finally:
            feed.close()

    def test_close_rejects_new_poll_work(self):
        feed = LiveDataFeed(
            StubSource({"price": 100.0, "volume": 1000.0, "timestamp": "10:30:00"}),
            EventBus(),
        )

        feed.close()
        feed.close()

        assert feed.is_closed is True
        with pytest.raises(RuntimeError, match="live data feed is closed"):
            feed.poll_all([(Symbol("600519"), AssetClass.STOCK)])

    def test_close_discards_provider_result_that_returns_after_poll_timeout(self):
        source = BlockingSource()
        bus = EventBus()
        received = []
        bus.subscribe(MarketEvent, received.append)
        feed = LiveDataFeed(source, bus, poll_timeout_seconds=0.01)

        assert feed.poll_all([(Symbol("600519"), AssetClass.STOCK)]) == []
        assert source.started.is_set()
        feed.close()
        source.release.set()
        assert source.finished.wait(timeout=1)

        bus.drain()
        assert received == []
        assert feed.get_last_snapshot(Symbol("600519"), AssetClass.STOCK) is None

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

    def test_poll_all_times_out_slow_symbols_without_blocking_fast_quotes(self):
        """单个慢标的不应阻塞整轮行情刷新。"""
        bus = EventBus()
        feed = LiveDataFeed(SlowMixedSource(), bus, poll_timeout_seconds=0.05)

        started = time.monotonic()
        events = feed.poll_all(
            [
                (Symbol("019999"), AssetClass.FUND),
                (Symbol("600001"), AssetClass.STOCK),
            ]
        )
        elapsed = time.monotonic() - started

        assert elapsed < 0.15
        assert [event.symbol for event in events] == [Symbol("600001")]

    def test_poll_latest_falls_back_to_akshare_for_fund_quotes(self):
        """基金主源失败时应回退到备用行情源。"""
        primary = SequenceSource({("019999", AssetClass.FUND): None})
        fallback = SequenceSource(
            {
                ("019999", AssetClass.FUND): {
                    "price": 1.126,
                    "volume": None,
                    "timestamp": "2026-04-21",
                    "previous_close": 1.12,
                    "previous_close_date": "2026-04-18",
                }
            }
        )
        bus = EventBus()
        feed = LiveDataFeed(primary, bus, fallback_source=fallback)

        event = feed.poll_latest(Symbol("019999"), AssetClass.FUND)

        assert event is not None
        assert float(event.close) == pytest.approx(1.126)
        assert event.timestamp.isoformat() == "2026-04-21T15:00:00"
        assert feed.get_last_snapshot(Symbol("019999"), AssetClass.FUND) == {
            "price": 1.126,
            "volume": None,
            "timestamp": "2026-04-21",
            "previous_close": 1.12,
            "previous_close_date": "2026-04-18",
        }
        assert primary.calls == [("019999", AssetClass.FUND)]
        assert fallback.calls == [("019999", AssetClass.FUND)]

    def test_poll_latest_prefers_fund_capable_fallback_before_primary(self):
        """基金可优先走专用源，避免重复触发主源的可选权限接口。"""
        primary = RaisingSource(RuntimeError("fund_nav permission denied"))
        fallback = SequenceSource(
            {
                ("019999", AssetClass.FUND): {
                    "price": 1.126,
                    "volume": None,
                    "timestamp": "2026-04-21T10:30:00+08:00",
                    "quote_source": "eastmoney_fund_estimate",
                }
            }
        )
        feed = LiveDataFeed(
            primary,
            EventBus(),
            fallback_source=fallback,
            prefer_fallback_asset_classes={AssetClass.FUND},
        )

        event = feed.poll_latest(Symbol("019999"), AssetClass.FUND)

        assert event is not None
        assert float(event.close) == pytest.approx(1.126)
        assert primary.calls == []
        assert fallback.calls == [("019999", AssetClass.FUND)]

    def test_preferred_fund_fallback_still_uses_primary_when_needed(self):
        """备用基金源无结果时仍保留具备 fund_nav 权限的主源能力。"""
        primary = SequenceSource(
            {
                ("019999", AssetClass.FUND): {
                    "price": 1.12,
                    "volume": None,
                    "timestamp": "2026-04-20",
                    "quote_source": "tushare_fund_nav",
                }
            }
        )
        fallback = SequenceSource({})
        feed = LiveDataFeed(
            primary,
            EventBus(),
            fallback_source=fallback,
            prefer_fallback_asset_classes={AssetClass.FUND},
        )

        event = feed.poll_latest(Symbol("019999"), AssetClass.FUND)

        assert event is not None
        assert float(event.close) == pytest.approx(1.12)
        assert fallback.calls == [("019999", AssetClass.FUND)]
        assert primary.calls == [("019999", AssetClass.FUND)]

    def test_poll_latest_falls_back_to_akshare_for_stock_quotes(self):
        """股票主源失败时也应回退到备用行情源。"""
        primary = SequenceSource({("600001", AssetClass.STOCK): None})
        fallback = SequenceSource(
            {
                ("600001", AssetClass.STOCK): {
                    "price": 8.76,
                    "volume": 123456.0,
                    "timestamp": "10:30:00",
                    "display_name": "示例能源",
                }
            }
        )
        bus = EventBus()
        feed = LiveDataFeed(primary, bus, fallback_source=fallback)

        event = feed.poll_latest(Symbol("600001"), AssetClass.STOCK)

        assert event is not None
        assert float(event.close) == pytest.approx(8.76)
        assert feed.get_last_snapshot(Symbol("600001"), AssetClass.STOCK) == {
            "price": 8.76,
            "volume": 123456.0,
            "timestamp": "10:30:00",
            "display_name": "示例能源",
        }
        assert primary.calls == [("600001", AssetClass.STOCK)]
        assert fallback.calls == [("600001", AssetClass.STOCK)]

    def test_poll_latest_falls_back_when_stock_primary_returns_stale_daily_quote(self):
        """股票主源只有旧日线快照时应继续回退到实时备用源。"""
        primary = SequenceSource(
            {
                ("600001", AssetClass.STOCK): {
                    "price": 9.25,
                    "volume": 1000.0,
                    "timestamp": "2000-01-01",
                    "quote_source": "tushare_daily",
                }
            }
        )
        fallback = SequenceSource(
            {
                ("600001", AssetClass.STOCK): {
                    "price": 9.31,
                    "volume": 123456.0,
                    "timestamp": "10:30:00",
                    "quote_source": "akshare",
                    "display_name": "示例能源",
                }
            }
        )
        bus = EventBus()
        feed = LiveDataFeed(primary, bus, fallback_source=fallback)

        event = feed.poll_latest(Symbol("600001"), AssetClass.STOCK)

        assert event is not None
        assert float(event.close) == pytest.approx(9.31)
        assert feed.get_last_snapshot(Symbol("600001"), AssetClass.STOCK) == {
            "price": 9.31,
            "volume": 123456.0,
            "timestamp": "10:30:00",
            "quote_source": "akshare",
            "display_name": "示例能源",
        }
        assert primary.calls == [("600001", AssetClass.STOCK)]
        assert fallback.calls == [("600001", AssetClass.STOCK)]

    def test_poll_latest_falls_back_when_primary_raises(self):
        """主源不支持 fetch_latest 时也应回退到备用行情源。"""
        primary = RaisingSource(
            NotImplementedError("Tushare fetch_latest is not implemented")
        )
        fallback = SequenceSource(
            {
                ("600001", AssetClass.STOCK): {
                    "price": 8.76,
                    "volume": 123456.0,
                    "timestamp": "10:30:00",
                    "display_name": "示例能源",
                }
            }
        )
        bus = EventBus()
        feed = LiveDataFeed(primary, bus, fallback_source=fallback)

        event = feed.poll_latest(Symbol("600001"), AssetClass.STOCK)

        assert event is not None
        assert float(event.close) == pytest.approx(8.76)
        assert primary.calls == [("600001", AssetClass.STOCK)]
        assert fallback.calls == [("600001", AssetClass.STOCK)]
