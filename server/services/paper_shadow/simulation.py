"""Batch order simulation against market context and paper portfolio state.

Canonical module in server.services.paper_shadow.
"""

from __future__ import annotations

from server.services.paper_shadow.paper_shadow_simulation import (
    PaperShadowSimulation,
    simulate_paper_shadow_orders,
)

__all__ = [
    "PaperShadowSimulation",
    "simulate_paper_shadow_orders",
]
