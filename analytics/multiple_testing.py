"""Deterministic multiple-testing and backtest-overfitting corrections.

These are pure, provider-free statistical primitives for AI strategy research.
They never register a strategy, mutate authority, or grant execution; they only
produce inspectable statistical evidence under each method's assumptions.

Implemented methods:

* Holm-Bonferroni family-wise error control over a family of p-values.
* Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).
* Probability of Backtest Overfitting via Combinatorially Symmetric
  Cross-Validation (CSCV).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

MULTIPLE_TESTING_EVIDENCE_SCHEMA_VERSION = "karkinos.multiple_testing_correction.v1"

_EULER_GAMMA = 0.5772156649015328606

# Acklam inverse-normal-CDF coefficients (accuracy ~1.15e-9).
_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _inverse_normal_cdf(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError("probability must be in (0, 1)")
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        num = ((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]
        den = (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        return num / den
    if p <= p_high:
        q = p - 0.5
        r = q * q
        num = ((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]
        den = ((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0
        return num * q / den
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    num = ((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]
    den = (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
    return -num / den


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return normalized if math.isfinite(normalized) else None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _with_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "evidence_fingerprint": _fingerprint(payload)}


def build_holm_bonferroni(
    pvalues: Sequence[float],
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Holm-Bonferroni step-down family-wise error control.

    ``pvalues`` is one family of independent p-values for the hypotheses under
    test.  Returns per-test adjusted thresholds and the largest step index that
    still rejects under FWER ``alpha``.
    """

    if not pvalues:
        raise ValueError("pvalues must be non-empty")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    family_size = len(pvalues)
    ranked = sorted(enumerate(pvalues), key=lambda pair: pair[1])
    tests: list[dict[str, Any]] = []
    rejected_count = 0
    for step, (index, raw_p) in enumerate(ranked, start=1):
        pvalue = _finite(raw_p)
        if pvalue is None or not 0.0 <= pvalue <= 1.0:
            raise ValueError("pvalues must be finite probabilities in [0, 1]")
        adjusted_alpha = alpha / (family_size - step + 1)
        rejects = pvalue <= adjusted_alpha
        # Holm rejects the smallest k p-values in order until the first failure.
        if rejects and rejected_count == step - 1:
            rejected_count = step
        tests.append(
            {
                "index": index,
                "pvalue": pvalue,
                "adjusted_alpha": adjusted_alpha,
                "rejects": rejects,
            }
        )
    return _with_fingerprint(
        {
            "schema_version": MULTIPLE_TESTING_EVIDENCE_SCHEMA_VERSION,
            "method": "holm_bonferroni",
            "family_size": family_size,
            "alpha": alpha,
            "rejected_count": rejected_count,
            "tests": tests,
            "limitations": [
                "Holm-Bonferroni controls the family-wise error rate under independence or arbitrary dependence.",
                "A p-value family is only meaningful when every semantic candidate enters it exactly once.",
            ],
        }
    )


def _expected_max_sharpe(num_trials: int, standard_error: float) -> float:
    if num_trials <= 1:
        return 0.0
    term = (1.0 - _EULER_GAMMA) * _inverse_normal_cdf(1.0 - 1.0 / num_trials) + (
        _EULER_GAMMA * _inverse_normal_cdf(1.0 - 1.0 / (num_trials * math.e))
    )
    return standard_error * term


