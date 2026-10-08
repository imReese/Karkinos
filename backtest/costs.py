"""Explicit simulation friction assumptions for frozen research comparisons."""

from __future__ import annotations

from decimal import Decimal

# Explicit research assumptions, not observations of broker execution or impact.
RESEARCH_SLIPPAGE_BPS = Decimal("5")
RESEARCH_MAX_VOLUME_PARTICIPATION = Decimal("0.01")
RESEARCH_COST_STRESS_BPS = (Decimal("10"), Decimal("25"))


def research_friction_assumptions(
    slippage_bps: Decimal = RESEARCH_SLIPPAGE_BPS,
) -> dict[str, str]:
    return {
        "execution_cost_model_id": "karkinos.research.percent_slippage.volume_cap.v1",
        "slippage_model": "percent_of_reference_price",
        "slippage_bps": str(slippage_bps),
        "max_volume_participation": str(RESEARCH_MAX_VOLUME_PARTICIPATION),
        "unfilled_remainder_policy": "cancel_after_one_execution_attempt",
        "calibration": "explicit_research_assumption",
    }
