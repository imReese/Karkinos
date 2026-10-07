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


def test_spread_drawdown_includes_initial_unit_equity():
    summary = summarize_quantile_spread(pd.DataFrame({"long_short": [-0.10, 0.0]}))
    assert summary["spread_max_drawdown"] == 0.10


def test_multiperiod_ic_uses_nonoverlapping_fixed_sample():
    # Odd rows overlap the endpoints of the even rows and must not increase n.
    ic = pd.Series([0.1, 0.9, 0.3, 0.9, np.nan, 0.9, 0.2, np.inf])
    summary = summarize_ic(ic, holding_period=2)
    assert summary["sample_count"] == 3
    assert summary["mean_ic"] == 0.2
    expected_icir = 0.2 / pd.Series([0.1, 0.3, 0.2]).std(ddof=1)
    assert summary["annualized_icir"] == pytest.approx(
        expected_icir * np.sqrt(126), abs=0.0001
    )


def test_multiperiod_spread_uses_matching_horizon_and_sample_spacing():
    returns = pd.DataFrame({"long_short": [-0.1, 0.9, 0.0, 0.9]})
    summary = summarize_quantile_spread(returns, holding_period=2)
    assert summary["annualized_spread_return"] == -6.3
    assert summary["spread_max_drawdown"] == 0.1
    spaced = summarize_quantile_spread(
        returns.iloc[::2], holding_period=2, sample_spacing=2
    )
    assert summary == spaced


def test_factor_summaries_exclude_infinite_values():
    assert summarize_ic(pd.Series([np.inf, -np.inf, 0.2]))["sample_count"] == 1
    summary = summarize_quantile_spread(
        pd.DataFrame({"long_short": [np.inf, -np.inf, -0.1]})
    )
    assert summary["annualized_spread_return"] == -25.2
    assert summary["spread_max_drawdown"] == 0.1
    assert all(np.isfinite(value) for value in summary.values())


@pytest.mark.parametrize("holding_period", [0, -1, 1.5, True])
def test_summaries_reject_ambiguous_horizon(holding_period):
    with pytest.raises(ValueError, match="positive_integer"):
        summarize_ic(pd.Series([0.1]), holding_period=holding_period)
    with pytest.raises(ValueError, match="positive_integer"):
        summarize_quantile_spread(
            pd.DataFrame({"long_short": [0.1]}), holding_period=holding_period
        )
