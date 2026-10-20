"""Short-lived, source-rechecked Account Truth evidence for session start.

Backward-compatible facade for server.services.account.session_truth.
"""

from __future__ import annotations

from server.services.account.session_truth import (
    SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE,
    SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE,
    SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE,
    SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
    SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION,
    SESSION_START_ACCOUNT_TRUTH_STATUS_SCHEMA_VERSION,
    SessionStartAccountTruthRejected,
    SessionStartAccountTruthService,
    resolve_session_start_account_truth_binding,
)

__all__ = [
    "SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT",
    "SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE",
    "SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE",
    "SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE",
    "SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS",
    "SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION",
    "SESSION_START_ACCOUNT_TRUTH_STATUS_SCHEMA_VERSION",
    "SessionStartAccountTruthRejected",
    "SessionStartAccountTruthService",
    "resolve_session_start_account_truth_binding",
]
