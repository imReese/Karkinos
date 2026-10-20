"""Shared utilities and policy functions for AI shadow research.

Canonical module in server.services.ai_shadow.
"""

from __future__ import annotations

from server.services.ai_shadow.ai_shadow_research_support import (
    AiShadowResearchSupportMixin,
    NullShadowResearchEventBus,
    is_after_shadow_research_close,
    shadow_research_asset_class,
    shadow_research_backtest_source_fingerprint,
    shadow_research_critique_usage,
    shadow_research_failure_code,
    shadow_research_hypothesis_usage,
    shadow_research_market_close_as_of,
    shadow_research_usage_tokens,
)

__all__ = [
    "AiShadowResearchSupportMixin",
    "NullShadowResearchEventBus",
    "is_after_shadow_research_close",
    "shadow_research_asset_class",
    "shadow_research_backtest_source_fingerprint",
    "shadow_research_critique_usage",
    "shadow_research_failure_code",
    "shadow_research_hypothesis_usage",
    "shadow_research_market_close_as_of",
    "shadow_research_usage_tokens",
]
