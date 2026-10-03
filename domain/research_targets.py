"""Portfolio-owned target allocation for an independent research observation."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction

RESEARCH_TARGET_POLICY_ID = "karkinos.research.target_weights.capped_proportional.v1"
_WEIGHT_UNITS = 100_000_000


def build_research_target_weights(
    desired_weights: Mapping[str, Decimal],
    *,
    max_symbol_weight: Decimal,
    max_gross_weight: Decimal,
) -> dict[str, Decimal]:
    """Cap each long-only target, then proportionally cap gross exposure.

    Eight-decimal weights are rounded down using exact rational arithmetic.
    This keeps the total within its bound even at rounding boundaries and does
    not depend on the caller's Decimal context. No cash, holdings or fills are
    inferred from these desired weights.
    """

    for name, limit in (
        ("max_symbol_weight", max_symbol_weight),
        ("max_gross_weight", max_gross_weight),
    ):
        if not _valid_weight(limit) or limit > 1:
            raise ValueError(f"research_target_{name}_invalid")
    if not desired_weights:
        raise ValueError("research_target_universe_empty")
    capped = {}
    for symbol, weight in desired_weights.items():
        if not isinstance(symbol, str) or not symbol or symbol.strip() != symbol:
            raise ValueError("research_target_symbol_invalid")
        if not _valid_weight(weight):
            raise ValueError("research_target_weight_invalid")
        capped[symbol] = Fraction(min(weight, max_symbol_weight))
    gross = sum(capped.values(), Fraction(0))
    scale = min(Fraction(1), Fraction(max_gross_weight) / gross) if gross else 1
    result = {}
    for symbol in sorted(capped):
        scaled_units = capped[symbol] * scale * _WEIGHT_UNITS
        units = scaled_units.numerator // scaled_units.denominator
        # Decimal(tuple) is exact even when the ambient context is restrictive.
        result[symbol] = Decimal((0, tuple(map(int, str(units))), -8))
    return result


def _valid_weight(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0
