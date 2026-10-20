"""Daily candidate runtime and review status aggregation.

Backward-compatible facade for server.services.strategy_scan.status.
"""

from __future__ import annotations

from server.services.strategy_scan.status import (
    DAILY_CANDIDATE_RUNTIME_STATUS_SCHEMA_VERSION,
    build_daily_candidate_runtime_status,
    unavailable_daily_candidate_runtime_status,
)

__all__ = [
    "DAILY_CANDIDATE_RUNTIME_STATUS_SCHEMA_VERSION",
    "build_daily_candidate_runtime_status",
    "unavailable_daily_candidate_runtime_status",
]
