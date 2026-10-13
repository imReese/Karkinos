"""Compatibility facade for market calendar verification.

Canonical domain implementation: `server.services.market.calendar`
"""

from __future__ import annotations

from server.services.market.calendar import (
    MarketCalendarEvidenceValidation,
    validate_verified_market_calendar,
)

__all__ = [
    "MarketCalendarEvidenceValidation",
    "validate_verified_market_calendar",
]
