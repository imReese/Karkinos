"""Compatibility facade for chronological backtest sweep engine.

Re-exports from server.services.backtest.chronological.
"""

from __future__ import annotations

from server.services.backtest.chronological import run_chronological_sweep

__all__ = [
    "run_chronological_sweep",
]
