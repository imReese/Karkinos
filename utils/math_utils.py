"""收益/风险计算辅助。"""

from __future__ import annotations

from decimal import Decimal

import numpy as np


def pct_change(old: Decimal, new: Decimal) -> Decimal:
    """计算百分比变化。"""
    if old == Decimal("0"):
        return Decimal("0")
    return (new - old) / old


def annualized_volatility(returns: list[Decimal], trading_days: int = 252) -> float:
    """计算年化波动率。"""
    arr = np.array([float(r) for r in returns])
    if len(arr) < 2:
        return 0.0
    return float(np.std(arr) * np.sqrt(trading_days))


def calmar_ratio(annual_return: float, max_drawdown: float) -> float:
    """计算 Calmar 比率。"""
    if max_drawdown == 0:
        return 0.0
    return annual_return / max_drawdown
