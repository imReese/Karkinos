"""Frozen-checkpoint uncertainty for paired, after-cost session returns."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from typing import Any

import numpy as np

from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from server.contracts.content_identity import content_fingerprint
from server.contracts.recommendation_publication import (
    is_final_statistical_policy,
    publication_number,
    validate_final_statistical_policy,
)


def compare_session_curves(
    *,
    candidate: Sequence[Sequence[Any]],
    comparators: Mapping[str, Sequence[Sequence[Any]]],
    initial_cash: Any,
    policy: Mapping[str, Any],
    seed: str,
    policy_fingerprint: str | None = None,
    comparator_bindings: Mapping[str, Mapping[str, Any]] | None = None,
    effective_checkpoint: str | None = None,
) -> dict[str, Any]:
    """One-sided moving-block bounds, paired on identical session dates.

    The checkpoint and per-attempt alpha are frozen before observation. Alpha
    is split across every declared comparator, including the incumbent. A failed
    sample is still a consumed attempt; callers own the durable budget.

    V2 additionally requires the caller's verified executable identities and
    effective calendar checkpoint. These matching inputs do not themselves
    prove source provenance, timely settlement, grant authority or budget.
    """
    cash = float(initial_cash)
    if not math.isfinite(cash) or cash <= 0 or not comparators:
        raise ValueError("deployment_curve_initial_cash_or_comparators_invalid")
    primary_comparator = is_final_statistical_policy(policy)
    if primary_comparator:
        validate_final_statistical_policy(policy, policy_fingerprint or "")
        if comparator_bindings != policy["comparator_bindings"] or set(
            comparators
        ) != set(policy["comparator_bindings"]):
            raise ValueError("deployment_comparator_identity_binding_mismatch")
        from datetime import date

        try:
            checkpoint = date.fromisoformat(effective_checkpoint or "")
        except ValueError as exc:
            raise ValueError("deployment_effective_checkpoint_required") from exc
        if checkpoint > date.fromisoformat(policy["decision_checkpoint"]):
            raise ValueError("deployment_effective_checkpoint_after_frozen_deadline")
    elif (
        policy.get("schema_version") is not None
        or {
            "primary_comparator",
            "comparator_bindings",
            "research_policy_fingerprint",
            "minimum_candidate_net_return",
            "minimum_annualized_relative_wealth",
            "maximum_drawdown",
        }.intersection(policy)
        or policy_fingerprint is not None
        or comparator_bindings is not None
        or effective_checkpoint is not None
    ):
        raise ValueError("deployment_statistical_policy_version_unsupported")

    def returns(curve):
        days: list[str] = []
        values = [cash]
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
        or dates[-1]
        != (
            effective_checkpoint
            if primary_comparator
            else policy["decision_checkpoint"]
        )
    ):
        blockers.append("deployment_independent_sample_insufficient")
    comparisons: list[dict[str, Any]] = []
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
    future_metrics = None
    if primary_comparator:
        primary = next(
            row for row in comparisons if row["label"] == policy["primary_comparator"]
        )
        if not blockers and primary["net_excess_lower_bound"] <= float(
            policy["minimum_net_excess"]
        ):
            blockers.append("deployment_primary_net_excess_not_established")
        net_return = drawdown = annual_relative = None
        if dates:
            # Reuse the financial drawdown owner, including original cash as
            # the initial peak; decimal point gates do not inherit float error
            # from the bootstrap's statistical log-return calculation.
            drawdown_evidence = build_backtest_drawdown_evidence(
                equity_curve=candidate, initial_cash=initial_cash
            )
            if drawdown_evidence["status"] != "complete":
                raise ValueError("deployment_candidate_drawdown_inputs_invalid")
            drawdown = Decimal(drawdown_evidence["max_drawdown_pct"])
            with localcontext() as context:
                context.prec = 42
                terminal = publication_number(candidate[-1][1])
                baseline_terminal = publication_number(
                    comparators[policy["primary_comparator"]][-1][1]
                )
                net_return = terminal / publication_number(initial_cash) - 1
                annual_relative = (terminal / baseline_terminal) ** (
                    Decimal(252) / len(dates)
                ) - 1
        if net_return is None or net_return <= publication_number(
            policy["minimum_candidate_net_return"]
        ):
            blockers.append("deployment_candidate_net_return_not_positive")
        if annual_relative is None or annual_relative < publication_number(
            policy["minimum_annualized_relative_wealth"]
        ):
            blockers.append("deployment_primary_relative_growth_below_floor")
        if drawdown is not None and drawdown > publication_number(
            policy["maximum_drawdown"]
        ):
            blockers.append("deployment_candidate_drawdown_budget_exceeded")
        future_metrics = {
            "candidate_net_return": str(net_return) if net_return is not None else None,
            "candidate_max_drawdown": str(drawdown) if drawdown is not None else None,
            "primary_annualized_relative_wealth": str(annual_relative)
            if annual_relative is not None
            else None,
        }
    elif not blockers and any(
        item["net_excess_lower_bound"] <= float(policy["minimum_net_excess"])
        for item in comparisons
    ):
        blockers.append("deployment_net_excess_not_established")
    core = {
        "schema_version": "karkinos.deployment_uncertainty.v2"
        if primary_comparator
        else "karkinos.deployment_uncertainty.v1",
        "method": policy["method"],
        "status": "pass" if not blockers else "insufficient_evidence",
        "policy": dict(policy),
        "observation_count": len(dates),
        "effective_blocks": effective,
        "comparisons": comparisons,
        "blockers": blockers,
    }
    if primary_comparator:
        core.update(
            policy_fingerprint=policy_fingerprint,
            comparator_bindings=dict(comparator_bindings or {}),
            effective_checkpoint=effective_checkpoint,
            future_metrics=future_metrics,
            authority_effect="none",
        )
    return {**core, "evidence_fingerprint": content_fingerprint(core)}
