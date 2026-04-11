"""equity — 权益曲线工具。"""

from __future__ import annotations

from decimal import Decimal

import numpy as np


class EquityCurve:
    """权益曲线工具。"""

    @staticmethod
    def daily_returns(equity_curve: list[tuple]) -> list[Decimal]:
        """计算日收益率。"""
        if len(equity_curve) < 2:
            return []

        returns = []
        for i in range(1, len(equity_curve)):
            prev_eq = equity_curve[i - 1][1]
            curr_eq = equity_curve[i][1]
            if prev_eq != Decimal("0"):
                ret = (curr_eq - prev_eq) / prev_eq
                returns.append(ret)
        return returns

    @staticmethod
    def cumulative_returns(equity_curve: list[tuple]) -> list[Decimal]:
        """计算累计收益率。"""
        if not equity_curve:
            return []

        initial = equity_curve[0][1]
        if initial == Decimal("0"):
            return []

        return [(eq - initial) / initial for _, eq in equity_curve]

    @staticmethod
    def rolling_max_drawdown(
        equity_curve: list[tuple], window: int = 20
    ) -> list[float]:
        """计算滚动最大回撤。"""
        equities = np.array([float(e) for _, e in equity_curve])
        if len(equities) < window:
            return []

        result = []
        for i in range(window - 1, len(equities)):
            window_data = equities[i - window + 1 : i + 1]
            peak = np.maximum.accumulate(window_data)
            dd = (peak - window_data) / peak
            result.append(float(np.max(dd)))
        return result
