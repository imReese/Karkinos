"""Compatibility facade for portfolio risk workspace projections.

Re-exports from server.services.risk.workspace.
"""

from __future__ import annotations

from server.services.risk.workspace import build_risk_workspace

__all__ = [
    "build_risk_workspace",
]
