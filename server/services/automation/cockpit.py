"""Read-only automation cockpit summary and diagnostic view service.

Canonical module in server.services.automation.
"""

from __future__ import annotations

from server.services.automation.automation_cockpit import (
    AUTOMATION_COCKPIT_SCHEMA_PREFIX,
    AUTOMATION_COCKPIT_SCHEMA_VERSION,
    AutomationCockpitService,
    validate_automation_cockpit_payload,
)

__all__ = [
    "AUTOMATION_COCKPIT_SCHEMA_PREFIX",
    "AUTOMATION_COCKPIT_SCHEMA_VERSION",
    "AutomationCockpitService",
    "validate_automation_cockpit_payload",
]
