"""Composition of capital-scaling execution-evidence fact projections."""

from __future__ import annotations

from server.services.capital_scaling_capacity_fact import (
    CapitalScalingCapacityFactMixin,
)
from server.services.capital_scaling_execution_scope_fact import (
    CapitalScalingExecutionScopeFactMixin,
)
from server.services.capital_scaling_operating_sample_fact import (
    CapitalScalingOperatingSampleFactMixin,
)


class CapitalScalingExecutionFactsMixin(
    CapitalScalingCapacityFactMixin,
    CapitalScalingOperatingSampleFactMixin,
    CapitalScalingExecutionScopeFactMixin,
):
    """Compose canonical capacity, operating, and execution-scope facts."""
