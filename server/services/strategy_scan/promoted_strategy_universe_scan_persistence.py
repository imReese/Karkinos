"""Serialized recommendation-task persistence for promoted-strategy scans.

Backward-compatible facade for server.services.strategy_scan.universe.persistence.
"""

from __future__ import annotations

from server.services.strategy_scan.universe.persistence import (
    persist_recommendation_tasks,
)

__all__ = ["persist_recommendation_tasks"]
