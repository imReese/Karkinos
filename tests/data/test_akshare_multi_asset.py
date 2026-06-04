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
    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_fetch_bars_etf_calls_akshare(self, mock_name_map, mock_ak, source):
        """ETF fetch_bars 调用 akshare.fund_etf_hist_em。"""
        mock_name_map.return_value = {}
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

    def test_call_with_retry_ignores_proxy_env_by_default(self, monkeypatch, source):
        """行情源默认不应继承本地代理，避免坏代理拖垮补数。"""
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
        observed: dict[str, str | None] = {}

        def fake_provider():
            import os

            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            return "ok"

        assert source._call_with_retry(fake_provider) == "ok"
        assert observed == {"HTTP_PROXY": None, "HTTPS_PROXY": None}

    def test_call_with_retry_can_keep_proxy_env_when_enabled(self, monkeypatch, source):
        """显式开启代理时保留 provider 代理环境。"""
        monkeypatch.setenv("KARKINOS_PROVIDER_USE_PROXY", "true")
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
        observed: dict[str, str | None] = {}

        def fake_provider():
            import os

            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            return "ok"

        assert source._call_with_retry(fake_provider) == "ok"
        assert observed["HTTP_PROXY"] == "http://127.0.0.1:7897"

    def test_open_end_fund_name_map_ignores_proxy_env_by_default(
        self, monkeypatch, source
    ):
        """基金名称表直连 AKShare 时也不应继承坏代理。"""
        import akshare as ak

        source._open_end_fund_name_map.cache_clear()
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
        observed: dict[str, str | None] = {}

        def fake_fund_name_em():
            import os

            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            return pd.DataFrame(
                [{"基金简称": "永赢先进制造智选混合C", "基金代码": "018125"}]
            )

        monkeypatch.setattr(ak, "fund_name_em", fake_fund_name_em)

        assert source._open_end_fund_name_map() == {"永赢先进制造智选混合C": "018125"}
        assert observed["HTTP_PROXY"] is None
        source._open_end_fund_name_map.cache_clear()


class TestAKShareFetchLatest:
    """AKShareSource.fetch_latest 测试。"""

    @patch("akshare.stock_zh_a_spot_em")
    def test_fetch_latest_stock(self, mock_ak, source):
        """A 股实时行情快照。"""
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": ["600519", "000001"],
                "名称": ["贵州茅台", "平安银行"],
                "最新价": [1850.0, 12.5],
                "成交额": [5000000.0, 3000000.0],
                "时间": ["10:30:00", "10:30:00"],
            }
        )

        result = source.fetch_latest(Symbol("600519"), AssetClass.STOCK)
        assert result is not None
        assert result["price"] == 1850.0
        assert result["display_name"] == "贵州茅台"

    @patch("akshare.fund_etf_spot_em")
    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_fetch_latest_etf(self, mock_name_map, mock_ak, source):
        """ETF 实时行情快照。"""
        mock_name_map.return_value = {}
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": ["510300", "510050"],
                "名称": ["沪深300ETF", "上证50ETF"],
                "最新价": [4.05, 2.80],
                "成交额": [1000000.0, 800000.0],
                "时间": ["10:30:00", "10:30:00"],
            }
        )

        result = source.fetch_latest(Symbol("510300"), AssetClass.FUND)
        assert result is not None
        assert result["price"] == 4.05
        assert result["display_name"] == "沪深300ETF"

    @patch("akshare.fund_open_fund_daily_em")
    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_fetch_latest_open_end_fund_by_name(self, mock_name_map, mock_daily, source):
        """开放式基金可按基金简称解析净值。"""
        mock_name_map.return_value = {"永赢先进制造智选混合C": "018124"}
        mock_daily.return_value = pd.DataFrame(
            {
                "基金代码": ["018124"],
                "基金简称": ["永赢先进制造智选混合C"],
                "2026-04-18-单位净值": [1.023],
                "2026-04-18-累计净值": [1.023],
            }
        )

        result = source.fetch_latest(Symbol("永赢先进制造智选混合C"), AssetClass.FUND)

        assert result is not None
        assert result["price"] == 1.023
        assert result["timestamp"] == "2026-04-18"
        assert result["display_name"] == "永赢先进制造智选混合C"

    @patch("akshare.fund_etf_spot_em")
    @patch("akshare.fund_open_fund_daily_em")
    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_fetch_latest_open_end_fund_by_code(
        self, mock_name_map, mock_daily, mock_etf, source
    ):
        """开放式基金代码应优先走净值接口，而不是 ETF 行情接口。"""
        mock_name_map.return_value = {"永赢先进制造智选混合发起C": "018125"}
        mock_daily.return_value = pd.DataFrame(
            {
                "基金代码": ["018125"],
                "基金简称": ["永赢先进制造智选混合发起C"],
                "2026-04-22-单位净值": [2.2503],
                "2026-04-22-累计净值": [2.2503],
                "2026-04-21-单位净值": [2.2606],
                "2026-04-21-累计净值": [2.2606],
                "日增长值": [-0.0103],
                "日增长率": [-0.46],
            }
        )

        result = source.fetch_latest(Symbol("018125"), AssetClass.FUND)

        assert result is not None
        assert result["price"] == 2.2503
        assert result["timestamp"] == "2026-04-22"
        assert result["display_name"] == "永赢先进制造智选混合发起C"
        assert result["previous_close"] == 2.2606
        assert result["previous_close_date"] == "2026-04-21"
        assert result["day_change_value"] == pytest.approx(-0.0103)
        assert result["day_change_pct"] == pytest.approx(-0.0046)
        mock_daily.assert_called_once()
        mock_etf.assert_not_called()

    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_resolve_open_end_fund_code_accepts_alias_name(self, mock_name_map, source):
        """缺少“发起/发起式”的输入别名也应解析到标准基金代码。"""
        mock_name_map.return_value = {
            "永赢先进制造智选混合发起C": "018125",
            "融通科技臻选混合发起式C": "026539",
        }

        assert source._resolve_open_end_fund_code(Symbol("永赢先进制造智选混合C")) == "018125"
        assert source._resolve_open_end_fund_code(Symbol("融通科技臻选混合C")) == "026539"

    @patch("akshare.stock_zh_a_spot_em")
    def test_fetch_latest_stock_includes_previous_close_and_change(
        self, mock_ak, source
    ):
        """A股最新行情应包含昨收、涨跌额和涨跌幅。"""
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": ["601985"],
                "名称": ["中国核电"],
                "最新价": [8.76],
                "昨收": [8.65],
                "涨跌额": [0.11],
                "涨跌幅": [1.27],
                "成交量": [123456.0],
                "成交额": [1081488.0],
                "时间": ["10:30:00"],
            }
        )

        result = source.fetch_latest(Symbol("601985"), AssetClass.STOCK)

        assert result is not None
        assert result["price"] == 8.76
        assert result["previous_close"] == 8.65
        assert result["change"] == 0.11
        assert result["change_percent"] == pytest.approx(0.0127)
        assert result["previous_close_date"] is not None
        assert result["display_name"] == "中国核电"

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
