"""Frozen-checkpoint uncertainty for paired, after-cost session returns."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from server.contracts.content_identity import content_fingerprint


def compare_session_curves(
    *,
    candidate: Sequence[Sequence[Any]],
    comparators: Mapping[str, Sequence[Sequence[Any]]],
    initial_cash: Any,
    policy: Mapping[str, Any],
    seed: str,
) -> dict[str, Any]:
    """One-sided moving-block bounds, paired on identical session dates.

    The checkpoint and per-attempt alpha are frozen before observation. Alpha
    is split across every declared comparator, including the incumbent. A failed
    sample is still a consumed attempt; callers own the durable budget.
    """
    cash = float(initial_cash)
    if not math.isfinite(cash) or cash <= 0 or not comparators:
        raise ValueError("deployment_curve_initial_cash_or_comparators_invalid")

    def returns(curve):
        days, values = [], [cash]
        for stamp, amount in curve:
            day = str(stamp)[:10]
            value = float(amount)
            if (days and day <= days[-1]) or not math.isfinite(value) or value <= 0:
                raise ValueError("deployment_curve_invalid")
            days.append(day)
            values.append(value)
        return days, np.diff(np.log(np.array(values)))

    dates, strategy = returns(candidate)
    minimum = int(policy["minimum_observations"])
    block = int(policy["block_length"])
    effective = len(dates) // block
    alpha = float(policy["significance_level"]) / len(comparators)
    samples = int(policy["bootstrap_samples"])
    if not 0 < alpha < 1 or block < 1 or samples < 1:
        raise ValueError("deployment_statistical_profile_invalid")
    blockers = []
    if (
        len(dates) < minimum
        or effective < int(policy["minimum_effective_blocks"])
        or samples * alpha < 20
        or not dates
        or dates[-1] != policy["decision_checkpoint"]
    ):
        blockers.append("deployment_independent_sample_insufficient")
    comparisons = []
    for label, curve in sorted(comparators.items()):
        other_dates, benchmark = returns(curve)
        if dates != other_dates:
            raise ValueError("deployment_comparator_interval_mismatch")
        excess = strategy - benchmark
        lower = None
        if not blockers:
            rng = np.random.default_rng(
                int(content_fingerprint({"seed": seed, "comparator": label})[:16], 16)
            )
            # Circular blocks retain local serial dependence; the same indices
            # are applied to candidate and comparator through paired differences.
            estimates = np.empty(samples)
            count = math.ceil(len(excess) / block)
            offsets = np.arange(block)
            for start in range(0, samples, 256):
                size = min(256, samples - start)
                starts = rng.integers(0, len(excess), size=(size, count))
                indices = ((starts[..., None] + offsets) % len(excess)).reshape(
                    size, -1
                )[:, : len(excess)]
                estimates[start : start + size] = excess[indices].mean(axis=1)
            lower_mean = 2 * float(excess.mean()) - float(
                np.quantile(estimates, 1 - alpha, method="higher")
            )
            lower = float(np.expm1(lower_mean * len(excess)))
        comparisons.append(
            {
                "label": label,
                "paired_observations": len(dates),
                "relative_net_excess": float(np.expm1(float(excess.sum()))),
                "net_excess_lower_bound": lower,
                "one_sided_alpha": alpha,
            }
        )
    if not blockers and any(
        item["net_excess_lower_bound"] <= float(policy["minimum_net_excess"])
        for item in comparisons
    ):
        blockers.append("deployment_net_excess_not_established")
    core = {
        "schema_version": "karkinos.deployment_uncertainty.v1",
        "method": policy["method"],
        "status": "pass" if not blockers else "insufficient_evidence",
        "policy": dict(policy),
        "observation_count": len(dates),
        "effective_blocks": effective,
        "comparisons": comparisons,
        "blockers": blockers,
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}
