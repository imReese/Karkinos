"""Read-only evaluation of realized candidate outcomes across standard horizons.

Backward-compatible facade for server.services.strategy_scan.outcomes.
"""

from __future__ import annotations

from server.services.strategy_scan.outcomes import (
    evaluate_daily_candidate_outcomes,
)

__all__ = ["evaluate_daily_candidate_outcomes"]
