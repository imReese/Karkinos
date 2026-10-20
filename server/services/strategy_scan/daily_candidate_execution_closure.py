"""Daily candidate execution closure and terminal state verification.

Backward-compatible facade for server.services.strategy_scan.closure.
"""

from __future__ import annotations

from server.services.strategy_scan.closure import (
    DAILY_CANDIDATE_EXECUTION_CLOSURE_SCHEMA_VERSION,
    DAILY_CANDIDATE_EXECUTION_EVIDENCE_SUMMARY_SCHEMA_VERSION,
    MAX_EXECUTION_CLOSURE_ORDERS,
    build_daily_candidate_execution_closure,
    project_daily_candidate_execution_evidence_summary,
    verify_daily_candidate_execution_closure,
)

__all__ = [
    "DAILY_CANDIDATE_EXECUTION_CLOSURE_SCHEMA_VERSION",
    "DAILY_CANDIDATE_EXECUTION_EVIDENCE_SUMMARY_SCHEMA_VERSION",
    "MAX_EXECUTION_CLOSURE_ORDERS",
    "build_daily_candidate_execution_closure",
    "project_daily_candidate_execution_evidence_summary",
    "verify_daily_candidate_execution_closure",
]
