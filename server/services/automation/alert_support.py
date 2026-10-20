"""Pure helper functions and schema definitions for automation alerts.

Canonical module in server.services.automation.
"""

from __future__ import annotations

from server.services.automation.automation_alert_support import (
    ACCOUNT_TRUTH_ALERT_STATUSES,
    AUTOMATION_ALERT_SCHEMA_VERSION,
    FAILED_AUTOMATION_RUN_STATUSES,
    PAPER_SHADOW_DIVERGENCE_STATUSES,
    RUNTIME_CONNECTOR_DEGRADED_STATUSES,
    STALE_MARKET_DATA_STATUSES,
    automation_run_suggested_action,
    current_review_alert_boundary,
    dedupe,
    json_list,
    json_object,
    object_dict,
    safe_int,
    stable_fingerprint,
)

__all__ = [
    "ACCOUNT_TRUTH_ALERT_STATUSES",
    "AUTOMATION_ALERT_SCHEMA_VERSION",
    "FAILED_AUTOMATION_RUN_STATUSES",
    "PAPER_SHADOW_DIVERGENCE_STATUSES",
    "RUNTIME_CONNECTOR_DEGRADED_STATUSES",
    "STALE_MARKET_DATA_STATUSES",
    "automation_run_suggested_action",
    "current_review_alert_boundary",
    "dedupe",
    "json_list",
    "json_object",
    "object_dict",
    "safe_int",
    "stable_fingerprint",
]
