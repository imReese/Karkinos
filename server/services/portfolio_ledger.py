"""Compatibility facade for portfolio ledger state.

Canonical domain implementation: `server.services.portfolio.ledger`
"""

from __future__ import annotations

from server.services.portfolio.ledger import (
    build_portfolio_projection,
    rebuild_portfolio_from_entries,
    rebuild_portfolio_from_ledger,
)

# Canonical requirement: only get_ledger_entries_sync facts
_REQUIRED_METHOD = "get_ledger_entries_sync"

__all__ = [
    "build_portfolio_projection",
    "rebuild_portfolio_from_entries",
    "rebuild_portfolio_from_ledger",
]
