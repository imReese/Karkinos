"""Automation execution policy controls and runtime toggles.

Canonical module in server.services.automation.
"""

from __future__ import annotations

from server.services.automation.automation_control import (
    AUTOMATION_POLICY_SCHEMA_VERSION,
    AUTOMATION_RUN_SCHEMA_VERSION,
    DEFAULT_AUTOMATION_POLICY_ID,
    SAFE_EXECUTION_MODES,
    AutomationControlService,
)

__all__ = [
    "AUTOMATION_POLICY_SCHEMA_VERSION",
    "AUTOMATION_RUN_SCHEMA_VERSION",
    "DEFAULT_AUTOMATION_POLICY_ID",
    "SAFE_EXECUTION_MODES",
    "AutomationControlService",
]
