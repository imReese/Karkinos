"""Independent long-only exposure checks without changing portfolio targets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from fractions import Fraction
from typing import Any

TARGET_LIMITS_POLICY_ID = "karkinos.research.target_limits.long_only.v1"


def evaluate_target_limits(
    target_weights: Mapping[str, Decimal],
    *,
    frozen_universe: Sequence[str],
    max_symbol_weight: Decimal,
    max_gross_weight: Decimal,
) -> dict[str, Any]:
    """Check the entire frozen universe and exact exposure, without rescaling."""

    reasons: list[str] = []
    universe_valid = (
        not isinstance(frozen_universe, (str, bytes))
        and bool(frozen_universe)
        and all(
            isinstance(symbol, str) and symbol and symbol.strip() == symbol
            for symbol in frozen_universe
        )
        and len(set(frozen_universe)) == len(frozen_universe)
    )
    if not universe_valid:
        reasons.append("target_frozen_universe_invalid")
    elif set(target_weights) != set(frozen_universe):
        reasons.append("target_universe_mismatch")
    limits_valid = True
    for name, limit in (
        ("max_symbol_weight", max_symbol_weight),
        ("max_gross_weight", max_gross_weight),
    ):
        if not _valid_weight(limit) or limit > 1:
            reasons.append(f"target_{name}_invalid")
            limits_valid = False
    weights_valid = all(_valid_weight(weight) for weight in target_weights.values())
    if not weights_valid:
        reasons.append("target_weight_invalid")
    gross = None
    if weights_valid:
        gross = sum(
            (Fraction(weight) for weight in target_weights.values()), Fraction(0)
        )
        if limits_valid:
            if any(weight > max_symbol_weight for weight in target_weights.values()):
                reasons.append("target_symbol_limit_exceeded")
            if gross > Fraction(max_gross_weight):
                reasons.append("target_gross_limit_exceeded")
    return {
        "policy_id": TARGET_LIMITS_POLICY_ID,
        "status": "blocked" if reasons else "allowed",
        "reasons": reasons,
        "gross_weight": _exact_decimal_sum(target_weights.values())
        if gross is not None
        else None,
        "max_symbol_weight": str(max_symbol_weight),
        "max_gross_weight": str(max_gross_weight),
        "scope": "research_target_observation",
        "authorizes_execution": False,
    }


def _valid_weight(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def _exact_decimal_sum(weights: Iterable[Decimal]) -> str:
    """Render a finite Decimal sum exactly without ambient-context rounding."""
    values = list(weights)
    exponent = min((int(weight.as_tuple().exponent) for weight in values), default=0)
    units = sum(
        int("".join(map(str, weight.as_tuple().digits)))
        * 10 ** (int(weight.as_tuple().exponent) - exponent)
        for weight in values
    )
    return format(Decimal((0, tuple(map(int, str(units))), exponent)), "f")
