"""FeatureEngine 单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data.features import FeatureEngine


@pytest.fixture
def price_df() -> pd.DataFrame:
    """生成测试用行情 DataFrame。"""
    np.random.seed(42)
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame(
        {
            "open": close - np.random.rand(n) * 0.5,
            "high": close + np.abs(np.random.randn(n)) * 0.5,
            "low": close - np.abs(np.random.randn(n)) * 0.5,
            "close": close,
            "volume": np.random.randint(1000, 10000, n).astype(float),
        }
    )


class TestFeatureEngine:
    def test_sma(self, price_df: pd.DataFrame):
        engine = FeatureEngine()
        sma5 = engine.sma(price_df, period=5)
        # SMA(5) 前 4 个值为 NaN
        assert pd.isna(sma5.iloc[:4]).all()
        assert not pd.isna(sma5.iloc[4])
        # 第 5 个值 = 前 5 个 close 的平均
        expected = price_df["close"].iloc[:5].mean()
        assert abs(sma5.iloc[4] - expected) < 1e-10

    def test_ema(self, price_df: pd.DataFrame):
        engine = FeatureEngine()
        ema12 = engine.ema(price_df, period=12)
        # EMA 应没有 NaN（从第一个值开始）
        assert not pd.isna(ema12).any()

    def test_rsi(self, price_df: pd.DataFrame):
        engine = FeatureEngine()
        rsi = engine.rsi(price_df, period=14)
        # RSI 在有效范围内
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_atr(self, price_df: pd.DataFrame):
        engine = FeatureEngine()
        atr = engine.atr(price_df, period=14)
        valid = atr.dropna()
        assert (valid > 0).all()

    def test_bollinger(self, price_df: pd.DataFrame):
        engine = FeatureEngine()
        mid, upper, lower = engine.bollinger(price_df, period=20)
        # 上轨 > 中轨 > 下轨
        valid_idx = mid.dropna().index
        assert (upper[valid_idx] >= mid[valid_idx]).all()
        assert (lower[valid_idx] <= mid[valid_idx]).all()

    def test_add_all_features(self, price_df: pd.DataFrame):
        engine = FeatureEngine()
        result = engine.add_all_features(price_df)
        assert "sma_5" in result.columns
        assert "sma_20" in result.columns
        assert "ema_12" in result.columns
        assert "rsi" in result.columns
        assert "atr" in result.columns
        assert "boll_mid" in result.columns
        assert len(result) == len(price_df)

    def test_cross_sectional_rank(self):
        engine = FeatureEngine()
        panel = pd.DataFrame(
            {
                "A": [10.0, 50.0],
                "B": [20.0, 30.0],
                "C": [30.0, 10.0],
            }
        )
        ranks = engine.cross_sectional_rank(panel, ascending=True, pct=False)
        assert ranks.loc[0, "A"] == 1.0
        assert ranks.loc[0, "B"] == 2.0
        assert ranks.loc[0, "C"] == 3.0
        assert ranks.loc[1, "C"] == 1.0
        assert ranks.loc[1, "A"] == 3.0

        pct_ranks = engine.cross_sectional_rank(panel, ascending=True, pct=True)
        assert pct_ranks.loc[0, "A"] == pytest.approx(1.0 / 3.0)
        assert pct_ranks.loc[0, "C"] == 1.0

    def test_cross_sectional_zscore(self):
        engine = FeatureEngine()
        panel = pd.DataFrame(
            {
                "A": [10.0, 20.0],
                "B": [20.0, 20.0],
                "C": [30.0, 20.0],
            }
        )
        z = engine.cross_sectional_zscore(panel)
        # 第一行均值 20，标准差 10
        assert z.loc[0, "A"] < 0
        assert z.loc[0, "B"] == pytest.approx(0.0)
        assert z.loc[0, "C"] > 0
        # 方差为0时填充为 NaN
        assert pd.isna(z.loc[1, "A"])

    def test_cross_sectional_top_k(self):
        engine = FeatureEngine()
        scores = pd.DataFrame(
            {
                "A": [10.0, 90.0],
                "B": [50.0, 10.0],
                "C": [80.0, 40.0],
            }
        )
        top2 = engine.cross_sectional_top_k(scores, k=2, ascending=False)
        assert top2.loc[0, "C"] and top2.loc[0, "B"]
        assert not top2.loc[0, "A"]
        assert top2.loc[1, "A"] and top2.loc[1, "C"]
        assert not top2.loc[1, "B"]

    def test_rolling_percentile(self):
        engine = FeatureEngine()
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        pct = engine.rolling_percentile(s, window=3)
        assert pd.isna(pct.iloc[0])
        assert pd.isna(pct.iloc[1])
        # [1, 2, 3] 中 3 是最大值 -> 1.0
        assert pct.iloc[2] == 1.0
        # [2, 3, 4] 中 4 是最大值 -> 1.0
        assert pct.iloc[3] == 1.0

    def test_risk_adjusted_momentum(self):
        engine = FeatureEngine()
        prices = pd.DataFrame(
            {
                "A": [10.0, 11.0, 12.0, 13.0, 14.0],
                "B": [10.0, 9.0, 8.0, 7.0, 6.0],
            }
        )
        score = engine.risk_adjusted_momentum(prices, return_window=2, vol_window=2)
        assert len(score) == len(prices)
        # 上涨标的应该有正得分，下跌标的为负
        valid_idx = score.dropna().index
        if len(valid_idx) > 0:
            assert (score.loc[valid_idx, "A"] > 0).all()
            assert (score.loc[valid_idx, "B"] < 0).all()
