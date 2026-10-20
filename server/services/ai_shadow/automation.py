"""AI shadow research automation orchestrator and service composition.

Canonical module in server.services.ai_shadow.
"""

from __future__ import annotations

from server.services.ai_shadow.ai_shadow_research_automation import (
    AiShadowResearchAutomationService,
    build_ai_shadow_research_automation_service,
    qualification_allows_new_research,
)

__all__ = [
    "AiShadowResearchAutomationService",
    "build_ai_shadow_research_automation_service",
    "qualification_allows_new_research",
]
