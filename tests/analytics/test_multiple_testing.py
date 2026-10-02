from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from analytics.multiple_testing import (
    build_deflated_sharpe,
    build_holm_bonferroni,
    build_probability_of_backtest_overfitting,
    build_return_series_trial_correction,
)


def test_holm_bonferroni_controls_family_wise_error():
    evidence = build_holm_bonferroni([0.01, 0.04, 0.03], alpha=0.05)
    assert evidence["family_size"] == 3
    assert evidence["rejected_count"] == 1
    assert evidence["tests"][0]["index"] == 0
    assert evidence["tests"][0]["adjusted_alpha"] == pytest.approx(0.05 / 3)
    assert evidence["tests"][0]["rejects"] is True
    assert len(evidence["evidence_fingerprint"]) == 64


def test_holm_bonferroni_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        build_holm_bonferroni([])
    with pytest.raises(ValueError):
        build_holm_bonferroni([0.01, 0.02], alpha=0.0)
    with pytest.raises(ValueError):
        build_holm_bonferroni([0.01, 1.5])


def test_inverse_normal_cdf_known_values():
    from analytics.multiple_testing import _inverse_normal_cdf, _normal_cdf

    assert _inverse_normal_cdf(0.5) == pytest.approx(0.0, abs=1e-9)
    assert _inverse_normal_cdf(0.975) == pytest.approx(1.95996, abs=1e-4)
    assert _normal_cdf(0.0) == pytest.approx(0.5, abs=1e-9)


def test_deflated_sharpe_without_trials_matches_probabilistic_sharpe():
    # With one trial and Normal returns, DSR reduces to PSR:
    # Phi(SR * sqrt(T-1) / sqrt(1 + 0.5 * SR^2)).
    observed = 0.2
    periods = 100
    evidence = build_deflated_sharpe(
        observed_sharpe=observed,
        num_periods=periods,
        num_trials=1,
    )
    expected_psr = 0.5 * (
        1.0
        + math.erf(
            observed
            * math.sqrt(periods - 1)
            / math.sqrt(1.0 + 0.5 * observed**2)
            / math.sqrt(2.0)
        )
    )
    assert evidence["expected_max_sharpe"] == 0.0
    assert evidence["deflated_sharpe"] == pytest.approx(expected_psr, abs=1e-9)


def test_deflated_sharpe_decreases_with_more_trials():
    one_trial = build_deflated_sharpe(
        observed_sharpe=0.5, num_periods=252, num_trials=1
    )
    many_trials = build_deflated_sharpe(
        observed_sharpe=0.5, num_periods=252, num_trials=100
    )
    assert many_trials["expected_max_sharpe"] > one_trial["expected_max_sharpe"]
    assert many_trials["deflated_sharpe"] < one_trial["deflated_sharpe"]


def test_deflated_sharpe_flags_insignificance_with_many_trials():
    evidence = build_deflated_sharpe(
        observed_sharpe=0.1, num_periods=252, num_trials=100
    )
    assert evidence["significant_at_0.95"] is False
    assert evidence["deflated_sharpe"] < 0.95


def test_deflated_sharpe_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        build_deflated_sharpe(observed_sharpe=0.5, num_periods=1, num_trials=1)
    with pytest.raises(ValueError):
        build_deflated_sharpe(observed_sharpe=0.5, num_periods=100, num_trials=0)


def _equity_curve(returns=(-0.02, 0.0, 0.02, 0.04)) -> list[tuple[datetime, Decimal]]:
    start = datetime(2026, 1, 1)
    equity = Decimal("100")
    points = [(start, equity)]
    for index, value in enumerate(returns, start=1):
        equity *= Decimal("1") + Decimal(str(value))
        points.append((start + timedelta(days=index), equity))
    return points


def test_return_series_correction_uses_actual_period_moments_not_annualized_sharpe():
    evidence = build_return_series_trial_correction(_equity_curve(), ["trial-a"])

    # Returns [-.02, 0, .02, .04] have mean .01, population variance .0005,
    # sample variance 1/1500, zero skew, and empirical excess kurtosis -1.36.
    moments = evidence["return_moments"]
    assert evidence["status"] == "assessed"
    assert moments["num_periods"] == 4
    assert moments["mean"] == pytest.approx(0.01)
    assert moments["sample_variance"] == pytest.approx(1 / 1500)
    assert moments["skewness"] == pytest.approx(0, abs=1e-12)
    assert moments["excess_kurtosis"] == pytest.approx(-1.36)
    period_sharpe = 0.01 / math.sqrt(1 / 1500)
    assert moments["observed_sharpe_per_period"] == pytest.approx(period_sharpe)
    expected_z = (
        period_sharpe * math.sqrt(3) / math.sqrt(1 + (1.64 - 1) / 4 * period_sharpe**2)
    )
    expected_probability = (1 + math.erf(expected_z / math.sqrt(2))) / 2
    assert evidence["dsr"]["deflated_sharpe"] == pytest.approx(expected_probability)
    assert evidence["significant_at_0_95"] is False
    assert len(evidence["evidence_fingerprint"]) == 64


