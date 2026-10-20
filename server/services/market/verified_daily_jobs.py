"""Verified daily market data job planning and batch enqueue routines.

Canonical module in server.services.market.
"""

from __future__ import annotations

from server.services.market.verified_daily_market_jobs import (
    MAX_VERIFIED_DAILY_JOB_INSTRUMENTS,
    VERIFIED_DAILY_MARKET_JOB,
    VerifiedDailyMarketJobPlan,
    VerifiedDailyMarketJobPlanningError,
    enqueue_latest_daily_market_collection_jobs,
    enqueue_latest_verified_daily_market_jobs,
    enqueue_verified_daily_market_jobs_for_range,
    supported_watchlist_instruments,
    verified_daily_instrument_batches,
)

__all__ = [
    "MAX_VERIFIED_DAILY_JOB_INSTRUMENTS",
    "VERIFIED_DAILY_MARKET_JOB",
    "VerifiedDailyMarketJobPlan",
    "VerifiedDailyMarketJobPlanningError",
    "enqueue_latest_daily_market_collection_jobs",
    "enqueue_latest_verified_daily_market_jobs",
    "enqueue_verified_daily_market_jobs_for_range",
    "supported_watchlist_instruments",
    "verified_daily_instrument_batches",
]
