"""Backtest metric ownership and compatibility contracts."""

import analytics
from analytics import backtest_metrics as legacy_backtest_metrics
from analytics import metrics as legacy_metrics
from backtest import metrics


def test_backtest_owns_metric_models_and_calculations() -> None:
    assert metrics.BacktestMetrics.__module__ == "backtest.metrics"
    assert metrics.CostSummary.__module__ == "backtest.metrics"
    assert metrics.calculate_backtest_metrics.__module__ == "backtest.metrics"


def test_legacy_analytics_metric_imports_are_identity_preserving() -> None:
    assert legacy_backtest_metrics.AfterCostEvidence is metrics.AfterCostEvidence
    assert legacy_backtest_metrics.BacktestMetrics is metrics.BacktestMetrics
    assert legacy_backtest_metrics.CostSummary is metrics.CostSummary
    assert (
        legacy_backtest_metrics.build_after_cost_evidence
        is metrics.build_after_cost_evidence
    )
    assert (
        legacy_backtest_metrics.calculate_backtest_metrics
        is metrics.calculate_backtest_metrics
    )
    assert legacy_backtest_metrics.summarize_fill_costs is metrics.summarize_fill_costs


def test_legacy_analytics_package_exports_are_identity_preserving() -> None:
    assert analytics.BacktestMetrics is metrics.BacktestMetrics
    assert analytics.CostSummary is metrics.CostSummary
    assert analytics.SharpeRatio is metrics.SharpeRatio
    assert legacy_metrics.AnnualizedReturn is metrics.AnnualizedReturn
    assert legacy_metrics.MaxDrawdown is metrics.MaxDrawdown
    assert legacy_metrics.SharpeRatio is metrics.SharpeRatio
    assert legacy_metrics.SortinoRatio is metrics.SortinoRatio
    assert legacy_metrics.WinRate is metrics.WinRate
