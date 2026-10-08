"""Pure numerical allocation helpers for research strategies.

Risk budgeting minimizes 0.5 * x' C x - sum(b * log(x)), then rescales by
volatility and normalizes. See Griveau-Billion, Richard and Roncalli (2013),
https://arxiv.org/abs/1311.4057, including Appendix A.3.2. This implementation
uses coordinate minimization and verifies normalized risk contributions;
it never repairs inputs or substitutes weights.
"""

from __future__ import annotations

import math

import numpy as np


def risk_budget_weights(
    covariance: np.ndarray,
    risk_budget: np.ndarray | None = None,
    *,
    max_iter: int = 2000,
    tolerance: float = 1e-8,
) -> np.ndarray:
    """Return positive weights matching positive relative variance-risk budgets.

    Covariance must be finite, symmetric, positive semidefinite and have positive
    diagonal entries. Singular matrices are accepted only if iteration finds a
    positive-risk solution. Unattainable budgets or nonconvergence raise instead
    of returning an approximate or equal-weight portfolio. No ridge is added.
    """
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or max_iter < 1:
        raise ValueError("risk_budget_iteration_limit_invalid")
    if not math.isfinite(tolerance) or not 0 < tolerance < 1:
        raise ValueError("risk_budget_tolerance_invalid")
    cov = np.asarray(covariance, dtype=float)
    if cov.ndim != 2 or cov.shape[0] == 0 or cov.shape[0] != cov.shape[1]:
        raise ValueError("risk_budget_covariance_shape_invalid")
    if not np.all(np.isfinite(cov)) or np.any(np.diag(cov) <= 0):
        raise ValueError("risk_budget_covariance_invalid")
    # Correlation coordinates preserve units and very small bond variances.
    vol = np.sqrt(np.diag(cov))
    corr = cov / vol[:, None] / vol[None, :]
    if not np.allclose(corr, corr.T, atol=1e-12, rtol=1e-12):
        raise ValueError("risk_budget_covariance_not_symmetric")
    corr = (corr + corr.T) * 0.5  # numerical symmetry only, never a PSD repair
    if np.linalg.eigvalsh(corr).min() < -1e-12:
        raise ValueError("risk_budget_covariance_not_positive_semidefinite")
    n = len(cov)
    budget = np.ones(n) if risk_budget is None else np.asarray(risk_budget, dtype=float)
    if budget.shape != (n,) or not np.all(np.isfinite(budget)) or np.any(budget <= 0):
        raise ValueError("risk_budget_budget_invalid")
    budget = budget / budget.max()
    budget = budget / budget.sum()
    if np.any(budget <= 0):
        raise ValueError("risk_budget_budget_invalid")
    x = np.sqrt(budget)
    for _ in range(max_iter):
        for i in range(n):
            c = float(corr[i] @ x - corr[i, i] * x[i])
            root = math.hypot(c, 2 * math.sqrt(corr[i, i] * budget[i]))
            # Avoid cancellation in the positive quadratic root when c > 0.
            x[i] = (
                2 * budget[i] / (root + c) if c >= 0 else (root - c) / (2 * corr[i, i])
            )
        contribution = x * (corr @ x)
        variance = float(contribution.sum())
        if (
            np.all(np.isfinite(contribution))
            and variance > 0
            and np.max(np.abs(contribution / variance - budget)) <= tolerance
        ):
            weights = x * (vol.min() / vol)
            weights /= weights.sum()
            if np.all(np.isfinite(weights)) and np.all(weights > 0):
                return weights
            break
    raise ValueError("risk_budget_not_converged")


def project_box_constraints(
    weights: np.ndarray,
    min_weight: float = 0.0,
    max_weight: float = 1.0,
    *,
    max_iter: int = 100,
) -> np.ndarray:
    """Euclidean projection onto sum(w)=1 and uniform long-only box bounds.

    Capital-weight projection can change risk budgets; this is not a constrained
    risk-budgeting solver.
    """
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1 or len(w) == 0 or not np.all(np.isfinite(w)):
        raise ValueError("risk_budget_projection_weights_invalid")
    if (
        not math.isfinite(min_weight)
        or not math.isfinite(max_weight)
        or not 0 <= min_weight <= max_weight <= 1
    ):
        raise ValueError("risk_budget_projection_bounds_invalid")
    if min_weight * len(w) > 1 or max_weight * len(w) < 1:
        raise ValueError("risk_budget_projection_bounds_infeasible")
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or max_iter < 1:
        raise ValueError("risk_budget_projection_iteration_limit_invalid")
    # KKT solution: clip(w - threshold, lower, upper). Normalizing beforehand
    # changes the distance objective and can violate the bounds.
    left = float(np.min(w - max_weight))
    right = float(np.max(w - min_weight))
    for _ in range(max_iter):
        threshold = left * 0.5 + right * 0.5
        projected = np.clip(w - threshold, min_weight, max_weight)
        error = float(projected.sum()) - 1
        if abs(error) <= 1e-12:
            return projected
        if error > 0:
            left = threshold
        else:
            right = threshold
    raise ValueError("risk_budget_projection_not_converged")
