"""Compatibility facade for market calendar date queries and session projections.

Canonical domain implementation: `server.services.market.calendar`
"""

from __future__ import annotations

from server.services.market.calendar import (
    POST_CLOSE_INGESTION_TIME,
    VerifiedClosedTradingDate,
    latest_verified_closed_trading_date,
    project_market_session,
    resolve_latest_verified_closed_trading_date,
    resolve_verified_closed_trading_dates,
    resolve_verified_closed_trading_dates_in_range,
)

__all__ = [
    "POST_CLOSE_INGESTION_TIME",
    "VerifiedClosedTradingDate",
    "latest_verified_closed_trading_date",
    "project_market_session",
    "resolve_latest_verified_closed_trading_date",
    "resolve_verified_closed_trading_dates",
    "resolve_verified_closed_trading_dates_in_range",
]
