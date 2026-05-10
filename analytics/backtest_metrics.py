"""Backtest metrics aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from math import isinf

import numpy as np

from analytics.metrics import (
    AnnualizedReturn,
    MaxDrawdown,
    SharpeRatio,
    SortinoRatio,
    WinRate,
)
from core.events import FillEvent


@dataclass(frozen=True)
class CostSummary:
    """Aggregated execution costs for a backtest."""

    total_commission: Decimal = Decimal("0")
    total_slippage: Decimal = Decimal("0")
    total_trades: int = 0
    gross_turnover: Decimal = Decimal("0")

    def to_json_dict(self) -> dict[str, float | int]:
        return {
            "total_commission": float(self.total_commission),
            "total_slippage": float(self.total_slippage),
            "total_trades": self.total_trades,
            "gross_turnover": float(self.gross_turnover),
        }


@dataclass(frozen=True)
class BacktestMetrics:
    """Core risk-adjusted metrics for a backtest."""

    initial_cash: float = 0.0
    final_equity: float = 0.0
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    calmar: float = 0.0
    volatility: float = 0.0
    win_rate: float = 0.0
    duration_days: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    total_trades: int = 0
    gross_turnover: float = 0.0

    def to_json_dict(self) -> dict:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, float) and isinf(value):
                payload[key] = "inf" if value > 0 else "-inf"
        return payload


def summarize_fill_costs(fills: list[FillEvent]) -> CostSummary:
    """Summarize commissions, slippage, and turnover from fills."""
    total_commission = sum((fill.commission for fill in fills), Decimal("0"))
    total_slippage = sum((fill.slippage for fill in fills), Decimal("0"))
    gross_turnover = sum(
        (fill.fill_price * fill.fill_quantity for fill in fills), Decimal("0")
    )
    return CostSummary(
        total_commission=total_commission,
        total_slippage=total_slippage,
        total_trades=len(fills),
        gross_turnover=gross_turnover,
    )


def calculate_backtest_metrics(
    equity_curve: list[tuple],
    *,
    initial_cash: Decimal,
    final_equity: Decimal,
    cost_summary: CostSummary | None = None,
    risk_free_rate: float = 0.03,
) -> BacktestMetrics:
    """Calculate standard performance and cost metrics from equity curve."""
    equities = [float(equity) for _, equity in equity_curve]
    returns = [
        Decimal(str((equities[i] - equities[i - 1]) / equities[i - 1]))
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]
    duration_days = _duration_days(equity_curve)
    total_return = (
        float((final_equity - initial_cash) / initial_cash)
        if initial_cash != Decimal("0")
        else 0.0
    )
    annual_return = AnnualizedReturn.calculate(equities)
    max_drawdown = MaxDrawdown.calculate(equities)
    calmar = _calculate_calmar(annual_return, max_drawdown)
    cost_summary = cost_summary or CostSummary()

    return BacktestMetrics(
        initial_cash=float(initial_cash),
        final_equity=float(final_equity),
        total_return=total_return,
        annual_return=annual_return,
        sharpe=SharpeRatio.calculate(returns, risk_free_rate=risk_free_rate),
        sortino=SortinoRatio.calculate(returns, risk_free_rate=risk_free_rate),
        max_drawdown=max_drawdown,
        calmar=calmar,
        volatility=_annualized_volatility(returns),
        win_rate=WinRate.calculate(returns),
        duration_days=duration_days,
        total_commission=float(cost_summary.total_commission),
        total_slippage=float(cost_summary.total_slippage),
        total_trades=cost_summary.total_trades,
        gross_turnover=float(cost_summary.gross_turnover),
    )


def _duration_days(equity_curve: list[tuple]) -> int:
    if not equity_curve:
        return 0
    first = equity_curve[0][0]
    last = equity_curve[-1][0]
    return (last - first).days + 1


def _annualized_volatility(returns: list[Decimal]) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.array([float(value) for value in returns])
    return float(np.std(arr, ddof=1) * np.sqrt(252))


def _calculate_calmar(annual_return: float, max_drawdown: float) -> float:
    if max_drawdown <= 0:
        return float("inf") if annual_return > 0 else 0.0
    return annual_return / max_drawdown
