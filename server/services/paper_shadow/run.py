"""Paper shadow run execution orchestrator from trading plans.

Canonical module in server.services.paper_shadow.
"""

from __future__ import annotations

from server.services.paper_shadow.paper_shadow_run import (
    run_paper_shadow_from_trading_plan,
)

__all__ = [
    "run_paper_shadow_from_trading_plan",
]
