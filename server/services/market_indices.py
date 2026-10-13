"""Compatibility facade for market indices.

Canonical domain implementation: `server.services.market.indices`
"""

from __future__ import annotations

from server.services.market.indices import (
    DEFAULT_MARKET_INDEX_ASSETS,
    default_market_index_assets,
    market_index_display_name,
)

__all__ = [
    "DEFAULT_MARKET_INDEX_ASSETS",
    "default_market_index_assets",
    "market_index_display_name",
]