def test_nominal_trial_deduplication_does_not_claim_independence():
    one = build_return_series_trial_correction(_equity_curve(), ["trial-a"])
    two = build_return_series_trial_correction(
        _equity_curve(), ["trial-b", "trial-a", "trial-b"]
    )
    reordered = build_return_series_trial_correction(
        _equity_curve(), ["trial-a", "trial-b"]
    )

    assert two == reordered
    assert two["trial_fingerprints"] == ["trial-a", "trial-b"]
    assert two["nominal_trial_count"] == 2
    assert two["independent_trial_count"] is None
    assert two["trial_count_model"] == "nominal_trials_treated_as_independent"
    assert (
        two["trial_sharpe_dispersion_model"]
        == "candidate_return_moments_sampling_error"
    )
    assert two["trial_family_completeness"] == "not_verified"
    assert two["dsr"]["deflated_sharpe"] < one["dsr"]["deflated_sharpe"]
    assert any("correlation is unknown" in item for item in two["limitations"])


def test_return_series_engine_and_persisted_points_have_same_evidence():
    points = _equity_curve()
    persisted = [
        {"timestamp": timestamp.isoformat(), "equity": str(equity)}
        for timestamp, equity in points
    ]
    assert build_return_series_trial_correction(
        points, ["trial-a"]
    ) == build_return_series_trial_correction(persisted, ["trial-a"])


def test_return_series_fingerprint_binds_order_even_when_moments_match():
    first = build_return_series_trial_correction(_equity_curve(), ["trial-a"])
    reversed_returns = build_return_series_trial_correction(
        _equity_curve((0.04, 0.02, 0, -0.02)), ["trial-a"]
    )
    assert first["dsr"]["deflated_sharpe"] == pytest.approx(
        reversed_returns["dsr"]["deflated_sharpe"]
    )
    assert (
        first["return_series_fingerprint"]
        != reversed_returns["return_series_fingerprint"]
    )
    assert first["evidence_fingerprint"] != reversed_returns["evidence_fingerprint"]


@pytest.mark.parametrize(
    ("points", "blocker"),
    [
        (None, "equity_curve_missing"),
        ([], "equity_curve_missing"),
        ("not-a-curve", "equity_curve_missing"),
        ([{}], "equity_curve_timestamp_invalid"),
        ([["2026-01-01"]], "equity_curve_point_invalid"),
        ([("bad-date", 100)], "equity_curve_timestamp_invalid"),
        ([("2026-01-01", None)], "equity_curve_value_invalid"),
        ([("2026-01-01", 0)], "equity_curve_value_invalid"),
        ([("2026-01-01", -100)], "equity_curve_value_invalid"),
        ([("2026-01-01", True)], "equity_curve_value_invalid"),
        ([("2026-01-01", float("nan"))], "equity_curve_value_invalid"),
        ([("2026-01-01", float("inf"))], "equity_curve_value_invalid"),
        (
            [("2026-01-01", 100), ("2026-01-01", 101)],
            "equity_curve_not_strictly_increasing",
        ),
        (
            [("2026-01-02", 100), ("2026-01-01", 101)],
            "equity_curve_not_strictly_increasing",
        ),
        (
            [("2026-01-01", 100), ("2026-01-02T00:00:00+08:00", 101)],
            "equity_curve_mixed_timezone_awareness",
        ),
        (
            [("2026-01-01", 1e-308), ("2026-01-02", 1e308)],
            "period_return_not_finite",
        ),
        (_equity_curve((0.01, 0.02, 0.03)), "insufficient_return_periods"),
        (_equity_curve((0.0,) * 4), "constant_return_series"),
        (_equity_curve((0.1,) * 4), "constant_return_series"),
    ],
)
def test_invalid_or_insufficient_return_series_cannot_pass(points, blocker):
    evidence = build_return_series_trial_correction(points, ["trial-a"])
    assert evidence["status"] == "unavailable"
    assert blocker in evidence["blockers"]
    assert evidence["dsr"] is None
    assert evidence["significant_at_0_95"] is None


@pytest.mark.parametrize("trials", [None, [], "trial-a", [""], [None], ["a", " "]])
def test_missing_or_invalid_trial_family_cannot_pass(trials):
    evidence = build_return_series_trial_correction(_equity_curve(), trials)
    assert evidence["status"] == "unavailable"
    assert evidence["blockers"]
    assert evidence["nominal_trial_count"] == 0
    assert evidence["dsr"] is None
    assert evidence["significant_at_0_95"] is None


def _dominant_returns() -> list[list[float]]:
    periods = 32
    winner = [0.12 if index % 2 == 0 else 0.08 for index in range(periods)]
    loser = [-0.12 if index % 2 == 0 else -0.08 for index in range(periods)]
    return [list(pair) for pair in zip(winner, loser, strict=True)]


def test_probability_of_backtest_overfitting_zero_for_dominant_trial():
    returns = _dominant_returns()
    evidence = build_probability_of_backtest_overfitting(returns, num_blocks=4)
    assert evidence["num_trials"] == 2
    assert evidence["num_blocks"] == 4
    assert evidence["cscv_split_count"] == 6  # C(4, 2)
    assert evidence["probability_of_backtest_overfitting"] == 0.0
    assert len(evidence["evidence_fingerprint"]) == 64


def test_probability_of_backtest_overfitting_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        build_probability_of_backtest_overfitting([], num_blocks=4)
    with pytest.raises(ValueError):
        build_probability_of_backtest_overfitting([[0.1, -0.1]] * 4, num_blocks=3)
    with pytest.raises(ValueError):
        build_probability_of_backtest_overfitting([[0.1, -0.1], [0.1]], num_blocks=4)
