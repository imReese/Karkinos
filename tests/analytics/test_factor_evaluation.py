"""Tests for analytics/factor_evaluation.py cross-sectional factor engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.factor_evaluation import (
    calculate_ic,
    calculate_quantile_returns,
    calculate_rank_ic,
    summarize_ic,
    summarize_quantile_spread,
)


@pytest.fixture
def synthetic_factor_and_returns():
    """Create a synthetic factor panel with positive forward correlation."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    assets = [f"asset_{i}" for i in range(10)]

    # Factor is standard normal
    factor_data = np.random.randn(len(dates), len(assets))
    factor_df = pd.DataFrame(factor_data, index=dates, columns=assets)

    # Forward return has signal + noise
    return_data = 0.5 * factor_data + 0.2 * np.random.randn(len(dates), len(assets))
    return_df = pd.DataFrame(return_data, index=dates, columns=assets)

    return factor_df, return_df


def test_calculate_ic_and_rank_ic(synthetic_factor_and_returns):
    factor_df, return_df = synthetic_factor_and_returns

    ic = calculate_ic(factor_df, return_df, method="pearson")
    rank_ic = calculate_rank_ic(factor_df, return_df)

    assert len(ic) == len(factor_df)
    assert len(rank_ic) == len(factor_df)

    # Mean IC should be positive and strong given synthetic construction
    assert ic.mean() > 0.4
    assert rank_ic.mean() > 0.4


def test_summarize_ic(synthetic_factor_and_returns):
    factor_df, return_df = synthetic_factor_and_returns
    rank_ic = calculate_rank_ic(factor_df, return_df)

    summary = summarize_ic(rank_ic)
    assert summary["sample_count"] == 30.0
    assert summary["mean_ic"] > 0.4
    assert summary["icir"] > 0.0
    assert summary["annualized_icir"] > 0.0
    assert summary["t_stat"] > 2.0
    assert summary["p_value"] < 0.05
    assert summary["positive_ratio"] > 0.8


def test_calculate_quantile_returns_and_spread(synthetic_factor_and_returns):
    factor_df, return_df = synthetic_factor_and_returns

    q_rets = calculate_quantile_returns(factor_df, return_df, n_quantiles=5)
    assert "Q1" in q_rets.columns
    assert "Q5" in q_rets.columns
    assert "long_short" in q_rets.columns

    # High factor should outperform low factor on average
    assert q_rets["Q5"].mean() > q_rets["Q1"].mean()
    assert q_rets["long_short"].mean() > 0

    spread_summary = summarize_quantile_spread(q_rets)
    assert spread_summary["annualized_spread_return"] > 0
    assert spread_summary["spread_sharpe"] > 0
    assert spread_summary["monotonicity_score"] > 0.5


def test_empty_and_nan_handling():
    empty_f = pd.DataFrame()
    empty_r = pd.DataFrame()

    ic = calculate_ic(empty_f, empty_r)
    assert len(ic) == 0

    summary = summarize_ic(ic)
    assert summary["sample_count"] == 0.0

    nan_f = pd.DataFrame({"A": [np.nan], "B": [np.nan]})
    nan_r = pd.DataFrame({"A": [1.0], "B": [2.0]})
    ic_nan = calculate_ic(nan_f, nan_r)
    assert pd.isna(ic_nan.iloc[0])
