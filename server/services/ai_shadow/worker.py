"""Durable background worker for AI shadow research jobs.

Canonical module in server.services.ai_shadow.
"""

from __future__ import annotations

from server.services.ai_shadow.ai_shadow_research_worker import (
    AI_SHADOW_RESEARCH_WORKER_HEARTBEAT_SECONDS,
    AI_SHADOW_RESEARCH_WORKER_LEASE_SECONDS,
    AI_SHADOW_RESEARCH_WORKER_POLL_SECONDS,
    AI_SHADOW_RESEARCH_WORKER_RETRY_SECONDS,
    AiShadowResearchWorker,
    AiShadowResearchWorkerLeaseLost,
    ShadowResearchRunner,
    ShadowResearchWorkerJobStore,
)

__all__ = [
    "AI_SHADOW_RESEARCH_WORKER_HEARTBEAT_SECONDS",
    "AI_SHADOW_RESEARCH_WORKER_LEASE_SECONDS",
    "AI_SHADOW_RESEARCH_WORKER_POLL_SECONDS",
    "AI_SHADOW_RESEARCH_WORKER_RETRY_SECONDS",
    "AiShadowResearchWorker",
    "AiShadowResearchWorkerLeaseLost",
    "ShadowResearchRunner",
    "ShadowResearchWorkerJobStore",
]
