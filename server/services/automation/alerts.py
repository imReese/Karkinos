"""Automation alert management and background polling service.

Canonical module in server.services.automation.
"""

from __future__ import annotations

from server.services.automation.automation_alerts import (
    AutomationAlertService,
)

__all__ = [
    "AutomationAlertService",
]
