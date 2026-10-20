"""Portfolio HTTP endpoint registrations."""

from __future__ import annotations

from server.http.portfolio_endpoints.dependencies import (
    PortfolioAnalysisDependencies,
    PortfolioCashFlowDependencies,
    PortfolioEndpointDependencies,
    PortfolioPerformanceDependencies,
    PortfolioPerformanceOperations,
    PortfolioSnapshotDependencies,
    PortfolioSnapshotOperations,
    PortfolioTradeDependencies,
)
from server.http.portfolio_endpoints.snapshot import (
    PortfolioSnapshotEndpoints,
    portfolio_response_not_modified,
)

__all__ = [
    "PortfolioAnalysisDependencies",
    "PortfolioCashFlowDependencies",
    "PortfolioEndpointDependencies",
    "PortfolioPerformanceDependencies",
    "PortfolioPerformanceOperations",
    "PortfolioSnapshotDependencies",
    "PortfolioSnapshotEndpoints",
    "PortfolioSnapshotOperations",
    "PortfolioTradeDependencies",
    "portfolio_response_not_modified",
]
