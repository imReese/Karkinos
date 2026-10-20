"""Account-truth HTTP endpoint registrations."""

from __future__ import annotations

from server.http.account_truth_endpoints.dependencies import (
    IntakeEndpointDependencies,
    ReportDetailEndpointDependencies,
    ReviewEndpointDependencies,
    SummaryEndpointDependencies,
)

__all__ = [
    "IntakeEndpointDependencies",
    "ReportDetailEndpointDependencies",
    "ReviewEndpointDependencies",
    "SummaryEndpointDependencies",
]
