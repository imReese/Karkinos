"""Compatibility facade for market calendar automation.

Canonical domain implementation: `server.services.market.calendar_automation`
"""

from __future__ import annotations

from server.services.market.calendar_automation import (
    MARKET_CALENDAR_AUTOMATION_RUN_TYPE,
    MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION,
    MarketCalendarAutomationService,
    market_calendar_automation_years,
)

__all__ = [
    "MARKET_CALENDAR_AUTOMATION_RUN_TYPE",
    "MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION",
    "MarketCalendarAutomationService",
    "market_calendar_automation_years",
]
