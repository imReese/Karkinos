"""Forward observation automation loop, scheduling, and projection.

Canonical module in server.services.research.
"""

from __future__ import annotations

from server.services.research.research_observation_automation import (
    OBSERVATION_AUTOMATION_INTERVAL_SECONDS,
    configure_observation_automation,
    logger,
    project_observation_automation,
    run_research_observation_automation_loop,
    run_research_observation_automation_once,
    start_reserved_champion_observation,
)

__all__ = [
    "OBSERVATION_AUTOMATION_INTERVAL_SECONDS",
    "configure_observation_automation",
    "logger",
    "project_observation_automation",
    "run_research_observation_automation_loop",
    "run_research_observation_automation_once",
    "start_reserved_champion_observation",
]
