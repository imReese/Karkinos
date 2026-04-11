"""FeatureEngine — 技术指标特征引擎。"""

from __future__ import annotations

import numpy as np
import pandas as pd


class FeatureEngine:
    """技术指标特征引擎。

    基于 pandas 滚动计算，输出附加列到 DataFrame。
    支持：SMA, EMA, RSI, ATR, 布林带。
    """

    @staticmethod
    def sma(df: pd.DataFrame, column: str = "close", period: int = 20) -> pd.Series:
        """简单移动平均。"""
        return df[column].rolling(window=period).mean()

    @staticmethod
    def ema(df: pd.DataFrame, column: str = "close", period: int = 20) -> pd.Series:
        """指数移动平均。"""
        return df[column].ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(df: pd.DataFrame, column: str = "close", period: int = 14) -> pd.Series:
        """相对强弱指标。"""
        delta = df[column].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """平均真实波幅。"""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    @staticmethod
    def bollinger(
        df: pd.DataFrame,
        column: str = "close",
        period: int = 20,
        num_std: float = 2.0,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """布林带。

        返回 (中轨, 上轨, 下轨)。
        """
        mid = df[column].rolling(window=period).mean()
        std = df[column].rolling(window=period).std()
        upper = mid + num_std * std
        lower = mid - num_std * std
        return mid, upper, lower

    def add_all_features(
        self,
        df: pd.DataFrame,
        sma_periods: tuple[int, ...] = (5, 20, 60),
        ema_periods: tuple[int, ...] = (12, 26),
        rsi_period: int = 14,
        atr_period: int = 14,
        boll_period: int = 20,
    ) -> pd.DataFrame:
        """添加所有常用技术指标到 DataFrame。"""
        df = df.copy()

        for p in sma_periods:
            df[f"sma_{p}"] = self.sma(df, period=p)

        for p in ema_periods:
            df[f"ema_{p}"] = self.ema(df, period=p)

        df["rsi"] = self.rsi(df, period=rsi_period)
        df["atr"] = self.atr(df, period=atr_period)

        mid, upper, lower = self.bollinger(df, period=boll_period)
        df["boll_mid"] = mid
        df["boll_upper"] = upper
        df["boll_lower"] = lower

        return df
