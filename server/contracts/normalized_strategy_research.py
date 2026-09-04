"""Canonical constants for normalized, strategy-only research."""

from __future__ import annotations

CANONICAL_COST_MODEL_REFERENCE = "karkinos.backtest.multi_asset_commission.default.v1"
NORMALIZED_RESEARCH_NOTIONAL = 1_000_000.0
NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID = (
    "karkinos.ai.normalized_research_notional.cny_1m.v1"
)

__all__ = [
    "CANONICAL_COST_MODEL_REFERENCE",
    "NORMALIZED_RESEARCH_NOTIONAL",
    "NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID",
]
