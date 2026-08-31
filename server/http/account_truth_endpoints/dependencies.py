"""Explicit dependency contracts for account-truth HTTP registration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Operation = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class IntakeEndpointDependencies:
    citic_history_xls_directory_config_for_state: Operation
    citic_history_xls_directory_scan_response: Operation
    citic_history_xls_directory_status_response: Operation
    citic_history_xls_preview_response: Operation
    citic_query_window_review_http_exception: Operation
    citic_query_window_review_read_http_exception: Operation
    citic_source_intake_response: Operation
    citic_source_reviews_for_state: Operation
    citic_source_scope_review_http_exception: Operation
    citic_source_scope_review_read_http_exception: Operation
    parse_citic_history_xls_transport: Operation
    preview_response: Operation
    record_citic_source_intake: Operation
    build_citic_history_canonical_lineage_assessment: Operation
    find_citic_history_xls_directory_preview: Operation
    parse_broker_statement_csv: Operation
    parse_citic_history_xls: Operation
    record_citic_source_query_window_review: Operation
    record_citic_source_scope_review: Operation
    revoke_citic_source_query_window_review: Operation
    revoke_citic_source_scope_review: Operation
    scan_citic_history_xls_directory: Operation


@dataclass(frozen=True, slots=True)
class ReportDetailEndpointDependencies:
    account_truth_read_http_exception: Operation
    build_report_for_import_run: Operation
    decision_response: Operation
    item_key: Operation
    manual_review_repository_for_state: Operation
    report_detail_response: Operation
    repository_for_state: Operation
    reconciliation_item_fingerprint: Operation


@dataclass(frozen=True, slots=True)
class ReviewEndpointDependencies:
    account_truth_read_http_exception: Operation
    citic_canonical_resolution_http_exception: Operation
    citic_canonical_resolution_read_http_exception: Operation
    evidence_scope_review_http_exception: Operation
    reviewed_fee_schedule_http_exception: Operation
    reviewed_fee_schedule_read_http_exception: Operation
    reviewed_fee_schedule_repository_for_state: Operation
    build_reviewed_fee_schedule_preview: Operation
    build_reviewed_fee_schedule_review_status: Operation
    record_account_truth_evidence_scope_review: Operation
    record_citic_source_canonical_resolution: Operation
    revoke_account_truth_evidence_scope_review: Operation
    revoke_citic_source_canonical_resolution: Operation


@dataclass(frozen=True, slots=True)
class SummaryEndpointDependencies:
    account_truth_read_http_exception: Operation
    build_report_for_import_run: Operation
    import_run_response: Operation
    latest_import_runs_by_fingerprint: Operation
    missing_score_response: Operation
    preview_response: Operation
    report_summary_response: Operation
    repository_for_state: Operation
    build_account_truth_evidence_readiness: Operation
    build_latest_account_truth_score_payload: Operation
    parse_broker_statement_csv: Operation


__all__ = [
    "IntakeEndpointDependencies",
    "ReportDetailEndpointDependencies",
    "ReviewEndpointDependencies",
    "SummaryEndpointDependencies",
]
