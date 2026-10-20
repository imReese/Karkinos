"""Canonical read-only account-strategy projections.

Backward-compatible facade for server.services.account.strategy.
"""

from __future__ import annotations

from server.services.account.strategy import (
    build_attribution_summary,
    build_contribution_report,
)

__all__ = [
    "build_attribution_summary",
    "build_contribution_report",
]
