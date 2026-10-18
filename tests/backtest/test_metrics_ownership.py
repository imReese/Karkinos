"""Backtest metric ownership and public analytics exports."""

import analytics
from backtest import metrics


def test_backtest_owns_metric_models_and_calculations() -> None:
    assert metrics.BacktestMetrics.__module__ == "backtest.metrics"
    assert metrics.CostSummary.__module__ == "backtest.metrics"
    assert metrics.calculate_backtest_metrics.__module__ == "backtest.metrics"


def test_analytics_package_exports_canonical_metrics() -> None:
    assert analytics.BacktestMetrics is metrics.BacktestMetrics
    assert analytics.CostSummary is metrics.CostSummary
    assert analytics.SharpeRatio is metrics.SharpeRatio
    assert analytics.AnnualizedReturn is metrics.AnnualizedReturn
    assert analytics.MaxDrawdown is metrics.MaxDrawdown
    assert analytics.SortinoRatio is metrics.SortinoRatio
    assert analytics.WinRate is metrics.WinRate
