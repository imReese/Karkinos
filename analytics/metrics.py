"""metrics — Sharpe/Sortino/最大回撤/胜率/年化收益。"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from core.types import ZERO


def _to_numpy_array(values: list[Decimal] | list[float]) -> np.ndarray:
    """将 Decimal 或 float 列表转为 numpy 数组。"""
    return np.array([float(v) for v in values])


class SharpeRatio:
    """Sharpe 比率。"""

    @staticmethod
    def calculate(
        returns: list[Decimal] | list[float], risk_free_rate: float = 0.03
    ) -> float:
        """计算 Sharpe 比率。

        Args:
            returns: 日收益率序列
            risk_free_rate: 年化无风险利率（默认 3%）
        """
        arr = _to_numpy_array(returns)
        if len(arr) < 2:
            return 0.0

        daily_rf = risk_free_rate / 252
        excess = arr - daily_rf
        std_excess = np.std(excess, ddof=1)
        if std_excess < 1e-10:
            # 所有超额收益相同（包括全为零）
            mean_excess = np.mean(excess)
            if mean_excess > 0:
                return float("inf")
            return 0.0

        return float(np.mean(excess) / std_excess * np.sqrt(252))


class SortinoRatio:
    """Sortino 比率。"""

    @staticmethod
    def calculate(
        returns: list[Decimal] | list[float], risk_free_rate: float = 0.03
    ) -> float:
        """计算 Sortino 比率。

        只考虑下行波动率。
        """
        arr = _to_numpy_array(returns)
        if len(arr) < 2:
            return 0.0

        daily_rf = risk_free_rate / 252
        excess = arr - daily_rf
        downside = excess[excess < 0]

        if len(downside) == 0:
            return float("inf") if np.mean(excess) > 0 else 0.0

        downside_std = np.sqrt(np.mean(downside**2))
        if downside_std == 0:
            return 0.0

        return float(np.mean(excess) / downside_std * np.sqrt(252))


class MaxDrawdown:
    """最大回撤。"""

    @staticmethod
    def calculate(equity_curve: list[Decimal] | list[float]) -> float:
        """计算最大回撤（返回正数百分比，如 0.15 表示 15%）。"""
        arr = _to_numpy_array(equity_curve)
        if len(arr) < 2:
            return 0.0

        peak = np.maximum.accumulate(arr)
        drawdown = (peak - arr) / peak
        return float(np.max(drawdown))


class WinRate:
    """胜率。"""

    @staticmethod
    def calculate(returns: list[Decimal] | list[float]) -> float:
        """计算胜率（正收益天数占比）。"""
        arr = _to_numpy_array(returns)
        if len(arr) == 0:
            return 0.0

        wins = np.sum(arr > 0)
        return float(wins / len(arr))


class AnnualizedReturn:
    """年化收益率。"""

    @staticmethod
    def calculate(
        equity_curve: list[Decimal] | list[float], trading_days: int = 252
    ) -> float:
        """计算年化收益率。

        Args:
            equity_curve: 权益曲线
            trading_days: 交易日数（用于年化）
        """
        arr = _to_numpy_array(equity_curve)
        if len(arr) < 2 or arr[0] == 0:
            return 0.0

        total_return = arr[-1] / arr[0] - 1.0
        n_periods = len(arr) - 1
        if n_periods <= 0:
            return 0.0

        # 年化 = (1 + 总收益率)^(252/交易日数) - 1
        annualized = (1 + total_return) ** (trading_days / n_periods) - 1
        return float(annualized)
