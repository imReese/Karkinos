"""Read-only freshness validation for persisted promoted-strategy scans.

Backward-compatible facade for server.services.strategy_scan.universe.validation.
"""

from __future__ import annotations

from server.services.strategy_scan.universe.validation import (
    current_scan_input_blockers,
    portfolio_stock_symbols,
)

__all__ = [
    "current_scan_input_blockers",
    "portfolio_stock_symbols",
]
