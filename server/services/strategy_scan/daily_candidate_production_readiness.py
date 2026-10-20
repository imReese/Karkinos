"""Projection of runtime readiness for automated strategy order production.

Backward-compatible facade for server.services.strategy_scan.readiness.
"""

from __future__ import annotations

from server.services.strategy_scan.readiness import (
    DAILY_CANDIDATE_PRODUCTION_READINESS_SCHEMA_VERSION,
    project_daily_candidate_production_readiness,
    unavailable_daily_candidate_production_readiness,
)

__all__ = [
    "DAILY_CANDIDATE_PRODUCTION_READINESS_SCHEMA_VERSION",
    "project_daily_candidate_production_readiness",
    "unavailable_daily_candidate_production_readiness",
]
