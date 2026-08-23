"""Compatibility exports for backtest-owned metrics.

The canonical implementations live in :mod:`backtest.metrics`. This module is
kept so existing analytics imports continue to resolve during the package
boundary migration.
"""

from backtest.metrics import (
    AfterCostEvidence,
    BacktestMetrics,
    CostSummary,
    build_after_cost_evidence,
    calculate_backtest_metrics,
    summarize_fill_costs,
)

__all__ = [
    "AfterCostEvidence",
    "BacktestMetrics",
    "CostSummary",
    "build_after_cost_evidence",
    "calculate_backtest_metrics",
    "summarize_fill_costs",
]
