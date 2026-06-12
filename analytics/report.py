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
        f"总成交额:   {result.cost_summary.gross_turnover:>14,.2f} CNY",
        f"总手续费:   {result.cost_summary.total_commission:>14,.2f} CNY",
        f"总滑点成本: {result.cost_summary.total_slippage:>14,.2f} CNY",
        f"回测天数:   {result.duration_days:>14d}",
        "-" * 50,
        "成本后证据:",
    ]

    if result.evidence_bundle is not None:
        evidence = result.evidence_bundle
        lines.extend(
            [
                f"  成本后收益率:     {evidence.net_return * 100:>10.2f}%",
                f"  成本前估算收益率: {evidence.gross_return_before_costs * 100:>10.2f}%",
                f"  总成本:           {evidence.total_cost:>10,.2f} CNY",
                f"  成本占初始资金:   {evidence.cost_to_initial_cash * 100:>10.2f}%",
                f"  成交笔数:         {evidence.fill_count:>10d}",
                "  限制: " + "；".join(evidence.limitations),
            ]
        )

    lines.extend(["-" * 50, "持仓:"])

    for symbol, pos in result.positions.items():
        if pos.quantity > 0:
            lines.append(
                f"  {symbol}: 数量={pos.quantity}, "
                f"均价={pos.avg_cost}, "
                f"盈亏={pos.realized_pnl}"
            )

    lines.append("=" * 50)
    return "\n".join(lines)
