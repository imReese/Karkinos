"""Backtest report tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from analytics import backtest_metrics
from analytics.backtest_metrics import CostSummary
from analytics.report import generate_report
from backtest.result import BacktestResult


def test_generate_report_includes_after_cost_evidence_bundle():
    cost_summary = CostSummary(
        total_commission=Decimal("8"),
        total_slippage=Decimal("2"),
        total_trades=2,
        gross_turnover=Decimal("2100"),
    )
    result = BacktestResult(
        equity_curve=[(datetime(2024, 1, 1), Decimal("1000"))],
        positions={},
        initial_cash=Decimal("1000"),
        final_equity=Decimal("1100"),
        cost_summary=cost_summary,
        evidence_bundle=backtest_metrics.build_after_cost_evidence(
            initial_cash=Decimal("1000"),
            final_equity=Decimal("1100"),
            cost_summary=cost_summary,
        ),
    )

    report = generate_report(result)

    assert "成本后证据:" in report
    assert "成本前估算收益率:" in report
    assert "成本占初始资金:" in report
    assert "限制:" in report
