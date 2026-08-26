"""Pure status projections for persisted AI shadow research usage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_CANDIDATE_STATUS_FIELDS = (
    "candidate_id",
    "run_id",
    "session_id",
    "draft_id",
    "backtest_run_id",
    "critique_id",
    "baseline_result_id",
    "candidate_result_id",
    "status",
    "recommendation",
    "promotion_status",
    "created_at",
    "updated_at",
    "automatic_strategy_replacement_enabled",
    "production_strategy_mutation_enabled",
    "broker_submission_enabled",
    "human_paper_shadow_approval_required",
)
_COMPARISON_STATUS_FIELDS = (
    "schema_version",
    "failure_code",
    "economic_hypothesis",
    "risk_impact",
    "failure_conditions",
    "limitations",
    "recommendation",
)
_BACKTEST_STATUS_FIELDS = (
    "result_id",
    "total_return",
    "sharpe",
    "max_drawdown",
    "total_cost",
    "total_commission",
    "total_slippage",
    "total_trades",
    "gross_turnover",
    "oos_fold_count",
    "mean_oos_return",
    "worst_oos_return",
    "oos_validation_status",
    "evidence_gate_status",
    "dataset_snapshot_id",
)
_DELTA_STATUS_FIELDS = (
    "total_return",
    "sharpe",
    "max_drawdown",
    "total_cost",
)
_CRITIQUE_STATUS_FIELDS = (
    "supported_claims",
    "contradicted_claims",
    "evidence_gaps",
    "uncertainty",
)
_ITERATION_STATUS_FIELDS = (
    "iteration_number",
    "total_iterations",
    "formula_fingerprint",
    "parent_candidate_id",
    "parent_draft_id",
    "parent_formula_fingerprint",
    "iteration_context_fingerprint",
    "sequential_feedback_bound",
)
_PROMOTION_GATE_STATUS_FIELDS = ("status", "blockers")


def project_shadow_research_candidate_status(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the bounded candidate view consumed by automation status pages.

    Full comparison evidence remains persisted and available through the
    repository's explicit candidate lookup.  In particular, this projection
    excludes equity curves, drawdown series, rolling-OOS folds, robustness
    payloads, and promotion-gate check evidence from the frequently polled
    status response.
    """

    projected = _select_fields(candidate, _CANDIDATE_STATUS_FIELDS)
    comparison = _mapping(candidate.get("comparison"))
    comparison_status = _select_fields(comparison, _COMPARISON_STATUS_FIELDS)

    nested_fields = (
        ("baseline", _BACKTEST_STATUS_FIELDS),
        ("candidate", _BACKTEST_STATUS_FIELDS),
        ("deltas", _DELTA_STATUS_FIELDS),
        ("deepseek_critique", _CRITIQUE_STATUS_FIELDS),
        ("iteration_lineage", _ITERATION_STATUS_FIELDS),
        ("promotion_gate", _PROMOTION_GATE_STATUS_FIELDS),
    )
    for key, fields in nested_fields:
        value = comparison.get(key)
        if isinstance(value, Mapping):
            comparison_status[key] = _select_fields(value, fields)

    projected["comparison"] = comparison_status
    return projected


def empty_shadow_research_usage(market_date: str | None) -> dict[str, Any]:
    """Return the fail-closed zero-usage projection for an unavailable store."""

    return {
        "market_date": market_date,
        "provider_calls": 0,
        "recorded_call_attempts": 0,
        "provider_free_rejections": 0,
        "reserved_tokens": 0,
        "actual_tokens": 0,
        "retry_authorization_id": None,
        "retry_authorization_consumed": False,
        "authorized_additional_calls": 0,
        "authorized_provider_call_ceiling": None,
        "retry_replacement_run_id": None,
        "citation_call_extension_id": None,
        "citation_call_extension_consumed": False,
        "citation_authorized_additional_calls": 0,
        "citation_extension_replacement_run_id": None,
        "output_truncation_call_extension_id": None,
        "output_truncation_call_extension_consumed": False,
        "output_truncation_authorized_additional_calls": 0,
        "output_truncation_extension_replacement_run_id": None,
        "timeout_resume_call_extension_id": None,
        "timeout_resume_call_extension_consumed": False,
        "timeout_resume_authorized_additional_calls": 0,
        "timeout_resume_resumed_run_id": None,
        "timeout_resume_iteration": None,
        "corrected_panel_rearm_authorization_id": None,
        "corrected_panel_rearm_consumed": False,
        "corrected_panel_rearm_authorized_additional_calls": 0,
        "corrected_panel_rearm_replacement_run_id": None,
        "corrected_panel_citation_resume_extension_id": None,
        "corrected_panel_citation_resume_consumed": False,
        "corrected_panel_citation_resume_authorized_additional_calls": 0,
        "corrected_panel_citation_resume_resumed_run_id": None,
        "corrected_panel_citation_resume_iteration": None,
        "corrected_panel_citation_resume_stage": None,
        "provider_free_partial_resume_id": None,
        "provider_free_partial_resume_run_id": None,
        "provider_free_partial_resume_failed_call_id": None,
        "provider_free_partial_resume_failure_code": None,
        "provider_free_partial_resume_completed_iteration_count": None,
        "provider_free_partial_resume_iteration": None,
    }


