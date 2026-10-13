"""Compatibility facade for portfolio allocation.

Canonical domain implementation: `server.services.portfolio.allocation`
"""

from __future__ import annotations

from server.services.portfolio.allocation import allocate_action_tasks

__all__ = [
    "allocate_action_tasks",
]
