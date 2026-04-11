"""BacktestResult — 回测结果 + 指标容器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from core.types import ZERO, Symbol
from domain.position import Position


@dataclass
class BacktestResult:
    """回测结果。"""

    equity_curve: list[tuple]  # (timestamp, equity)
    positions: dict[Symbol, Position]
    initial_cash: Decimal
    final_equity: Decimal

    @property
    def total_return(self) -> Decimal:
        """总收益率。"""
        if self.initial_cash == ZERO:
            return ZERO
        return (self.final_equity - self.initial_cash) / self.initial_cash

    @property
    def total_pnl(self) -> Decimal:
        """总盈亏。"""
        return self.final_equity - self.initial_cash

    @property
    def duration_days(self) -> int:
        """回测天数。"""
        if not self.equity_curve:
            return 0
        first = self.equity_curve[0][0]
        last = self.equity_curve[-1][0]
        return (last - first).days + 1
