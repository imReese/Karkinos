from __future__ import annotations

import math

import pytest

from analytics.multiple_testing import (
    build_deflated_sharpe,
    build_holm_bonferroni,
    build_probability_of_backtest_overfitting,
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
