"""Deterministic full-market scan for human-promoted paper/shadow strategies.

Backward-compatible facade for server.services.strategy_scan.universe.service.
"""

from __future__ import annotations

from server.services.strategy_scan.universe.service import (
    PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
    PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
    PromotedStrategyUniverseScanService,
    SafetyGateReader,
    StrategyGateResolver,
    StrategyLoader,
)

__all__ = [
    "PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE",
    "PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION",
    "PromotedStrategyUniverseScanService",
    "SafetyGateReader",
    "StrategyGateResolver",
    "StrategyLoader",
]
