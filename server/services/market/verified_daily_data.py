"""Verified daily market data ingestion and publication service.

Canonical module in server.services.market.
"""

from __future__ import annotations

from server.services.market.verified_daily_market_data import (
    VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION,
    VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION,
    VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
    VerifiedDailyMarketDataError,
    VerifiedDailyMarketDataNotPublishable,
    VerifiedDailyMarketDataRequestError,
    VerifiedDailyMarketDataService,
    VerifiedDailyMarketDataUnavailable,
    VerifiedDailyMarketJobRequest,
    VerifiedDailyMarketPublication,
    VerifiedDailySourceResolution,
    is_verified_daily_resolver_policy,
    verified_daily_resolver_policy_id,
)

__all__ = [
    "VERIFIED_DAILY_MARKET_JOB_SCHEMA_VERSION",
    "VERIFIED_DAILY_MARKET_RANGE_JOB_SCHEMA_VERSION",
    "VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT",
    "VerifiedDailyMarketDataError",
    "VerifiedDailyMarketDataNotPublishable",
    "VerifiedDailyMarketDataRequestError",
    "VerifiedDailyMarketDataService",
    "VerifiedDailyMarketDataUnavailable",
    "VerifiedDailyMarketJobRequest",
    "VerifiedDailyMarketPublication",
    "VerifiedDailySourceResolution",
    "is_verified_daily_resolver_policy",
    "verified_daily_resolver_policy_id",
]
