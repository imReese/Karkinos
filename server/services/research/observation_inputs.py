"""Observation dataset inputs, historical calendar slicing, and forward bindings.

Canonical module in server.services.research.
"""

from __future__ import annotations

from server.services.research.research_observation_inputs import (
    ResearchObservationInputError,
    bind_observation_forward_input,
    latest_closed_session,
    load_research_observation_source,
    observation_deployment_scope,
    observation_input_binding,
    observation_outcome_sessions,
    read_research_observation_dataset,
    require_observation_dataset_prefix,
)

__all__ = [
    "ResearchObservationInputError",
    "bind_observation_forward_input",
    "latest_closed_session",
    "load_research_observation_source",
    "observation_deployment_scope",
    "observation_input_binding",
    "observation_outcome_sessions",
    "read_research_observation_dataset",
    "require_observation_dataset_prefix",
]
