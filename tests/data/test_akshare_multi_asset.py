"""测试 AKShareSource 多资产支持。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.types import AssetClass, BarFrequency, Symbol
from data.providers.akshare_source import AKShareSource


@pytest.fixture
def source():
    return AKShareSource()


def _make_stock_df(n=10):
    """构造 A股风格 DataFrame（中文列名）。"""
    dates = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame(
        {
            "日期": dates,
            "开盘": [100.0 + i for i in range(n)],
            "最高": [102.0 + i for i in range(n)],
            "最低": [99.0 + i for i in range(n)],
            "收盘": [101.0 + i for i in range(n)],
            "成交量": [10000.0] * n,
            "成交额": [1000000.0] * n,
        }
    )


def _make_etf_df(n=10):
    """构造 ETF 风格 DataFrame（中文列名，同 A股）。"""
    dates = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame(
        {
            "日期": dates,
            "开盘": [4.0 + i * 0.01 for i in range(n)],
            "最高": [4.1 + i * 0.01 for i in range(n)],
            "最低": [3.9 + i * 0.01 for i in range(n)],
            "收盘": [4.05 + i * 0.01 for i in range(n)],
            "成交量": [50000.0] * n,
            "成交额": [200000.0] * n,
        }
    )


def _make_gold_df(n=10):
    """构造黄金 SGE 风格 DataFrame（英文列名，无成交量）。"""
    dates = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame(
        {
            "date": dates,
            "open": [600.0 + i for i in range(n)],
            "high": [602.0 + i for i in range(n)],
            "low": [599.0 + i for i in range(n)],
            "close": [601.0 + i for i in range(n)],
        }
    )


def _make_bond_df(n=10):
    """构造债券风格 DataFrame（英文列名，无成交量）。"""
    dates = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame(
        {
            "date": dates,
            "open": [100.5 + i * 0.01 for i in range(n)],
            "high": [100.6 + i * 0.01 for i in range(n)],
            "low": [100.4 + i * 0.01 for i in range(n)],
            "close": [100.55 + i * 0.01 for i in range(n)],
        }
    )


class TestAKShareMultiAsset:
    """AKShareSource 多资产 fetch_bars 测试。"""

    @patch("data.providers.akshare_source.AKShareSource.fetch_bars")
    def test_stock_uses_stock_zh_a_hist(self, mock_fetch, source):
        """A 股应调用 stock_zh_a_hist。"""
        # 直接测试内部逻辑
        pass

    def test_stock_column_mapping(self, source):
        """A 股列名映射：中文 → 英文。"""
        from data.providers.akshare_source import _HIST_CONFIG

        config = _HIST_CONFIG[AssetClass.STOCK]
        _, col_map, has_volume = config
        assert col_map["日期"] == "timestamp"
        assert col_map["开盘"] == "open"
        assert col_map["成交量"] == "volume"
        assert has_volume is True

    def test_etf_column_mapping(self, source):
        """ETF 列名映射。"""
        from data.providers.akshare_source import _HIST_CONFIG

        config = _HIST_CONFIG[AssetClass.FUND]
        _, col_map, has_volume = config
        assert col_map["日期"] == "timestamp"
        assert has_volume is True

    def test_gold_column_mapping(self, source):
        """黄金列名映射（英文，无成交量）。"""
        from data.providers.akshare_source import _HIST_CONFIG

        config = _HIST_CONFIG[AssetClass.GOLD]
        _, col_map, has_volume = config
        assert col_map["date"] == "timestamp"
        assert has_volume is False

    def test_bond_column_mapping(self, source):
        """债券列名映射（英文，无成交量）。"""
        from data.providers.akshare_source import _HIST_CONFIG

        config = _HIST_CONFIG[AssetClass.BOND]
        _, col_map, has_volume = config
        assert col_map["date"] == "timestamp"
        assert has_volume is False

    def test_normalize_stock_bars(self, source):
        """A 股 normalize：中文列名正确映射。"""
        from data.providers.akshare_source import _HIST_CONFIG

        col_map = _HIST_CONFIG[AssetClass.STOCK][1]
        df = _make_stock_df()
        result = AKShareSource._normalize_bars(df, col_map, has_volume=True)

        assert "timestamp" in result.columns
        assert "open" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
        assert result["close"].iloc[0] == pytest.approx(101.0)

    def test_normalize_gold_bars_fills_volume(self, source):
        """黄金 normalize：无成交量时自动填充 volume=0。"""
        from data.providers.akshare_source import _HIST_CONFIG

        col_map = _HIST_CONFIG[AssetClass.GOLD][1]
        df = _make_gold_df()
        result = AKShareSource._normalize_bars(df, col_map, has_volume=False)

        assert "volume" in result.columns
        assert (result["volume"] == 0).all()
        assert "amount" in result.columns
        assert (result["amount"] == 0).all()

    def test_normalize_bond_bars_fills_volume(self, source):
        """债券 normalize：无成交量时自动填充 volume=0。"""
        from data.providers.akshare_source import _HIST_CONFIG

        col_map = _HIST_CONFIG[AssetClass.BOND][1]
        df = _make_bond_df()
        result = AKShareSource._normalize_bars(df, col_map, has_volume=False)

        assert "volume" in result.columns
        assert (result["volume"] == 0).all()

    @patch("akshare.stock_zh_a_hist")
    def test_fetch_bars_stock_calls_akshare(self, mock_ak, source):
        """A 股 fetch_bars 调用 akshare.stock_zh_a_hist。"""
        mock_ak.return_value = _make_stock_df()
        start = datetime(2025, 1, 2)
        end = datetime(2025, 3, 1)

        df = source.fetch_bars(
            Symbol("600519"), start, end, asset_class=AssetClass.STOCK
        )

        mock_ak.assert_called_once()
        assert "timestamp" in df.columns

    @patch("akshare.fund_etf_hist_em")
    def test_fetch_bars_etf_calls_akshare(self, mock_ak, source):
        """ETF fetch_bars 调用 akshare.fund_etf_hist_em。"""
        mock_ak.return_value = _make_etf_df()
        start = datetime(2025, 1, 2)
        end = datetime(2025, 3, 1)

        df = source.fetch_bars(
            Symbol("510300"), start, end, asset_class=AssetClass.FUND
        )

        mock_ak.assert_called_once()
        assert "timestamp" in df.columns

    @patch("akshare.spot_hist_sge")
    def test_fetch_bars_gold_calls_akshare(self, mock_ak, source):
        """黄金 fetch_bars 调用 akshare.spot_hist_sge。"""
        mock_ak.return_value = _make_gold_df()
        start = datetime(2025, 1, 2)
        end = datetime(2025, 3, 1)

        df = source.fetch_bars(
            Symbol("Au99.99"), start, end, asset_class=AssetClass.GOLD
        )

        mock_ak.assert_called_once()
        assert "timestamp" in df.columns
        assert "volume" in df.columns

    @patch("akshare.bond_zh_hs_daily")
    def test_fetch_bars_bond_calls_akshare(self, mock_ak, source):
        """债券 fetch_bars 调用 akshare.bond_zh_hs_daily。"""
        mock_ak.return_value = _make_bond_df()
        start = datetime(2025, 1, 2)
        end = datetime(2025, 3, 1)

        df = source.fetch_bars(
            Symbol("sh010107"), start, end, asset_class=AssetClass.BOND
        )

        mock_ak.assert_called_once()
        assert "timestamp" in df.columns

    def test_fetch_bars_unsupported_frequency(self, source):
        """不支持的频率应抛出 NotImplementedError。"""
        with pytest.raises(NotImplementedError):
            source.fetch_bars(
                Symbol("600519"),
                datetime(2025, 1, 2),
                datetime(2025, 3, 1),
                frequency=BarFrequency.WEEKLY,
            )


class TestAKShareFetchLatest:
    """AKShareSource.fetch_latest 测试。"""

    @patch("akshare.stock_zh_a_spot_em")
    def test_fetch_latest_stock(self, mock_ak, source):
        """A 股实时行情快照。"""
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": ["600519", "000001"],
                "最新价": [1850.0, 12.5],
                "成交额": [5000000.0, 3000000.0],
                "时间": ["10:30:00", "10:30:00"],
            }
        )

        result = source.fetch_latest(Symbol("600519"), AssetClass.STOCK)
        assert result is not None
        assert result["price"] == 1850.0

    @patch("akshare.fund_etf_spot_em")
    def test_fetch_latest_etf(self, mock_ak, source):
        """ETF 实时行情快照。"""
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": ["510300", "510050"],
                "最新价": [4.05, 2.80],
                "成交额": [1000000.0, 800000.0],
                "时间": ["10:30:00", "10:30:00"],
            }
        )

        result = source.fetch_latest(Symbol("510300"), AssetClass.FUND)
        assert result is not None
        assert result["price"] == 4.05

    @patch("akshare.stock_zh_a_spot_em")
    def test_fetch_latest_not_found(self, mock_ak, source):
        """找不到 symbol 时返回 None。"""
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": ["000001"],
                "最新价": [12.5],
            }
        )

        result = source.fetch_latest(Symbol("999999"), AssetClass.STOCK)
        assert result is None