def project_shadow_research_usage(
    *,
    market_date: str,
    totals: Mapping[str, Any],
    retry: Mapping[str, Any] | None,
    citation: Mapping[str, Any] | None,
    output_truncation: Mapping[str, Any] | None,
    timeout_resume: Mapping[str, Any] | None,
    corrected_panel: Mapping[str, Any] | None,
    corrected_panel_citation_resume: Mapping[str, Any] | None,
    provider_free_partial_resume: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project database records without granting strategy or trading authority."""

    calls = int(totals["calls"])
    recorded_calls = int(totals["recorded_calls"])
    authorization_rows = (
        retry,
        citation,
        output_truncation,
        timeout_resume,
        corrected_panel,
        corrected_panel_citation_resume,
    )
    ceiling_rows = tuple(row for row in reversed(authorization_rows) if row)
    return {
        "market_date": market_date,
        "provider_calls": calls,
        "recorded_call_attempts": recorded_calls,
        "provider_free_rejections": recorded_calls - calls,
        "reserved_tokens": int(totals["reserved"]),
        "actual_tokens": int(totals["actual"]),
        "retry_authorization_id": _value(retry, "authorization_id"),
        "retry_authorization_consumed": bool(_value(retry, "replacement_run_id")),
        "authorized_additional_calls": sum(
            _integer(row, "authorized_additional_calls") for row in authorization_rows
        ),
        "authorized_provider_call_ceiling": (
            _integer(ceiling_rows[0], "provider_call_ceiling") if ceiling_rows else None
        ),
        "retry_replacement_run_id": _value(retry, "replacement_run_id"),
        "citation_call_extension_id": _value(citation, "extension_id"),
        "citation_call_extension_consumed": bool(
            _value(citation, "replacement_run_id")
        ),
        "citation_authorized_additional_calls": _integer(
            citation, "authorized_additional_calls"
        ),
        "citation_extension_replacement_run_id": _value(citation, "replacement_run_id"),
        "output_truncation_call_extension_id": _value(
            output_truncation, "extension_id"
        ),
        "output_truncation_call_extension_consumed": bool(
            _value(output_truncation, "replacement_run_id")
        ),
        "output_truncation_authorized_additional_calls": _integer(
            output_truncation, "authorized_additional_calls"
        ),
        "output_truncation_extension_replacement_run_id": _value(
            output_truncation, "replacement_run_id"
        ),
        "timeout_resume_call_extension_id": _value(timeout_resume, "extension_id"),
        "timeout_resume_call_extension_consumed": bool(
            _value(timeout_resume, "resumed_run_id")
        ),
        "timeout_resume_authorized_additional_calls": _integer(
            timeout_resume, "authorized_additional_calls"
        ),
        "timeout_resume_resumed_run_id": _value(timeout_resume, "resumed_run_id"),
        "timeout_resume_iteration": _optional_integer(
            timeout_resume, "resume_iteration"
        ),
        "corrected_panel_rearm_authorization_id": _value(
            corrected_panel, "authorization_id"
        ),
        "corrected_panel_rearm_consumed": bool(
            _value(corrected_panel, "replacement_run_id")
        ),
        "corrected_panel_rearm_authorized_additional_calls": _integer(
            corrected_panel, "authorized_additional_calls"
        ),
        "corrected_panel_rearm_replacement_run_id": _value(
            corrected_panel, "replacement_run_id"
        ),
        "corrected_panel_citation_resume_extension_id": _value(
            corrected_panel_citation_resume, "extension_id"
        ),
        "corrected_panel_citation_resume_consumed": bool(
            _value(corrected_panel_citation_resume, "resumed_run_id")
        ),
        "corrected_panel_citation_resume_authorized_additional_calls": _integer(
            corrected_panel_citation_resume, "authorized_additional_calls"
        ),
        "corrected_panel_citation_resume_resumed_run_id": _value(
            corrected_panel_citation_resume, "resumed_run_id"
        ),
        "corrected_panel_citation_resume_iteration": _optional_integer(
            corrected_panel_citation_resume, "resume_iteration"
        ),
        "corrected_panel_citation_resume_stage": _value(
            corrected_panel_citation_resume, "resume_stage"
        ),
        "provider_free_partial_resume_id": _value(
            provider_free_partial_resume, "resume_id"
        ),
        "provider_free_partial_resume_run_id": _value(
            provider_free_partial_resume, "run_id"
        ),
        "provider_free_partial_resume_failed_call_id": _value(
            provider_free_partial_resume, "failed_call_id"
        ),
        "provider_free_partial_resume_failure_code": _value(
            provider_free_partial_resume, "failure_code"
        ),
        "provider_free_partial_resume_completed_iteration_count": _optional_integer(
            provider_free_partial_resume, "completed_iteration_count"
        ),
        "provider_free_partial_resume_iteration": _optional_integer(
            provider_free_partial_resume, "resume_iteration"
        ),
    }


def _value(row: Mapping[str, Any] | None, key: str) -> Any:
    return row.get(key) if row is not None else None


def _integer(row: Mapping[str, Any] | None, key: str) -> int:
    return int(_value(row, key) or 0)


def _optional_integer(row: Mapping[str, Any] | None, key: str) -> int | None:
    value = _value(row, key)
    return int(value) if value is not None else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _select_fields(
    source: Mapping[str, Any], fields: tuple[str, ...]
) -> dict[str, Any]:
    return {field: source[field] for field in fields if field in source}
