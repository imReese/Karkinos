"""Compatibility facade for market trading hours.

Canonical domain implementation: `server.services.market.hours`
"""

from __future__ import annotations

from server.services.market.hours import (
    get_shanghai_now,
    is_cn_trading_session,
)

__all__ = [
    "get_shanghai_now",
    "is_cn_trading_session",
]