def build_deflated_sharpe(
    *,
    observed_sharpe: float,
    num_periods: int,
    num_trials: int,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> dict[str, Any]:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    ``excess_kurtosis`` is the fourth standardized moment minus three (zero for
    a Normal distribution).  ``num_trials`` is the number of independent trials
    that were searched to reach this candidate.
    """

    if num_periods <= 1:
        raise ValueError("num_periods must be greater than 1")
    if num_trials < 1:
        raise ValueError("num_trials must be at least 1")
    observed = _finite(observed_sharpe)
    gamma3 = _finite(skewness)
    gamma4_excess = _finite(excess_kurtosis)
    if observed is None or gamma3 is None or gamma4_excess is None:
        raise ValueError("numeric inputs must be finite")
    gamma4 = gamma4_excess + 3.0
    variance_term = 1.0 - gamma3 * observed + ((gamma4 - 1.0) / 4.0) * observed**2
    standard_error = math.sqrt(max(variance_term, 1e-12) / (num_periods - 1))
    expected_max = _expected_max_sharpe(num_trials, standard_error)
    deflated = _normal_cdf((observed - expected_max) / standard_error)
    return _with_fingerprint(
        {
            "schema_version": MULTIPLE_TESTING_EVIDENCE_SCHEMA_VERSION,
            "method": "deflated_sharpe",
            "observed_sharpe": observed,
            "num_periods": num_periods,
            "num_trials": num_trials,
            "skewness": gamma3,
            "excess_kurtosis": gamma4_excess,
            "expected_max_sharpe": expected_max,
            "deflated_sharpe": deflated,
            "significant_at_0.95": deflated >= 0.95,
            "limitations": [
                "DSR corrects for the number of trials and return non-normality, not for data-snooping that reuses the same holdout.",
                "DSR assumes trials are independent and that the trial family is complete.",
            ],
        }
    )


def build_return_series_trial_correction(
    equity_curve: Sequence[Any],
    trial_fingerprints: Sequence[str],
) -> dict[str, Any]:
    """Estimate DSR from adjacent-period returns and a nominal trial family.

    Accept engine ``(datetime, equity)`` points or persisted mappings containing
    ``timestamp`` and ``equity``. Do not sort, drop invalid points, annualize, or
    infer missing trials. Sample variance uses ``ddof=1``; skewness and excess
    kurtosis use empirical central moments. Four returns are the computational
    minimum, not a claim that the observation window is statistically sufficient.

    Fingerprints identify distinct supplied trials, not independent trials. The
    result is a nominal-count approximation using the existing DSR primitive;
    trial correlation and the across-trial Sharpe variance are not supplied.
    """

    payload: dict[str, Any] = {
        "schema_version": MULTIPLE_TESTING_EVIDENCE_SCHEMA_VERSION,
        "method": "return_series_deflated_sharpe",
        "status": "unavailable",
        "blockers": [],
        "trial_fingerprints": [],
        "nominal_trial_count": 0,
        "independent_trial_count": None,
        "trial_count_model": "nominal_trials_treated_as_independent",
        "trial_sharpe_dispersion_model": "candidate_return_moments_sampling_error",
        "trial_family_completeness": "not_verified",
        "equity_curve_fingerprint": None,
        "return_series_fingerprint": None,
        "return_moments": None,
        "dsr": None,
        "significant_at_0_95": None,
        "limitations": [
            "Distinct fingerprints count supplied nominal trials; they do not establish independence or a complete search history.",
            "Trial correlation is unknown. The nominal count is used in the independent-trial DSR approximation; it is not an estimated effective trial count.",
            "Expected maximum Sharpe uses this candidate's estimated sampling error, not the unobserved across-trial Sharpe dispersion.",
            "Returns are adjacent observation-period simple returns with a zero risk-free return; no annualization or serial-dependence adjustment is applied.",
            "The caller must supply a consistent observation grid and an equity series without external cash flows, or a cash-flow-adjusted NAV series.",
            "Four returns permit moment calculation but do not establish a sufficient observation horizon or reliable tail estimates.",
            "This correction does not repair reused holdouts, missing trials, look-ahead bias, or prove investment profitability.",
        ],
    }
    if not isinstance(trial_fingerprints, Sequence) or isinstance(
        trial_fingerprints, (str, bytes)
    ):
        payload["blockers"].append("trial_fingerprints_missing")
    elif not trial_fingerprints:
        payload["blockers"].append("trial_fingerprints_missing")
    elif any(
        not isinstance(item, str) or not item.strip() for item in trial_fingerprints
    ):
        payload["blockers"].append("trial_fingerprint_invalid")
    else:
        fingerprints = sorted({item.strip() for item in trial_fingerprints})
        payload["trial_fingerprints"] = fingerprints
        payload["nominal_trial_count"] = len(fingerprints)

    try:
        points = _validated_equity_points(equity_curve)
    except ValueError as exc:
        payload["blockers"].append(str(exc))
        return _with_fingerprint(payload)
    payload["equity_curve_fingerprint"] = _fingerprint({"points": points})
    returns = [
        current[1] / previous[1] - 1.0
        for previous, current in itertools.pairwise(points)
    ]
    if any(not math.isfinite(value) for value in returns):
        payload["blockers"].append("period_return_not_finite")
        return _with_fingerprint(payload)
    payload["return_series_fingerprint"] = _fingerprint({"returns": returns})
    if len(returns) < 4:
        payload["blockers"].append("insufficient_return_periods")
        return _with_fingerprint(payload)
    # Constant proportional growth can acquire roundoff noise during division.
    if max(returns) - min(returns) <= 32 * math.ulp(
        max(1.0, *(abs(value) for value in returns))
    ):
        payload["blockers"].append("constant_return_series")
        return _with_fingerprint(payload)
    try:
        count = len(returns)
        mean = math.fsum(returns) / count
        centered = [value - mean for value in returns]
        moment_2 = math.fsum(value**2 for value in centered) / count
        variance = moment_2 * count / (count - 1)
        stddev = math.sqrt(variance)
        standardized = [value / math.sqrt(moment_2) for value in centered]
        skewness = math.fsum(value**3 for value in standardized) / count
        excess_kurtosis = math.fsum(value**4 for value in standardized) / count - 3.0
        observed_sharpe = mean / stddev
        if not all(
            math.isfinite(value)
            for value in (
                mean,
                variance,
                stddev,
                skewness,
                excess_kurtosis,
                observed_sharpe,
            )
        ):
            raise ValueError("return_moments_not_finite")
    except (ValueError, OverflowError, ZeroDivisionError):
        payload["blockers"].append("return_moments_not_finite")
        return _with_fingerprint(payload)
    payload["return_moments"] = {
        "num_periods": count,
        "mean": mean,
        "sample_variance": variance,
        "sample_stddev": stddev,
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "observed_sharpe_per_period": observed_sharpe,
        "risk_free_return_per_period": 0.0,
        "moment_estimator": "sample_variance_ddof_1_empirical_standardized_moments",
    }
    if payload["blockers"]:
        return _with_fingerprint(payload)
    correction = build_deflated_sharpe(
        observed_sharpe=observed_sharpe,
        num_periods=count,
        num_trials=payload["nominal_trial_count"],
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
    )
    payload.update(
        status="assessed",
        dsr=correction,
        significant_at_0_95=correction["significant_at_0.95"],
    )
    return _with_fingerprint(payload)


def _validated_equity_points(equity_curve: Sequence[Any]) -> list[tuple[str, float]]:
    if not isinstance(equity_curve, Sequence) or isinstance(equity_curve, (str, bytes)):
        raise ValueError("equity_curve_missing")
    if not equity_curve:
        raise ValueError("equity_curve_missing")
    points: list[tuple[str, float]] = []
    previous: datetime | None = None
    for point in equity_curve:
        if isinstance(point, Mapping):
            raw_timestamp, raw_equity = point.get("timestamp"), point.get("equity")
        elif isinstance(point, (tuple, list)) and len(point) == 2:
            raw_timestamp, raw_equity = point
        else:
            raise ValueError("equity_curve_point_invalid")
        try:
            timestamp = (
                raw_timestamp
                if isinstance(raw_timestamp, datetime)
                else datetime.fromisoformat(raw_timestamp)
            )
        except (TypeError, ValueError):
            raise ValueError("equity_curve_timestamp_invalid") from None
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc)
        if previous is not None:
            if (timestamp.tzinfo is None) != (previous.tzinfo is None):
                raise ValueError("equity_curve_mixed_timezone_awareness")
            if timestamp <= previous:
                raise ValueError("equity_curve_not_strictly_increasing")
        equity = _finite(raw_equity)
        if equity is None or equity <= 0:
            raise ValueError("equity_curve_value_invalid")
        points.append((timestamp.isoformat(), equity))
        previous = timestamp
    return points


def _sharpe_performance(period_returns: Sequence[float]) -> float:
    values = [float(item) for item in period_returns]
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    std = math.sqrt(variance)
    if std <= 1e-12:
        return 0.0
    return mean / std


def build_probability_of_backtest_overfitting(
    returns: Sequence[Sequence[float]],
    *,
    num_blocks: int = 16,
    performance_fn: Callable[[Sequence[float]], float] | None = None,
) -> dict[str, Any]:
    """Probability of Backtest Overfitting via CSCV.

    ``returns`` is a matrix ``[num_periods][num_trials]`` of period returns.
    The default performance metric is the per-trial Sharpe ratio.  Returns the
    fraction of CSCV splits where the in-sample best trial lands in the worse
    half out-of-sample, plus the logit and the relative-rank mean.
    """

    if num_blocks < 4 or num_blocks % 2 != 0:
        raise ValueError("num_blocks must be an even integer >= 4")
    performance = performance_fn or _sharpe_performance
    num_periods = len(returns)
    num_trials = len(returns[0]) if returns else 0
    if num_periods < 2 * num_blocks:
        raise ValueError("returns must contain at least 2*num_blocks periods")
    if num_trials < 2:
        raise ValueError("returns must contain at least 2 trials")
    for row in returns:
        if len(row) != num_trials:
            raise ValueError("returns rows must be equal length")

    block_size = num_periods // num_blocks
    blocks = [
        returns[index * block_size : (index + 1) * block_size]
        for index in range(num_blocks)
    ]

    def _trial_series(block_indices: Sequence[int]) -> list[list[float]]:
        rows = [
            period for block_index in block_indices for period in blocks[block_index]
        ]
        return [[float(row[trial]) for row in rows] for trial in range(num_trials)]

    relative_ranks: list[float] = []
    for in_sample_blocks in itertools.combinations(range(num_blocks), num_blocks // 2):
        out_of_sample_blocks = [
            index for index in range(num_blocks) if index not in in_sample_blocks
        ]
        in_sample = _trial_series(in_sample_blocks)
        out_of_sample = _trial_series(out_of_sample_blocks)
        in_sample_perf = [performance(series) for series in in_sample]
        best_trial = max(range(num_trials), key=lambda index: in_sample_perf[index])
        out_of_sample_perf = [performance(series) for series in out_of_sample]
        best_oos = out_of_sample_perf[best_trial]
        worse_count = sum(1 for value in out_of_sample_perf if value < best_oos)
        # relative_rank = 1.0 means IS-best is OOS-best; 0.0 means OOS-worst.
        relative_ranks.append(worse_count / (num_trials - 1))

    # PBO: the IS-best lands in the worse half out-of-sample (rank below 0.5).
    overfit_fraction = sum(1 for rank in relative_ranks if rank < 0.5) / len(
        relative_ranks
    )
    return _with_fingerprint(
        {
            "schema_version": MULTIPLE_TESTING_EVIDENCE_SCHEMA_VERSION,
            "method": "probability_of_backtest_overfitting",
            "num_periods": num_periods,
            "num_trials": num_trials,
            "num_blocks": num_blocks,
            "cscv_split_count": len(relative_ranks),
            "probability_of_backtest_overfitting": overfit_fraction,
            "mean_relative_rank": (
                sum(relative_ranks) / len(relative_ranks) if relative_ranks else 0.0
            ),
            "limitations": [
                "PBO measures the risk that the in-sample best trial degrades out-of-sample; it is not a profitability guarantee.",
                "PBO requires a complete trial family over the same period grid.",
            ],
        }
    )


__all__ = [
    "MULTIPLE_TESTING_EVIDENCE_SCHEMA_VERSION",
    "build_holm_bonferroni",
    "build_deflated_sharpe",
    "build_return_series_trial_correction",
    "build_probability_of_backtest_overfitting",
]
