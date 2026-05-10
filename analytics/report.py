"""report — 报告生成。"""

from __future__ import annotations

from backtest.result import BacktestResult


def generate_report(result: BacktestResult) -> str:
    """生成回测报告。"""
    if not result.equity_curve:
        return "No data in backtest result."

    metrics = result.metrics

    lines = [
        "=" * 50,
        "         Karkinos 回测报告",
        "=" * 50,
        f"初始资金:   {result.initial_cash:>15,.2f} CNY",
        f"最终权益:   {result.final_equity:>15,.2f} CNY",
        f"总盈亏:     {result.total_pnl:>15,.2f} CNY",
        f"总收益率:   {result.total_return * 100:>14.2f}%",
        f"年化收益:   {metrics.annual_return * 100:>14.2f}%",
        f"Sharpe比率: {metrics.sharpe:>14.2f}",
        f"Sortino比率:{metrics.sortino:>14.2f}",
        f"最大回撤:   {metrics.max_drawdown * 100:>14.2f}%",
        f"Calmar比率: {metrics.calmar:>14.2f}",
        f"胜率:       {metrics.win_rate * 100:>14.2f}%",
        f"总手续费:   {result.cost_summary.total_commission:>14,.2f} CNY",
        f"总滑点成本: {result.cost_summary.total_slippage:>14,.2f} CNY",
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
