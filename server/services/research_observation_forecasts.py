"""Run frozen research rules over known history without creating orders or fills.

Backward-compatible facade for server.services.research.forecasts.
"""

from __future__ import annotations

from server.services.research.forecasts import (
    FORECAST_POLICY_ID,
    build_observation_forecasts,
)

__all__ = [
    "FORECAST_POLICY_ID",
    "build_observation_forecasts",
]
