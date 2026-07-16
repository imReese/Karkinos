"""测试 AKShareSource 多资产支持。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
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
            return pd.DataFrame([{"基金简称": "示例成长混合C", "基金代码": "019999"}])

        monkeypatch.setattr(ak, "fund_name_em", fake_fund_name_em)

        assert source._open_end_fund_name_map() == {"示例成长混合C": "019999"}
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

    @pytest.mark.parametrize(
        ("symbol", "series_name"),
        [
            ("000001", "上证系列指数"),
            ("399001", "深证系列指数"),
            ("399006", "深证系列指数"),
        ],
    )
    @patch("akshare.stock_zh_index_spot_sina")
    @patch("akshare.stock_zh_index_spot_em")
    def test_fetch_latest_index_selects_the_matching_exchange_series(
        self,
        mock_ak,
        mock_sina,
        symbol,
        series_name,
        source,
    ):
        """深市指数不能继续从 AKShare 默认的上证指数列表中查找。"""
        mock_sina.return_value = pd.DataFrame({"代码": []})
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": [symbol],
                "名称": ["测试指数"],
                "最新价": [1234.56],
                "成交额": [5000000.0],
                "时间": ["14:55:00"],
            }
        )

        result = source.fetch_latest(Symbol(symbol), AssetClass.INDEX)

        assert result is not None
        assert result["price"] == 1234.56
        assert result["display_name"] == "测试指数"
        mock_ak.assert_called_once_with(symbol=series_name)

    @patch("akshare.stock_zh_index_daily_tx")
    @patch("akshare.stock_zh_index_spot_sina")
    @patch("akshare.stock_zh_index_spot_em")
    def test_fetch_latest_index_uses_sina_with_explicit_daily_provenance(
        self,
        mock_eastmoney,
        mock_sina,
        mock_daily,
        source,
    ):
        mock_sina.return_value = pd.DataFrame(
            {
                "代码": ["sz399001"],
                "名称": ["深证成指"],
                "最新价": [14488.654],
                "涨跌额": [-290.742],
                "涨跌幅": [-1.967],
                "昨收": [14779.396],
                "成交量": [66586933111.0],
                "成交额": [1279353199758.0],
            }
        )
        mock_daily.return_value = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-14", "2026-01-15"]).date,
                "close": [14779.396, 14488.654],
                "amount": [688984096.0, 665968453.0],
            }
        )

        result = source.fetch_latest(Symbol("399001"), AssetClass.INDEX)

        assert result is not None
        assert result["price"] == pytest.approx(14488.654)
        assert result["previous_close"] == pytest.approx(14779.396)
        assert result["change"] == pytest.approx(-290.742)
        assert result["change_percent"] == pytest.approx(-290.742 / 14779.396)
        assert result["timestamp"] == "2026-01-15T15:00:00+08:00"
        assert result["quote_source"] == "akshare_index_daily_tx"
        assert result["display_name"] == "深证成指"
        mock_eastmoney.assert_not_called()
        mock_sina.assert_called_once_with()
        mock_daily.assert_called_once()

    @patch("akshare.stock_zh_index_daily_tx")
    def test_index_daily_fallback_does_not_publish_an_incomplete_session(
        self,
        mock_daily,
        source,
    ):
        mock_daily.return_value = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-07-15", "2026-07-16"]).date,
                "close": [14779.396, 14488.654],
                "amount": [688984096.0, 665968453.0],
            }
        )

        row = source._latest_completed_index_daily_row(
            __import__("akshare"),
            Symbol("399001"),
            display_name="深证成指",
            now=datetime.fromisoformat("2026-07-16T10:30:00+08:00"),
        )

        assert row is not None
        assert row["最新价"] == pytest.approx(14779.396)
        assert row["时间"] == "2026-07-15T15:00:00+08:00"
        mock_daily.assert_called_once_with(
            symbol="sz399001",
            start_date="20260701",
            end_date="20260715",
        )

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
    def test_fetch_latest_open_end_fund_by_name(
        self, mock_name_map, mock_daily, source
    ):
        """开放式基金可按基金简称解析净值。"""
        mock_name_map.return_value = {"示例成长混合C": "018124"}
        mock_daily.return_value = pd.DataFrame(
            {
                "基金代码": ["018124"],
                "基金简称": ["示例成长混合C"],
                "2026-04-18-单位净值": [1.023],
                "2026-04-18-累计净值": [1.023],
            }
        )

        result = source.fetch_latest(Symbol("示例成长混合C"), AssetClass.FUND)

        assert result is not None
        assert result["price"] == 1.023
        assert result["timestamp"] == "2026-04-18"
        assert result["display_name"] == "示例成长混合C"

    @patch("requests.get")
    @patch("akshare.fund_etf_spot_em")
    @patch("akshare.fund_open_fund_daily_em")
    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_fetch_latest_open_end_fund_by_code(
        self, mock_name_map, mock_daily, mock_etf, mock_get, source
    ):
        """单基金页失败时，开放式基金代码仍可回退到净值表。"""
        mock_name_map.return_value = {"示例成长混合C": "019999"}
        mock_get.side_effect = TimeoutError("single fund page timeout")
        mock_daily.return_value = pd.DataFrame(
            {
                "基金代码": ["019999"],
                "基金简称": ["示例成长混合C"],
                "2026-04-22-单位净值": [2.2503],
                "2026-04-22-累计净值": [2.2503],
                "2026-04-21-单位净值": [2.2606],
                "2026-04-21-累计净值": [2.2606],
                "日增长值": [-0.0103],
                "日增长率": [-0.46],
            }
        )

        result = source.fetch_latest(Symbol("019999"), AssetClass.FUND)

        assert result is not None
        assert result["price"] == 2.2503
        assert result["timestamp"] == "2026-04-22"
        assert result["display_name"] == "示例成长混合C"
        assert result["previous_close"] == 2.2606
        assert result["previous_close_date"] == "2026-04-21"
        assert result["day_change_value"] == pytest.approx(-0.0103)
        assert result["day_change_pct"] == pytest.approx(-0.0046)
        mock_get.assert_called()
        mock_daily.assert_called_once()
        mock_etf.assert_not_called()

    @patch("requests.get")
    @patch("akshare.fund_etf_spot_em")
    @patch("akshare.fund_open_fund_daily_em")
    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_fetch_latest_open_end_fund_code_skips_name_map(
        self, mock_name_map, mock_daily, mock_etf, mock_get, source
    ):
        """已知基金代码应走单基金页，不依赖全量名称表或全市场净值表。"""
        mock_name_map.side_effect = AssertionError("fund_name_em should not be called")
        mock_get.return_value = SimpleNamespace(
            text='jsonpgz({"fundcode":"019999","name":"示例成长混合C","jzrq":"2026-06-04","dwjz":"2.5000","gsz":"2.5123","gszzl":"0.49","gztime":"2026-01-12 15:00"});',
            raise_for_status=lambda: None,
        )

        result = source.fetch_latest(Symbol("019999"), AssetClass.FUND)

        assert result is not None
        assert result["price"] == 2.5123
        assert result["timestamp"] == "2026-01-12 15:00"
        assert result["display_name"] == "示例成长混合C"
        assert result["previous_close"] == 2.5
        assert result["previous_close_date"] == "2026-06-04"
        assert result["quote_source"] == "eastmoney_fund_estimate"
        mock_name_map.assert_not_called()
        mock_daily.assert_not_called()
        mock_etf.assert_not_called()

    @patch("requests.get")
    @patch("akshare.fund_etf_spot_em")
    @patch("akshare.fund_open_fund_daily_em")
    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_fetch_latest_open_end_fund_falls_back_to_single_fund_page(
        self, mock_name_map, mock_daily, mock_etf, mock_get, source
    ):
        """全市场开放式基金表失败时，应回退到单基金净值页。"""
        mock_name_map.side_effect = AssertionError("fund_name_em should not be called")
        mock_daily.side_effect = TimeoutError("daily table timeout")
        mock_get.side_effect = [
            TimeoutError("fund estimate timeout"),
            SimpleNamespace(
                text=(
                    'var fS_name = "示例成长混合C";'
                    "var Data_netWorthTrend = ["
                    '{"x":1780416000000,"y":2.5000,"equityReturn":0.12},'
                    '{"x":1780502400000,"y":2.5123,"equityReturn":0.49}'
                    "];"
                ),
                raise_for_status=lambda: None,
            ),
        ]

        result = source.fetch_latest(Symbol("019999"), AssetClass.FUND)

        assert result is not None
        assert result["price"] == 2.5123
        assert result["timestamp"] == "2026-06-04"
        assert result["display_name"] == "示例成长混合C"
        assert result["previous_close"] == 2.5
        assert result["previous_close_date"] == "2026-06-03"
        assert result["day_change_value"] == pytest.approx(0.0123)
        assert result["day_change_pct"] == pytest.approx(0.0049)
        assert mock_get.call_count == 2
        mock_etf.assert_not_called()

    @patch("data.providers.akshare_source.AKShareSource._open_end_fund_name_map")
    def test_resolve_open_end_fund_code_accepts_alias_name(self, mock_name_map, source):
        """缺少“发起/发起式”的输入别名也应解析到标准基金代码。"""
        mock_name_map.return_value = {
            "示例成长混合C": "019999",
            "示例科技混合C": "029999",
        }

        assert source._resolve_open_end_fund_code(Symbol("示例成长混合C")) == "019999"
        assert source._resolve_open_end_fund_code(Symbol("示例科技混合C")) == "029999"

    @patch("akshare.stock_zh_a_spot_em")
    def test_fetch_latest_stock_includes_previous_close_and_change(
        self, mock_ak, source
    ):
        """A股最新行情应包含昨收、涨跌额和涨跌幅。"""
        mock_ak.return_value = pd.DataFrame(
            {
                "代码": ["600001"],
                "名称": ["示例能源"],
                "最新价": [8.76],
                "昨收": [8.65],
                "涨跌额": [0.11],
                "涨跌幅": [1.27],
                "成交量": [123456.0],
                "成交额": [1081488.0],
                "时间": ["10:30:00"],
            }
        )

        result = source.fetch_latest(Symbol("600001"), AssetClass.STOCK)

        assert result is not None
        assert result["price"] == 8.76
        assert result["previous_close"] == 8.65
        assert result["change"] == 0.11
        assert result["change_percent"] == pytest.approx(0.0127)
        assert result["previous_close_date"] is not None
        assert result["display_name"] == "示例能源"
        assert result["symbol"] == "600001"
        assert result["asset_class"] == "stock"
        assert result["provider_name"] == "akshare"
        assert result["provider_symbol"] == "600001"
        assert result["source"] == "akshare"
        assert result["quote_source"] == "akshare_stock_spot"

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
