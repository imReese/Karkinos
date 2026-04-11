"""Analytics metrics 单元测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from analytics.metrics import (
    AnnualizedReturn,
    MaxDrawdown,
    SharpeRatio,
    SortinoRatio,
    WinRate,
)


class TestSharpeRatio:
    def test_positive_sharpe(self):
        """正收益序列应有正 Sharpe。"""
        # 有变化的正收益
        returns = [Decimal("0.01"), Decimal("0.02"), Decimal("0.015"), Decimal("0.008")]
        sharpe = SharpeRatio.calculate(returns)
        assert sharpe > 0

    def test_zero_returns(self):
        """零收益序列 Sharpe 为 0。"""
        returns = [Decimal("0")] * 50
        sharpe = SharpeRatio.calculate(returns)
        assert sharpe == 0.0

    def test_constant_positive_returns(self):
        """恒定正收益（零波动）Sharpe 为无穷。"""
        returns = [Decimal("0.01")] * 50
        sharpe = SharpeRatio.calculate(returns)
        assert sharpe == float("inf")

    def test_single_return(self):
        returns = [Decimal("0.01")]
        sharpe = SharpeRatio.calculate(returns)
        assert sharpe == 0.0


class TestSortinoRatio:
    def test_positive_sortino(self):
        returns = [Decimal("0.01")] * 50
        sortino = SortinoRatio.calculate(returns)
        assert sortino > 0 or sortino == float("inf")

    def test_mixed_returns(self):
        returns = [
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.01"),
            Decimal("-0.005"),
        ]
        sortino = SortinoRatio.calculate(returns)
        # 只要能计算即可
        assert isinstance(sortino, float)


class TestMaxDrawdown:
    def test_no_drawdown(self):
        """持续上涨无回撤。"""
        equity = [Decimal(str(100 + i)) for i in range(10)]
        dd = MaxDrawdown.calculate(equity)
        assert dd == 0.0

    def test_known_drawdown(self):
        """已知回撤计算。"""
        equity = [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110")]
        dd = MaxDrawdown.calculate(equity)
        # 从 120 跌到 90，回撤 = 30/120 = 0.25
        assert abs(dd - 0.25) < 1e-6

    def test_empty_curve(self):
        dd = MaxDrawdown.calculate([])
        assert dd == 0.0


class TestWinRate:
    def test_all_wins(self):
        returns = [Decimal("0.01")] * 10
        wr = WinRate.calculate(returns)
        assert wr == 1.0

    def test_mixed(self):
        returns = [
            Decimal("0.01"),
            Decimal("-0.01"),
            Decimal("0.02"),
            Decimal("-0.005"),
        ]
        wr = WinRate.calculate(returns)
        assert wr == 0.5

    def test_empty(self):
        wr = WinRate.calculate([])
        assert wr == 0.0


class TestAnnualizedReturn:
    def test_known_annual_return(self):
        """已知年化收益率计算。"""
        # 252 个交易日，从 100 到 110
        equity = [Decimal(str(100 + 10 * i / 251)) for i in range(252)]
        annual = AnnualizedReturn.calculate(equity)
        assert annual > 0
        # 年化约 10%
        assert abs(annual - 0.10) < 0.01

    def test_empty(self):
        annual = AnnualizedReturn.calculate([])
        assert annual == 0.0
