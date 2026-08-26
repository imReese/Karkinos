"""Evidence-contract projections for daily-candidate production readiness."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from server.services.daily_candidate_readiness_support import (
    is_nonnegative_int as _is_nonnegative_int,
)
from server.services.daily_candidate_readiness_support import (
    is_safe_code as _is_safe_code,
)
from server.services.daily_candidate_readiness_support import (
    is_safe_code_list as _is_safe_code_list,
)
from server.services.daily_candidate_readiness_support import is_sha256 as _is_sha256
from server.services.daily_candidate_readiness_support import mapping as _mapping
from server.services.daily_candidate_readiness_support import (
    matches_fingerprint as _matches_fingerprint,
)
from server.services.daily_candidate_readiness_support import safe_code as _safe_code
from server.services.daily_candidate_readiness_support import strings as _strings

OPERATOR_EVIDENCE_CONTRACT_VERSION = "karkinos.daily_candidate_operator_evidence.v1"
CANONICAL_EVIDENCE_AUTHORITY = "canonical_persisted_evidence_only"


def execution_evidence_contract_blockers(value: dict[str, Any]) -> list[str]:
    """Validate the sanitized current-execution evidence contract."""

    expected_schema = "karkinos.daily_candidate_execution_evidence_summary.v1"
    core = dict(value)
    evidence_fingerprint = core.pop("evidence_fingerprint", None)
    expected_core_fields = {
        "schema_version",
        "status",
        "current_execution_closure_fingerprint",
        "population_scope",
        "production_order_count",
        "clear_order_count",
        "reconciled_actual_order_count",
        "reconciled_no_fill_order_count",
        "comparison_coverage_complete",
        "blockers",
        "actual_orders_attributed_to_trial",
        "actual_orders_count_toward_simulated_trial_threshold",
        "persisted_evidence_only",
        "provider_contact_performed",
        "manual_review_required",
        "authorizes_execution",
        "does_not_submit_broker_order",
        "does_not_mutate_oms",
        "does_not_mutate_production_ledger",
        "does_not_change_capital_authority",
    }
    integer_fields = (
        "production_order_count",
        "clear_order_count",
        "reconciled_actual_order_count",
        "reconciled_no_fill_order_count",
    )
    if (
        set(core) != expected_core_fields
        or core.get("schema_version") != expected_schema
        or core.get("status") not in {"blocked", "not_required", "pass"}
        or not _matches_fingerprint(core, evidence_fingerprint)
        or core.get("population_scope") != "all_current_non_paper_shadow_oms_orders"
        or any(not _is_nonnegative_int(core.get(field)) for field in integer_fields)
        or not isinstance(core.get("comparison_coverage_complete"), bool)
        or not isinstance(core.get("blockers"), list)
        or not all(isinstance(item, str) and item for item in core.get("blockers", []))
        or core.get("actual_orders_attributed_to_trial") is not False
        or core.get("actual_orders_count_toward_simulated_trial_threshold") is not False
        or core.get("persisted_evidence_only") is not True
        or core.get("provider_contact_performed") is not False
        or not isinstance(core.get("manual_review_required"), bool)
        or core.get("authorizes_execution") is not False
        or core.get("does_not_submit_broker_order") is not True
        or core.get("does_not_mutate_oms") is not True
        or core.get("does_not_mutate_production_ledger") is not True
        or core.get("does_not_change_capital_authority") is not True
    ):
        return ["trial_current_execution_evidence_contract_invalid"]
    production_count = core["production_order_count"]
    clear_count = core["clear_order_count"]
    accounted_count = (
        core["reconciled_actual_order_count"] + core["reconciled_no_fill_order_count"]
    )
    if clear_count > production_count or accounted_count > clear_count:
        return ["trial_current_execution_evidence_contract_invalid"]
    if core["comparison_coverage_complete"] is True and (
        core["status"] not in {"not_required", "pass"}
        or core["blockers"]
        or not _is_sha256(core.get("current_execution_closure_fingerprint"))
        or production_count != clear_count
        or clear_count != accounted_count
        or core["manual_review_required"] is not False
    ):
        return ["trial_current_execution_evidence_contract_invalid"]
    if core["comparison_coverage_complete"] is False and (
        core["status"] != "blocked"
        or core["manual_review_required"] is not True
        or not core["blockers"]
    ):
        return ["trial_current_execution_evidence_contract_invalid"]
    if core["status"] == "not_required" and production_count != 0:
        return ["trial_current_execution_evidence_contract_invalid"]
    if core["status"] == "pass" and production_count == 0:
        return ["trial_current_execution_evidence_contract_invalid"]
    return []


def project_execution_evidence(value: dict[str, Any]) -> dict[str, Any]:
    """Return only the reviewed execution-evidence fields."""

    if execution_evidence_contract_blockers(value):
        return {
            "schema_version": "karkinos.daily_candidate_execution_evidence_summary.v1",
            "status": "blocked",
            "current_execution_closure_fingerprint": None,
            "population_scope": "all_current_non_paper_shadow_oms_orders",
            "production_order_count": 0,
            "clear_order_count": 0,
            "reconciled_actual_order_count": 0,
            "reconciled_no_fill_order_count": 0,
            "comparison_coverage_complete": False,
            "blockers": ["trial_current_execution_evidence_contract_invalid"],
            "actual_orders_attributed_to_trial": False,
            "actual_orders_count_toward_simulated_trial_threshold": False,
            "persisted_evidence_only": True,
            "provider_contact_performed": False,
            "manual_review_required": True,
            "authorizes_execution": False,
            "does_not_submit_broker_order": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "does_not_change_capital_authority": True,
            "evidence_fingerprint": None,
        }
    return {
        key: value.get(key)
        for key in (
            "schema_version",
            "status",
            "current_execution_closure_fingerprint",
            "population_scope",
            "production_order_count",
            "clear_order_count",
            "reconciled_actual_order_count",
            "reconciled_no_fill_order_count",
            "comparison_coverage_complete",
            "blockers",
            "actual_orders_attributed_to_trial",
            "actual_orders_count_toward_simulated_trial_threshold",
            "persisted_evidence_only",
            "provider_contact_performed",
            "manual_review_required",
            "authorizes_execution",
            "does_not_submit_broker_order",
            "does_not_mutate_oms",
            "does_not_mutate_production_ledger",
            "does_not_change_capital_authority",
            "evidence_fingerprint",
        )
    }


def operator_checklist_contract_blockers(
    preflight: dict[str, Any],
) -> list[str]:
    """Validate the ordered operator-evidence checklist contract."""

    checklist = preflight.get("operator_checklist")
    if not isinstance(checklist, list) or not checklist:
        return ["preflight_operator_checklist_contract_invalid"]
    for expected_step, raw_item in enumerate(checklist, start=1):
        item = _mapping(raw_item)
        if (
            item.get("step") != expected_step
            or not _is_safe_code(item.get("gate"))
            or not _is_safe_code(item.get("action"))
            or not _is_safe_code(item.get("completion_mode"))
            or item.get("evidence_contract_version")
            != OPERATOR_EVIDENCE_CONTRACT_VERSION
            or item.get("accepted_evidence_authority") != CANONICAL_EVIDENCE_AUTHORITY
            or item.get("owner_attestation_is_financial_fact") is not False
            or item.get("private_xls_rows_required") is not False
            or item.get("private_account_identifiers_required") is not False
            or item.get("automatic_action_performed") is not False
            or item.get("authorizes_execution") is not False
            or item.get("changes_capital_authority") is not False
            or not _is_safe_code_list(item.get("blockers"), allow_empty=True)
            or not _is_safe_code_list(item.get("required_evidence"))
            or not _is_safe_code_list(item.get("completion_criteria"))
        ):
            return ["preflight_operator_checklist_contract_invalid"]
    return []


def project_operator_checklist(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    """Sanitize operator steps without exposing underlying financial facts."""

    if operator_checklist_contract_blockers(preflight):
        return []
    projected = []
    for raw_item in preflight["operator_checklist"]:
        item = _mapping(raw_item)
        blockers = list(item["blockers"])
        blocker_summary = summarize_operator_blockers(blockers)
        projected.append(
            {
                "step": item["step"],
                "gate": item["gate"],
                "action": item["action"],
                "completion_mode": item["completion_mode"],
                "blocker_count": len(blockers),
                "unique_blocker_count": len(blocker_summary),
                "blocker_summary": blocker_summary,
                "evidence_contract_version": item["evidence_contract_version"],
                "required_evidence": list(item["required_evidence"]),
                "completion_criteria": list(item["completion_criteria"]),
                "accepted_evidence_authority": item["accepted_evidence_authority"],
                "owner_attestation_is_financial_fact": False,
                "private_xls_rows_required": False,
                "private_account_identifiers_required": False,
                "automatic_action_performed": False,
                "authorizes_execution": False,
                "changes_capital_authority": False,
            }
        )
    return projected


def summarize_operator_blockers(blockers: list[str]) -> list[dict[str, Any]]:
    """Collapse candidate-scoped blockers into deterministic counts."""

    counts: dict[str, int] = {}
    candidates: dict[str, set[str]] = {}
    for blocker in blockers:
        prefix, separator, remainder = blocker.partition(":")
        candidate_scoped = bool(
            separator
            and prefix.startswith("candidate_")
            and prefix.removeprefix("candidate_").isdigit()
            and remainder
        )
        code = remainder if candidate_scoped else blocker
        counts[code] = counts.get(code, 0) + 1
        if candidate_scoped:
            candidates.setdefault(code, set()).add(prefix)
    return [
        {
            "code": code,
            "occurrence_count": count,
            "affected_candidate_count": len(candidates.get(code, set())),
        }
        for code, count in counts.items()
    ]


def project_next_reviewed_window(trial: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitize the next reviewed market window."""

    schedule = _mapping(trial.get("background_schedule"))
    window = _mapping(schedule.get("next_reviewed_window"))
    if (
        schedule.get("schema_version")
        != "karkinos.daily_candidate_background_schedule.v3"
        or window.get("schema_version")
        != "karkinos.daily_candidate_next_reviewed_window.v1"
    ):
        return unavailable_next_reviewed_window_projection(
            "next_reviewed_window_not_exposed_by_running_service"
        )

    boundaries_clear = all(
        window.get(field) is False
        for field in (
            "provider_contact_performed",
            "database_writes_performed",
            "permits_retry_or_backfill",
            "changes_attempt_eligibility",
            "broker_submission_enabled",
            "authorizes_execution",
            "changes_capital_authority",
        )
    )
    if not boundaries_clear:
        return unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )

    status = window.get("status")
    blockers = _strings(window.get("blockers"))
    if any(not _is_safe_code(blocker) for blocker in blockers):
        return unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )
    if status == "unavailable":
        if (
            not blockers
            or window.get("market_date") is not None
            or window.get("window_start") is not None
            or window.get("window_end") is not None
            or window.get("is_current_market_date") is not False
            or window.get("official_calendar_verified") is not False
        ):
            return unavailable_next_reviewed_window_projection(
                "next_reviewed_window_contract_invalid"
            )
        return {
            **unavailable_next_reviewed_window_projection(blockers[0]),
            "blockers": blockers,
        }

    market_date = str(window.get("market_date") or "")
    run_date = str(schedule.get("run_date") or "")
    try:
        parsed_date = datetime.strptime(market_date, "%Y-%m-%d").date()
        parsed_run_date = datetime.strptime(run_date, "%Y-%m-%d").date()
        window_start = datetime.fromisoformat(str(window.get("window_start") or ""))
        window_end = datetime.fromisoformat(str(window.get("window_end") or ""))
    except ValueError:
        return unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )
    if (
        status != "available"
        or parsed_date.isoformat() != market_date
        or parsed_run_date.isoformat() != run_date
        or parsed_date < parsed_run_date
        or window_start.tzinfo is None
        or window_end.tzinfo is None
        or window_start.utcoffset() != timedelta(hours=8)
        or window_end.utcoffset() != timedelta(hours=8)
        or window_start.date() != parsed_date
        or window_end.date() != parsed_date
        or (window_start.hour, window_start.minute, window_start.second) != (9, 35, 0)
        or (window_end.hour, window_end.minute, window_end.second) != (9, 45, 0)
        or window_start.microsecond != 0
        or window_end.microsecond != 0
        or window_start.isoformat() != str(window.get("window_start") or "")
        or window_end.isoformat() != str(window.get("window_end") or "")
        or window.get("official_calendar_verified") is not True
        or blockers
        or not isinstance(window.get("is_current_market_date"), bool)
        or window.get("is_current_market_date") is not (market_date == run_date)
    ):
        return unavailable_next_reviewed_window_projection(
            "next_reviewed_window_contract_invalid"
        )
    return {
        "schema_version": "karkinos.daily_candidate_next_reviewed_window.v1",
        "status": "available",
        "market_date": market_date,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "is_current_market_date": window["is_current_market_date"],
        "official_calendar_verified": True,
        "blockers": [],
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "permits_retry_or_backfill": False,
        "changes_attempt_eligibility": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def unavailable_next_reviewed_window_projection(blocker: str) -> dict[str, Any]:
    """Return the fail-closed next-window projection."""

    return {
        "schema_version": "karkinos.daily_candidate_next_reviewed_window.v1",
        "status": "unavailable",
        "market_date": None,
        "window_start": None,
        "window_end": None,
        "is_current_market_date": False,
        "official_calendar_verified": False,
        "blockers": [_safe_code(blocker)],
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "permits_retry_or_backfill": False,
        "changes_attempt_eligibility": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


__all__ = [
    "CANONICAL_EVIDENCE_AUTHORITY",
    "OPERATOR_EVIDENCE_CONTRACT_VERSION",
    "execution_evidence_contract_blockers",
    "operator_checklist_contract_blockers",
    "project_execution_evidence",
    "project_next_reviewed_window",
    "project_operator_checklist",
    "summarize_operator_blockers",
    "unavailable_next_reviewed_window_projection",
]
