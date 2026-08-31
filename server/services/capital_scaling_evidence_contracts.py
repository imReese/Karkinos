"""Stable constants for capital-scaling evidence collection."""

from __future__ import annotations

from zoneinfo import ZoneInfo

CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_SCHEMA_VERSION = (
    "karkinos.capital_scaling_account_truth_snapshot.v1"
)
CAPITAL_SCALING_EVIDENCE_WINDOW_SCHEMA_VERSION = (
    "karkinos.capital_scaling_evidence_window.v2"
)
CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_EVENT_TYPE = (
    "capital_scaling.account_truth_snapshot_recorded"
)
CAPITAL_SCALING_ACCOUNT_TRUTH_SNAPSHOT_ENTITY_TYPE = (
    "capital_scaling_account_truth_snapshot"
)
CAPITAL_SCALING_EVIDENCE_WINDOW_EVENT_TYPE = "capital_scaling.evidence_window_recorded"
CAPITAL_SCALING_EVIDENCE_WINDOW_ENTITY_TYPE = "capital_scaling_evidence_window"
CAPITAL_SCALING_EVIDENCE_SOURCE = "capital_scaling_evidence_window"

DEFAULT_BOUNDARY_GAP_HOURS = 72
MAX_ACCOUNT_TRUTH_CAPTURE_LAG_SECONDS = 900
MAX_SOURCE_ROWS = 5000
MAX_RUNTIME_ADMISSION_ROWS = 500

REAL_EXECUTION_MODES = frozenset({"manual", "controlled_live", "live"})
POLICY_VIOLATION_GATEWAY_EVENTS = frozenset(
    {"live_submission_rejected", "live_cancel_rejected"}
)
DISCONNECT_MARKERS = (
    "disconnect",
    "unavailable",
    "timeout",
    "connector_error",
    "connection_error",
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
