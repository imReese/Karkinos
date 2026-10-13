"""Quarantined CITIC legacy reconciliation, source review, and lineage.

DURABLE INVARIANT (AGENTS.md & docs/PLAN.md):
- Real-money authority remains default-off, bounded, observable, pausable, revocable, and human-supervised.
- Live-trading safety constraints are durable boundaries, not current implementation scope.
- Strategy and research code never call a broker directly.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION",
    "CITIC_QUERY_WINDOW_BATCH_ASSESSMENT_SCHEMA_VERSION",
    "CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION",
    "CITIC_SOURCE_QUERY_WINDOW_REVIEW_COMMAND_SCHEMA_VERSION",
    "CITIC_SOURCE_SCOPE_BATCH_ASSESSMENT_SCHEMA_VERSION",
    "CITIC_SOURCE_SCOPE_REVIEW_COMMAND_SCHEMA_VERSION",
    "active_citic_source_scope_review",
    "build_citic_history_canonical_lineage_assessment",
    "build_citic_source_follow_up",
    "citic_source_query_window_review_response",
    "citic_source_scope_review_response",
    "current_citic_source_set_fingerprint",
    "latest_citic_query_window_reviews_by_intake",
    "latest_citic_source_scope_reviews_by_intake",
    "project_citic_history_canonical_lineage_assessment",
    "project_citic_query_window_batch_assessment",
    "project_citic_source_scope_batch_assessment",
    "record_citic_source_canonical_resolution",
    "record_citic_source_query_window_review",
    "record_citic_source_scope_review",
    "revoke_citic_source_canonical_resolution",
    "revoke_citic_source_query_window_review",
    "revoke_citic_source_scope_review",
]

_SUBMODULE_MAP = {
    # Canonical Resolution
    "record_citic_source_canonical_resolution": "canonical_resolution",
    "revoke_citic_source_canonical_resolution": "canonical_resolution",
    "current_citic_source_set_fingerprint": "canonical_resolution",
    # Follow up
    "CITIC_SOURCE_FOLLOW_UP_SCHEMA_VERSION": "follow_up",
    "build_citic_source_follow_up": "follow_up",
    # Query window review
    "CITIC_QUERY_WINDOW_BATCH_ASSESSMENT_SCHEMA_VERSION": "query_window_review",
    "CITIC_SOURCE_QUERY_WINDOW_REVIEW_COMMAND_SCHEMA_VERSION": "query_window_review",
    "citic_source_query_window_review_response": "query_window_review",
    "latest_citic_query_window_reviews_by_intake": "query_window_review",
    "project_citic_query_window_batch_assessment": "query_window_review",
    "record_citic_source_query_window_review": "query_window_review",
    "revoke_citic_source_query_window_review": "query_window_review",
    # Scope review
    "CITIC_SOURCE_SCOPE_BATCH_ASSESSMENT_SCHEMA_VERSION": "scope_review",
    "CITIC_SOURCE_SCOPE_REVIEW_COMMAND_SCHEMA_VERSION": "scope_review",
    "active_citic_source_scope_review": "scope_review",
    "citic_source_scope_review_response": "scope_review",
    "latest_citic_source_scope_reviews_by_intake": "scope_review",
    "project_citic_source_scope_batch_assessment": "scope_review",
    "record_citic_source_scope_review": "scope_review",
    "revoke_citic_source_scope_review": "scope_review",
    # History lineage
    "CITIC_HISTORY_CANONICAL_LINEAGE_SCHEMA_VERSION": "history_lineage",
    "build_citic_history_canonical_lineage_assessment": "history_lineage",
    "project_citic_history_canonical_lineage_assessment": "history_lineage",
}


def __getattr__(name: str) -> Any:
    submodule = _SUBMODULE_MAP.get(name)
    if submodule:
        mod = importlib.import_module(
            f"server.services.controlled_execution.citic.{submodule}"
        )
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
