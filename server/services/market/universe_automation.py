"""Market universe automated scan execution and lifecycle loop.

Canonical module in server.services.market.
"""

from __future__ import annotations

from server.services.market.market_universe_automation import (
    MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS,
    MARKET_UNIVERSE_AUTOMATION_RUN_TYPE,
    MARKET_UNIVERSE_AUTOMATION_SCHEMA_PREFIX,
    MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION,
    MarketUniverseAutomationService,
    run_market_universe_automation_loop,
    validate_market_universe_automation_payload,
    verified_trading_dates,
)

__all__ = [
    "MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS",
    "MARKET_UNIVERSE_AUTOMATION_RUN_TYPE",
    "MARKET_UNIVERSE_AUTOMATION_SCHEMA_PREFIX",
    "MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION",
    "MarketUniverseAutomationService",
    "run_market_universe_automation_loop",
    "validate_market_universe_automation_payload",
    "verified_trading_dates",
]
