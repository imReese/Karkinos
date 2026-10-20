"""Market session start and close automation orchestrator.

Canonical module in server.services.market.
"""

from __future__ import annotations

from server.services.market.market_session_automation import (
    MARKET_SESSION_AUTOMATION_SCHEMA_VERSION,
    MARKET_SESSION_LIMITATION,
    MarketSessionAutomationService,
)

__all__ = [
    "MARKET_SESSION_AUTOMATION_SCHEMA_VERSION",
    "MARKET_SESSION_LIMITATION",
    "MarketSessionAutomationService",
]
