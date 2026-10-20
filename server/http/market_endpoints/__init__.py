"""Market HTTP endpoint registrations."""

from __future__ import annotations

from server.http.market_endpoints.dependencies import (
    CalendarEndpointDependencies,
    HealthEndpointDependencies,
    RefreshEndpointDependencies,
    ResearchEndpointDependencies,
    WatchlistEndpointDependencies,
)
from server.http.market_endpoints.watchlist import WatchlistLoader

__all__ = [
    "CalendarEndpointDependencies",
    "HealthEndpointDependencies",
    "RefreshEndpointDependencies",
    "ResearchEndpointDependencies",
    "WatchlistEndpointDependencies",
    "WatchlistLoader",
]
