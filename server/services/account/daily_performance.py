"""Canonical deterministic daily performance attribution primitives.

Backward-compatible facade for server.services.account.performance.
"""

from __future__ import annotations

from server.services.account.performance import (
    AccountDailyPerformance,
    DailySellLot,
    DailyTradeLot,
    PositionDailyContext,
    PositionDailyMark,
    build_position_daily_context,
    calculate_account_daily_performance,
    mark_position_daily,
    price_at_tick,
)

__all__ = [
    "AccountDailyPerformance",
    "DailySellLot",
    "DailyTradeLot",
    "PositionDailyContext",
    "PositionDailyMark",
    "build_position_daily_context",
    "calculate_account_daily_performance",
    "mark_position_daily",
    "price_at_tick",
]
