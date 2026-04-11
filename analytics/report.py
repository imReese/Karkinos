"""report — 报告生成。"""

from __future__ import annotations

from decimal import Decimal

from analytics.metrics import (
    AnnualizedReturn,
    MaxDrawdown,
    SharpeRatio,
    SortinoRatio,
    WinRate,
)
from backtest.result import BacktestResult


def generate_report(result: BacktestResult) -> str:
    """生成回测报告。"""
    if not result.equity_curve:
        return "No data in backtest result."

    # 计算日收益率
    equities = [float(e) for _, e in result.equity_curve]
    returns = [
        Decimal(str((equities[i] - equities[i - 1]) / equities[i - 1]))
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]

    sharpe = SharpeRatio.calculate(returns)
    sortino = SortinoRatio.calculate(returns)
    max_dd = MaxDrawdown.calculate(equities)
    win_rate = WinRate.calculate(returns)
    annual_return = AnnualizedReturn.calculate(equities)

    lines = [
        "=" * 50,
        "         MyQuant 回测报告",
        "=" * 50,
        f"初始资金:   {result.initial_cash:>15,.2f} CNY",
        f"最终权益:   {result.final_equity:>15,.2f} CNY",
        f"总盈亏:     {result.total_pnl:>15,.2f} CNY",
        f"总收益率:   {result.total_return * 100:>14.2f}%",
        f"年化收益:   {annual_return * 100:>14.2f}%",
        f"Sharpe比率: {sharpe:>14.2f}",
        f"Sortino比率:{sortino:>14.2f}",
        f"最大回撤:   {max_dd * 100:>14.2f}%",
        f"胜率:       {win_rate * 100:>14.2f}%",
        f"回测天数:   {result.duration_days:>14d}",
        "-" * 50,
        "持仓:",
    ]

    for symbol, pos in result.positions.items():
        if pos.quantity > 0:
            lines.append(
                f"  {symbol}: 数量={pos.quantity}, "
                f"均价={pos.avg_cost}, "
                f"盈亏={pos.realized_pnl}"
            )

    lines.append("=" * 50)
    return "\n".join(lines)
