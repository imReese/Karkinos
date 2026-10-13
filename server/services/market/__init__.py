"""Market domain services: calendar verification, trading hours, indices, and automation."""

from __future__ import annotations

from server.services.market.calendar import (
    POST_CLOSE_INGESTION_TIME,
    MarketCalendarEvidenceValidation,
    VerifiedClosedTradingDate,
    latest_verified_closed_trading_date,
    project_market_session,
    resolve_latest_verified_closed_trading_date,
    resolve_verified_closed_trading_dates,
    resolve_verified_closed_trading_dates_in_range,
    validate_verified_market_calendar,
)
from server.services.market.calendar_automation import (
    MARKET_CALENDAR_AUTOMATION_RUN_TYPE,
    MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION,
    MarketCalendarAutomationService,
    market_calendar_automation_years,
)
from server.services.market.hours import get_shanghai_now, is_cn_trading_session
from server.services.market.indices import (
    DEFAULT_MARKET_INDEX_ASSETS,
    default_market_index_assets,
    market_index_display_name,
)

__all__ = [
    "DEFAULT_MARKET_INDEX_ASSETS",
    "MARKET_CALENDAR_AUTOMATION_RUN_TYPE",
    "MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION",
    "MarketCalendarAutomationService",
    "MarketCalendarEvidenceValidation",
    "POST_CLOSE_INGESTION_TIME",
    "VerifiedClosedTradingDate",
    "default_market_index_assets",
    "get_shanghai_now",
    "is_cn_trading_session",
    "latest_verified_closed_trading_date",
    "market_calendar_automation_years",
    "market_index_display_name",
    "project_market_session",
    "resolve_latest_verified_closed_trading_date",
    "resolve_verified_closed_trading_dates",
    "resolve_verified_closed_trading_dates_in_range",
    "validate_verified_market_calendar",
]
