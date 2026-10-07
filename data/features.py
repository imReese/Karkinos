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

    @staticmethod
    def cross_sectional_rank(
        df: pd.DataFrame, ascending: bool = True, pct: bool = True
    ) -> pd.DataFrame:
        """计算截面排名（每一行各资产之间的相对排名）。

        Args:
            df: 行索引为时间，列为各个资产/标的的指标值矩阵。
            ascending: 是否升序排列（True 则数值越小排名越靠前）。
            pct: 是否返回百分比排名（0.0 ~ 1.0）。
        """
        return df.rank(axis=1, ascending=ascending, pct=pct)

    @staticmethod
    def cross_sectional_zscore(df: pd.DataFrame) -> pd.DataFrame:
        """计算截面 Z-Score 标准化（每一行跨资产去均值并除以标准差）。"""
        mean = df.mean(axis=1)
        std = df.std(axis=1).replace(0, np.nan)
        return df.sub(mean, axis=0).div(std, axis=0)

    @staticmethod
    def cross_sectional_top_k(
        scores: pd.DataFrame, k: int, ascending: bool = False
    ) -> pd.DataFrame:
        """截面 Top-K 选股掩码。

        Args:
            scores: 资产评分矩阵（行=时间，列=资产）。
            k: 选取资产数量。
            ascending: False 为取分数最高的前 k 个，True 为取分数最低的前 k 个。

        Returns:
            布尔 DataFrame，选中的标的对应值为 True。
        """
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("cross_sectional_top_k_requires_positive_integer")
        if not scores.columns.is_unique:
            raise ValueError("cross_sectional_top_k_duplicate_assets")
        # Column order breaks ties deterministically. Invalid values never win;
        # a sparse row selects at most its finite asset count.
        finite_scores = scores.where(np.isfinite(scores))
        ranks = finite_scores.rank(axis=1, ascending=ascending, method="first")
        return ranks <= k

    @staticmethod
    def rolling_percentile(series: pd.Series, window: int = 20) -> pd.Series:
        """计算序列在其滑动窗口内的百分位排名（0.0 ~ 1.0）。"""
        if window < 2:
            raise ValueError("rolling percentile window must be at least 2")

        def _calc_rank(sub: np.ndarray) -> float:
            current = sub[-1]
            if np.isnan(current):
                return np.nan
            valid = sub[~np.isnan(sub)]
            if len(valid) == 0:
                return np.nan
            return float(np.sum(valid <= current) / len(valid))

        return series.rolling(window=window).apply(_calc_rank, raw=True)

    @staticmethod
    def risk_adjusted_momentum(
        prices: pd.DataFrame, return_window: int = 20, vol_window: int = 20
    ) -> pd.DataFrame:
        """计算资产的风险调整后动量（区间收益率 / 年化已实现波动率）。"""
        returns = prices.pct_change(return_window, fill_method=None)
        daily_ret = prices.pct_change(1, fill_method=None)
        realized_vol = daily_ret.rolling(window=vol_window).std() * np.sqrt(252)
        realized_vol = realized_vol.replace(0, np.nan)
        return returns / realized_vol
