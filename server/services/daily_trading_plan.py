"""Read-only daily trading plan aggregation.

Backward-compatible facade for server.services.decision.plan.
"""

from __future__ import annotations

from server.services.decision.plan import build_daily_trading_plan

__all__ = ["build_daily_trading_plan"]
