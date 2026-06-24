"""测试 DataManager。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.types import AssetClass, BarFrequency, Symbol
from data.manager import DataManager
from data.source import DataSource


def _make_bars_df(n=30):
    """构造测试用 K 线 DataFrame。"""
    dates = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [100.0 + i for i in range(n)],
            "high": [102.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [101.0 + i for i in range(n)],
            "volume": [10000.0] * n,
        }
    )


# 测试用日期范围（不超过 30 个工作日：2025-01-02 ~ 2025-02-12）
_TEST_START = datetime(2025, 1, 2)
_TEST_END = datetime(2025, 2, 12)


class MockSource(DataSource):
    """测试用 DataSource mock。"""

    def __init__(self, name="mock"):
        self.name = name
        self._df = _make_bars_df()
        self.fetch_count = 0

    def fetch_bars(
        self,
        symbol,
        start,
        end,
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.STOCK,
    ):
        self.fetch_count += 1
        return self._df

    def fetch_ticks(self, symbol, start, end):
        raise NotImplementedError

    def list_symbols(self):
        return [Symbol("600519")]


class FailingSource(MockSource):
    def fetch_bars(
        self,
        symbol,
        start,
        end,
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.STOCK,
    ):
        self.fetch_count += 1
        raise RuntimeError("provider failed")


class EmptySource(MockSource):
    def fetch_bars(
        self,
        symbol,
        start,
        end,
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.STOCK,
    ):
        self.fetch_count += 1
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )


class TestDataManager:
    """DataManager 测试。"""

    def test_cache_miss_fetches_from_source(self):
        """缓存未命中时从 DataSource 拉取。"""
        source = MockSource()
        manager = DataManager({"mock": source}, store=None, default_source="mock")
        handler = manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
        )
        assert handler.total_bars > 0
        assert source.fetch_count == 1

    def test_store_save_on_fetch(self, tmp_path):
        """拉取数据后保存到 DataStore。"""
        source = MockSource()
        from data.store import DataStore

        store = DataStore(str(tmp_path / "store"))
        manager = DataManager({"mock": source}, store=store, default_source="mock")

        manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
        )

        # 验证 store 中有数据
        loaded = store.load_bars(Symbol("600519"), BarFrequency.DAILY)
        assert loaded is not None
        assert len(loaded) > 0

    def test_cache_hit_skips_fetch(self, tmp_path):
        """缓存命中时不调用 DataSource。"""
        source = MockSource()
        from data.store import DataStore

        store = DataStore(str(tmp_path / "store"))
        manager = DataManager({"mock": source}, store=store, default_source="mock")

        # 第一次拉取
        manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
        )
        assert source.fetch_count == 1

        # 第二次应命中缓存
        manager2 = DataManager({"mock": source}, store=store, default_source="mock")
        manager2.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
        )
        # fetch_count 仍为 1（未再调用 fetch_bars）
        assert source.fetch_count == 1

    def test_multi_source_selection(self):
        """多数据源时按 source_name 选择。"""
        source_a = MockSource("akshare")
        source_t = MockSource("tushare")
        manager = DataManager(
            {"akshare": source_a, "tushare": source_t},
            default_source="akshare",
        )

        # 默认使用 akshare
        manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
            source_name="akshare",
        )
        assert source_a.fetch_count == 1
        assert source_t.fetch_count == 0

        # 指定 tushare
        manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
            source_name="tushare",
        )
        assert source_t.fetch_count == 1

    def test_remote_fetch_falls_back_to_akshare_when_primary_fails(self, tmp_path):
        """主数据源失败时应 fallback 到 AKShare，并写回本地权威 store。"""
        from data.store import DataStore

        primary = FailingSource("tushare")
        fallback = MockSource("akshare")
        store = DataStore(str(tmp_path / "store"))
        manager = DataManager(
            {"tushare": primary, "akshare": fallback},
            store=store,
            default_source="tushare",
        )

        handler = manager.get_bars(
            Symbol("600001"),
            start=_TEST_START,
            end=_TEST_END,
            asset_class=AssetClass.STOCK,
        )

        assert handler.total_bars > 0
        assert primary.fetch_count == 1
        assert fallback.fetch_count == 1
        loaded = store.load_bars(Symbol("600001"), BarFrequency.DAILY)
        assert loaded is not None
        assert len(loaded) > 0

    def test_store_meta_records_actual_provider_after_fallback(self, tmp_path):
        """写入缓存的元数据应记录实际成功的数据源，而不是请求的主源。"""
        from data.store import DataStore

        primary = FailingSource("tushare")
        fallback = MockSource("akshare")
        store = DataStore(str(tmp_path / "store"))
        manager = DataManager(
            {"tushare": primary, "akshare": fallback},
            store=store,
            default_source="tushare",
        )

        manager.get_bars(
            Symbol("600001"),
            start=_TEST_START,
            end=_TEST_END,
            asset_class=AssetClass.STOCK,
        )

        meta = store.get_meta(Symbol("600001"), BarFrequency.DAILY)
        assert meta is not None
        assert meta["provider_name"] == "akshare"
        assert meta["data_source"] == "akshare"

    def test_remote_fetch_falls_back_to_akshare_when_primary_returns_empty(self):
        """主数据源返回空结果时也应 fallback 到 AKShare。"""
        primary = EmptySource("tushare")
        fallback = MockSource("akshare")
        manager = DataManager(
            {"tushare": primary, "akshare": fallback},
            default_source="tushare",
        )

        handler = manager.get_bars(
            Symbol("019999"),
            start=_TEST_START,
            end=_TEST_END,
            asset_class=AssetClass.FUND,
        )

        assert handler.total_bars > 0
        assert primary.fetch_count == 1
        assert fallback.fetch_count == 1

    def test_unknown_source_raises(self):
        """未知数据源应抛出 ValueError。"""
        manager = DataManager({"akshare": MockSource()})
        with pytest.raises(ValueError, match="未注册"):
            manager.get_bars(
                Symbol("600519"),
                start=_TEST_START,
                end=_TEST_END,
                source_name="unknown",
            )

    def test_get_instrument_stock(self):
        """创建 A 股 Instrument。"""
        inst = DataManager.get_instrument(Symbol("600519"), AssetClass.STOCK)
        assert inst.asset_class == AssetClass.STOCK
        assert inst.commission_type.value == "stock_a"

    def test_get_instrument_etf(self):
        """创建 ETF Instrument。"""
        inst = DataManager.get_instrument(Symbol("510300"), AssetClass.FUND)
        assert inst.asset_class == AssetClass.FUND
        assert inst.commission_type.value == "fund_etf"

    def test_get_instrument_gold(self):
        """创建黄金 Instrument。"""
        inst = DataManager.get_instrument(Symbol("Au99.99"), AssetClass.GOLD)
        assert inst.asset_class == AssetClass.GOLD

    def test_get_instrument_bond(self):
        """创建债券 Instrument。"""
        inst = DataManager.get_instrument(Symbol("sh010107"), AssetClass.BOND)
        assert inst.asset_class == AssetClass.BOND

    def test_cache_miss_without_remote_refresh_returns_empty_handler(self, tmp_path):
        """禁用远端刷新时，缓存未命中应返回空结果而不是拉取。"""
        source = MockSource()
        from data.store import DataStore

        store = DataStore(str(tmp_path / "store"))
        manager = DataManager({"mock": source}, store=store, default_source="mock")

        handler = manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
            allow_remote_refresh=False,
            degrade_to_cache=True,
        )

        assert handler.total_bars == 0
        assert source.fetch_count == 0

    def test_partial_cache_without_remote_refresh_uses_cached_slice(self, tmp_path):
        """禁用远端刷新时，部分缓存也应直接返回本地已有区间。"""
        source = MockSource()
        from data.store import DataStore

        store = DataStore(str(tmp_path / "store"))
        cached_df = _make_bars_df(n=10)
        store.save_bars(Symbol("600519"), BarFrequency.DAILY, cached_df)
        manager = DataManager({"mock": source}, store=store, default_source="mock")

        handler = manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=_TEST_END,
            allow_remote_refresh=False,
            degrade_to_cache=True,
        )

        assert handler.total_bars == 10
        assert source.fetch_count == 0

    def test_partial_cache_with_recent_meta_skips_remote_refresh(self, tmp_path):
        """开市允许刷新时，若缓存刚更新过则仍应命中节流，不重复拉取。"""
        source = MockSource()
        from data.store import DataStore

        store = DataStore(str(tmp_path / "store"))
        cached_df = _make_bars_df(n=10)
        store.save_bars(Symbol("600519"), BarFrequency.DAILY, cached_df)
        manager = DataManager({"mock": source}, store=store, default_source="mock")

        handler = manager.get_bars(
            Symbol("600519"),
            start=_TEST_START,
            end=datetime.now(),
            allow_remote_refresh=True,
            refresh_ttl_seconds=3600,
            degrade_to_cache=True,
        )

        assert handler.total_bars == 10
        assert source.fetch_count == 0
