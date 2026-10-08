"""Exploratory benchmark-relative metrics for aligned simple period returns.

Inputs must already share return basis, currency, periods and cost treatment.
This helper neither models distributions/external cash flows nor verifies those
semantics. Annualization assumes equally spaced, non-overlapping samples and
uses the caller's periods-per-year assumption, not elapsed calendar time.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BenchmarkRelativeMetrics:
    """Research estimates; unavailable/undefined metrics are None, not zero proof."""

    annualized_excess_return: float | None
    tracking_error: float | None
    information_ratio: float | None
    relative_max_drawdown: float | None
    capm_alpha: float | None
    capm_beta: float | None
    outperformance_ratio: float | None
    sample_periods: int
    periods_per_year: int
    risk_free_rate: float

    def to_json_dict(self) -> dict:
        return asdict(self)


def _returns(
    portfolio: pd.Series, benchmark: pd.Series
) -> tuple[np.ndarray, np.ndarray]:
    for series in (portfolio, benchmark):
        if not isinstance(series, pd.Series) or not isinstance(
            series.index, pd.DatetimeIndex
        ):
            raise ValueError("benchmark_returns_dated_series_required")
        if (
            series.index.hasnans
            or not series.index.is_unique
            or not series.index.is_monotonic_increasing
        ):
            raise ValueError("benchmark_returns_index_invalid")
        if np.iscomplexobj(series.to_numpy()) or any(
            isinstance(value, (bool, np.bool_)) for value in series
        ):
            raise ValueError("benchmark_returns_values_invalid")
    if not portfolio.index.equals(benchmark.index):
        raise ValueError("benchmark_returns_periods_not_aligned")
    try:
        rp, rb = portfolio.to_numpy(dtype=float), benchmark.to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("benchmark_returns_values_invalid") from exc
    if not np.isfinite(rp).all() or not np.isfinite(rb).all():
        raise ValueError("benchmark_returns_values_invalid")
    if np.any(rp < -1) or np.any(rb < -1):
        raise ValueError("benchmark_returns_below_total_loss")
    # Simple returns cannot describe recovery after a zero-wealth book without
    # external funding. A final total loss remains a valid return observation.
    if np.any(rp[:-1] == -1) or np.any(rb[:-1] == -1):
        raise ValueError("benchmark_returns_after_total_loss")
    return rp, rb


def _relative_drawdown(rp: np.ndarray, rb: np.ndarray) -> float | None:
    if len(rp) == 0 or np.any(rb == -1):
        return None
    if np.any(rp == -1):
        return 1.0
    # log relative wealth avoids overflow and retains the initial wealth of 1,
    # including when the very first period underperforms the benchmark.
    relative = np.concatenate(([0.0], np.cumsum(np.log1p(rp) - np.log1p(rb))))
    drawdown = -np.expm1(relative - np.maximum.accumulate(relative))
    return float(np.max(drawdown))


def evaluate_benchmark_relative(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    *,
    risk_free_rate: float,
    periods_per_year: int,
) -> BenchmarkRelativeMetrics:
    """Evaluate same-period returns; do not silently join, drop or truncate rows.

    ``annualized_excess_return`` is arithmetic mean(Rp-Rb) times frequency,
    not a difference of CAGRs. Tracking error is sample std(Rp-Rb)*sqrt(frequency).
    IR is that arithmetic active return divided by tracking error. Relative
    drawdown uses cumulative portfolio wealth divided by benchmark wealth.

    ``risk_free_rate`` is an explicit effective annual constant; its equivalent
    period return is (1+rf)**(1/frequency)-1. CAPM alpha is the OLS period intercept
    times frequency, and beta is the OLS slope of excess portfolio on excess
    benchmark returns. Fewer than three observations or a constant benchmark
    cannot support this regression. These estimates do not establish skill.
    """
    if (
        isinstance(periods_per_year, bool)
        or not isinstance(periods_per_year, int)
        or periods_per_year <= 0
    ):
        raise ValueError("benchmark_periods_per_year_invalid")
    if (
        isinstance(risk_free_rate, bool)
        or not isinstance(risk_free_rate, (int, float))
        or not math.isfinite(risk_free_rate)
        or risk_free_rate <= -1
    ):
        raise ValueError("benchmark_risk_free_rate_invalid")
    rp, rb = _returns(portfolio_returns, benchmark_returns)
    n = len(rp)
    active = rp - rb
    annual_active = float(active.mean()) * periods_per_year if n else None
    te = float(np.std(active, ddof=1)) * math.sqrt(periods_per_year) if n >= 2 else None
    # Floating subtraction can leave tiny residuals for identical active returns.
    if n >= 2 and float(np.ptp(active)) <= np.finfo(float).eps * max(
        1.0, float(np.max(np.abs(active)))
    ):
        te = 0.0
    ir = (
        annual_active / te
        if annual_active is not None and te is not None and te > 0
        else None
    )
    alpha, beta = None, None
    if n >= 3 and float(np.ptp(rb)) > np.finfo(float).eps * max(
        1.0, float(np.max(np.abs(rb)))
    ):
        rf_period = math.expm1(math.log1p(risk_free_rate) / periods_per_year)
        x, y = rb - rf_period, rp - rf_period
        centered_x, centered_y = x - x.mean(), y - y.mean()
        beta = float(np.dot(centered_x, centered_y) / np.dot(centered_x, centered_x))
        alpha = float(y.mean() - beta * x.mean()) * periods_per_year
    metrics = BenchmarkRelativeMetrics(
        annualized_excess_return=annual_active,
        tracking_error=te,
        information_ratio=ir,
        relative_max_drawdown=_relative_drawdown(rp, rb),
        capm_alpha=alpha,
        capm_beta=beta,
        outperformance_ratio=float(np.mean(active > 0)) if n else None,
        sample_periods=n,
        periods_per_year=periods_per_year,
        risk_free_rate=float(risk_free_rate),
    )
    if any(
        isinstance(value, float) and not math.isfinite(value)
        for value in metrics.to_json_dict().values()
    ):
        raise ValueError("benchmark_metric_numeric_overflow")
    return metrics
