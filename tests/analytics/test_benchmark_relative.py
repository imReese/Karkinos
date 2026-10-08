"""Aligned research return metrics, financial definitions and unavailable cases."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import stdev

import numpy as np
import pandas as pd
import pytest

from analytics.benchmark_relative import evaluate_benchmark_relative


def returns(values):
    return pd.Series(
        values,
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
        dtype=float,
    )


def evaluate(portfolio, benchmark, **assumptions):
    return evaluate_benchmark_relative(
        returns(portfolio),
        returns(benchmark),
        **({"risk_free_rate": 0.0, "periods_per_year": 12} | assumptions),
    )


def test_active_metrics_use_arithmetic_difference_and_explicit_sampling():
    result = evaluate([0.04, -0.02, 0.03], [0.02, -0.01, 0.015])
    active = [0.02, -0.01, 0.015]
    annual_mean = sum(active) / len(active) * 12
    tracking_error = stdev(active) * math.sqrt(12)
    assert result.annualized_excess_return == pytest.approx(annual_mean)
    assert result.tracking_error == pytest.approx(tracking_error)
    assert result.information_ratio == pytest.approx(annual_mean / tracking_error)
    assert result.outperformance_ratio == pytest.approx(2 / 3)
    assert result.sample_periods == 3
    assert result.periods_per_year == 12


def test_relative_drawdown_uses_wealth_ratio_and_initial_wealth():
    result = evaluate([-0.5, 0.2], [-0.4, 0.1])
    # Wealth ratios are 1, 0.5/0.6, 0.6/0.66. Subtracting and compounding
    # returns instead would produce a different drawdown, or miss period one.
    assert result.relative_max_drawdown == pytest.approx(1 - 0.5 / 0.6)
    single = evaluate([-0.1], [0.1])
    assert single.relative_max_drawdown == pytest.approx(1 - 0.9 / 1.1)


def test_capm_ols_uses_effective_risk_free_period_return_without_rounding():
    risk_free = 0.05
    rf_period = (1 + risk_free) ** (1 / 12) - 1
    excess_market = np.array([0.01, -0.02, 0.005, 0.03, -0.01])
    benchmark = rf_period + excess_market
    portfolio = rf_period + 0.0001234567 + 1.23456789 * excess_market
    result = evaluate(portfolio, benchmark, risk_free_rate=risk_free)
    assert result.capm_beta == pytest.approx(1.23456789, abs=1e-12)
    assert result.capm_alpha == pytest.approx(0.0001234567 * 12, abs=1e-12)


def test_empty_single_period_and_constant_benchmark_do_not_invent_estimates():
    empty = evaluate([], [])
    assert empty.sample_periods == 0
    assert all(
        value is None
        for name, value in empty.to_json_dict().items()
        if name not in {"sample_periods", "periods_per_year", "risk_free_rate"}
    )
    single = evaluate([0.01], [0.02])
    assert single.tracking_error is None
    assert single.information_ratio is None
    assert (single.capm_alpha, single.capm_beta) == (None, None)
    constant_market = evaluate([0.01, 0.02, 0.03], [0.01, 0.01, 0.01])
    assert (constant_market.capm_alpha, constant_market.capm_beta) == (None, None)
    json.dumps(empty.to_json_dict(), allow_nan=False)


def test_zero_active_risk_has_no_information_ratio():
    result = evaluate([0.011, 0.021, -0.009], [0.01, 0.02, -0.01])
    assert result.tracking_error == 0.0
    assert result.information_ratio is None
    same = evaluate([0.01, -0.02, 0.03], [0.01, -0.02, 0.03])
    assert same.relative_max_drawdown == 0.0
    assert same.annualized_excess_return == 0.0
    assert same.information_ratio is None


def test_total_loss_does_not_manufacture_recovery_or_divide_by_zero():
    assert evaluate([0.01, -1], [0.01, -0.2]).relative_max_drawdown == 1.0
    assert evaluate([0.01, -0.2], [0.01, -1]).relative_max_drawdown is None
    with pytest.raises(ValueError, match="after_total_loss"):
        evaluate([-1, 0.1], [0.01, 0.02])
    with pytest.raises(ValueError, match="below_total_loss"):
        evaluate([-1.1], [0.0])


@pytest.mark.parametrize(
    "change", ["shorter", "shifted", "duplicate", "unordered", "nat"]
)
def test_wrong_period_alignment_is_rejected_instead_of_truncating(change):
    portfolio = returns([0.01, 0.02, 0.03])
    benchmark = returns([0.0, 0.01, 0.02])
    if change == "shorter":
        benchmark = benchmark.iloc[:2]
    elif change == "shifted":
        benchmark.index += pd.Timedelta(days=1)
    elif change == "duplicate":
        benchmark.index = pd.DatetimeIndex([portfolio.index[0]] * 3)
    elif change == "unordered":
        benchmark = benchmark.iloc[::-1]
    else:
        benchmark.index = pd.DatetimeIndex(
            [portfolio.index[0], pd.NaT, portfolio.index[2]]
        )
    with pytest.raises(ValueError, match="index_invalid|periods_not_aligned"):
        evaluate_benchmark_relative(
            portfolio, benchmark, risk_free_rate=0.0, periods_per_year=252
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_return_is_rejected_without_dropping_samples(bad):
    with pytest.raises(ValueError, match="values_invalid"):
        evaluate([0.1, bad], [0.01, 0.02])


@pytest.mark.parametrize("bad", [True, 0.01 + 0.02j])
def test_boolean_or_complex_values_are_not_silently_coerced_to_returns(bad):
    benchmark = returns([0.01])
    portfolio = pd.Series([bad], index=benchmark.index)
    with pytest.raises(ValueError, match="values_invalid"):
        evaluate_benchmark_relative(
            portfolio, benchmark, risk_free_rate=0.0, periods_per_year=252
        )


@pytest.mark.parametrize(
    "values,dtype",
    [
        (pd.date_range("2026-01-01", periods=3), None),
        (pd.date_range("2026-01-01", periods=3, tz="UTC"), None),
        (pd.to_timedelta([1, 2, 3], unit="D"), None),
        ([datetime(2026, 1, 1)] * 3, object),
        ([date(2026, 1, 1)] * 3, object),
        ([timedelta(days=1)] * 3, object),
        ([np.datetime64("2026-01-01")] * 3, object),
        ([np.timedelta64(1, "D")] * 3, object),
        ([Decimal("0.01"), pd.Timestamp("2026-01-01"), Decimal("0.03")], object),
    ],
)
def test_temporal_values_are_not_cast_to_numeric_returns(values, dtype):
    index = pd.date_range("2026-01-01", periods=3)
    invalid = pd.Series(values, index=index, dtype=dtype)
    valid = pd.Series([0.01, 0.02, 0.03], index=index)
    for portfolio, benchmark in ((invalid, valid), (valid, invalid)):
        with pytest.raises(ValueError, match="benchmark_returns_values_invalid"):
            evaluate_benchmark_relative(
                portfolio, benchmark, risk_free_rate=0.0, periods_per_year=252
            )


def test_object_decimal_returns_keep_the_same_metrics_as_numeric_returns():
    portfolio, benchmark = returns([0.01, -0.02, 0.03]), returns([0.02, 0.01, 0.015])
    decimal_portfolio = portfolio.map(lambda value: Decimal(str(value)))
    decimal_benchmark = benchmark.map(lambda value: Decimal(str(value)))
    expected = evaluate_benchmark_relative(
        portfolio, benchmark, risk_free_rate=0.0, periods_per_year=252
    )
    assert (
        evaluate_benchmark_relative(
            decimal_portfolio,
            decimal_benchmark,
            risk_free_rate=0.0,
            periods_per_year=252,
        )
        == expected
    )


@pytest.mark.parametrize(
    "assumptions",
    [
        {"periods_per_year": 0},
        {"periods_per_year": True},
        {"periods_per_year": 12.5},
        {"risk_free_rate": float("nan")},
        {"risk_free_rate": -1},
        {"risk_free_rate": True},
    ],
)
def test_invalid_sampling_or_risk_free_assumptions_are_rejected(assumptions):
    with pytest.raises(ValueError):
        evaluate([0.01], [0.02], **assumptions)


def test_undated_arrays_are_not_treated_as_aligned_periods():
    with pytest.raises(ValueError, match="dated_series_required"):
        evaluate_benchmark_relative(
            [0.01], [0.01], risk_free_rate=0.0, periods_per_year=252
        )
