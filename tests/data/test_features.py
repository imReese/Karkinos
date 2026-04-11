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
