"""Market universe truth resolution, membership, and panel construction.

Canonical module in server.services.market.
"""

from __future__ import annotations

from server.services.market.market_universe_truth import (
    FULL_MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION,
    LEGACY_MARKET_UNIVERSE_POLICY_VERSION,
    MARKET_UNIVERSE_POLICY_VERSION,
    MARKET_UNIVERSE_SNAPSHOT_SCHEMA_PREFIX,
    MARKET_UNIVERSE_SNAPSHOT_SCHEMA_VERSION,
    MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION,
    RESEARCH_PANEL_SCHEMA_VERSION,
    RESEARCH_POSITION_SIZING_POLICY_VERSION,
    SUPPORTED_MARKET_UNIVERSE_SNAPSHOT_VERSIONS,
    MarketUniversePolicy,
    MarketUniverseRejected,
    build_full_market_universe_truth,
    build_market_universe_truth,
    market_deployment_scope,
    market_master_buy_instruments,
    market_universe_observation,
    normalize_a_share_members,
    preliminary_research_panel_symbols,
    require_complete_market_universe_snapshot,
)

__all__ = [
    "FULL_MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION",
    "LEGACY_MARKET_UNIVERSE_POLICY_VERSION",
    "MARKET_UNIVERSE_POLICY_VERSION",
    "MARKET_UNIVERSE_SNAPSHOT_SCHEMA_PREFIX",
    "MARKET_UNIVERSE_SNAPSHOT_SCHEMA_VERSION",
    "MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION",
    "RESEARCH_PANEL_SCHEMA_VERSION",
    "RESEARCH_POSITION_SIZING_POLICY_VERSION",
    "SUPPORTED_MARKET_UNIVERSE_SNAPSHOT_VERSIONS",
    "MarketUniversePolicy",
    "MarketUniverseRejected",
    "build_full_market_universe_truth",
    "build_market_universe_truth",
    "market_deployment_scope",
    "market_master_buy_instruments",
    "market_universe_observation",
    "normalize_a_share_members",
    "preliminary_research_panel_symbols",
    "require_complete_market_universe_snapshot",
]
