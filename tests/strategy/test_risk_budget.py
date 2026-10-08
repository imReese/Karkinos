"""Risk budgets, numerical failure, and capital bounds have distinct semantics."""

import numpy as np
import pytest

from strategy.risk_budget import project_box_constraints, risk_budget_weights


def test_diagonal_covariance_has_analytic_risk_budget_solution():
    variance = np.array([0.04, 0.0001, 0.09])
    budget = np.array([2.0, 3.0, 5.0])
    expected = np.sqrt(budget / variance)
    expected /= expected.sum()
    np.testing.assert_allclose(risk_budget_weights(np.diag(variance), budget), expected)


def test_correlated_budget_solution_preserves_scale_and_symbol_permutation():
    factor = np.array([[1, 0, 0], [0.3, 0.4, 0], [-0.2, 0.1, 0.3]])
    cov = factor @ factor.T
    budget = np.array([0.2, 0.3, 0.5])
    weights = risk_budget_weights(cov, budget)
    rc = weights * (cov @ weights)
    np.testing.assert_allclose(rc / rc.sum(), budget, atol=1e-8)
    assert weights.sum() == pytest.approx(1)
    for scale in (1e-200, 1e200):
        np.testing.assert_allclose(
            risk_budget_weights(cov * scale, budget * scale), weights
        )
    order = np.array([2, 0, 1])
    np.testing.assert_allclose(
        risk_budget_weights(cov[np.ix_(order, order)], budget[order]),
        weights[order],
        atol=1e-8,
    )


def test_singular_positive_correlation_needs_no_hidden_ridge():
    vol = np.array([0.2, 0.000001])
    np.testing.assert_allclose(
        risk_budget_weights(np.outer(vol, vol)), [vol[1], vol[0]] / vol.sum(), atol=1e-8
    )


@pytest.mark.parametrize(
    "covariance",
    [
        np.array([]),
        np.ones((2, 3)),
        np.ones(2),
        np.array([[0.0]]),
        np.array([[float("nan")]]),
        np.array([[1, 0.2], [0.4, 1]]),
        np.array([[1, 2], [2, 1]]),
        np.diag([1, -1]),
    ],
)
def test_invalid_covariance_never_becomes_a_portfolio(covariance):
    with pytest.raises(ValueError, match="risk_budget_covariance_"):
        risk_budget_weights(covariance)


@pytest.mark.parametrize(
    "budget", [[0, 1], [-1, 2], [1], [[1, 1]], [float("nan"), 1], [float("inf"), 1]]
)
def test_invalid_budget_never_defaults_to_equal_weights(budget):
    with pytest.raises(ValueError, match="risk_budget_budget_invalid"):
        risk_budget_weights(np.eye(2), np.array(budget))


def test_unattainable_or_unconverged_risk_budget_fails():
    with pytest.raises(ValueError, match="not_converged"):
        risk_budget_weights(np.array([[1, -1], [-1, 1]]))
    with pytest.raises(ValueError, match="not_converged"):
        risk_budget_weights(np.array([[1, 0.5], [0.5, 1]]), max_iter=1)


def test_projection_is_euclidean_and_respects_all_bounds():
    np.testing.assert_allclose(
        project_box_constraints(np.array([2, 1, 0]), 0.05, 0.8),
        [0.8, 0.15, 0.05],
        atol=1e-12,
    )
    np.testing.assert_allclose(
        project_box_constraints(np.array([0.5, 0.3, 0.15, 0.05]), 0.05, 0.3),
        [0.3, 0.3, 0.25, 0.15],
        atol=1e-12,
    )
    np.testing.assert_allclose(
        project_box_constraints(np.array([-4, 10]), 0.5, 0.5), [0.5, 0.5]
    )
    rng = np.random.default_rng(17)
    for _ in range(20):
        raw = rng.normal(size=5)
        actual = project_box_constraints(raw, 0.1, 0.35)
        assert actual.sum() == pytest.approx(1, abs=1e-12)
        assert np.all(actual >= 0.1) and np.all(actual <= 0.35)
        free = (actual > 0.1) & (actual < 0.35)
        if np.any(free):
            shift = raw[free] - actual[free]
            np.testing.assert_allclose(shift, shift[0], atol=1e-12)


@pytest.mark.parametrize(
    "weights,minimum,maximum",
    [
        ([], 0, 1),
        ([float("nan"), 1], 0, 1),
        ([[0.5, 0.5]], 0, 1),
        ([0.5, 0.5], 0, 0.4),
        ([0.5, 0.5], 0.6, 1),
        ([0.5, 0.5], -0.1, 1),
        ([0.5, 0.5], 0, float("nan")),
    ],
)
def test_projection_rejects_invalid_or_infeasible_inputs(weights, minimum, maximum):
    with pytest.raises(ValueError, match="risk_budget_projection_"):
        project_box_constraints(np.array(weights), minimum, maximum)
