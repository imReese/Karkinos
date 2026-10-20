"""Pure projections for the controlled-execution operator read model."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

UNRECONCILED_SUBMISSION_STATUSES = frozenset(
    {"prepared", "submitted", "submission_unknown"}
)

ORDER_JOURNEY_ATTENTION = {
    "submission_unknown": (0, "critical"),
    "prepared_outcome_review_required": (1, "critical"),
    "open_broker_order_review_required": (2, "critical"),
    "execution_reconciliation_required": (10, "warning"),
    "submission_rejected": (20, "warning"),
    "execution_reconciliation_review_required": (30, "warning"),
    "terminal_clearance_review_required": (40, "warning"),
    "terminal_cleared_posting_review_required": (50, "warning"),
    "ledger_posted_account_truth_review_required": (60, "warning"),
    "ledger_corrected_account_truth_review_required": (60, "warning"),
}


def group_rows(
    rows: list[dict[str, Any]],
    key: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            grouped.setdefault(value, []).append(row)
    return grouped


def first_row_by_key(
    rows: list[dict[str, Any]],
    key: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value and value not in result:
            result[value] = row
    return result


def submission_intent_summary(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "submit_intent_id": str(row.get("submit_intent_id") or ""),
        "order_id": str(row.get("order_id") or ""),
        "gateway_id": str(row.get("gateway_id") or ""),
        "status": str(row.get("status") or ""),
        "prepared_at": str(row.get("prepared_at") or ""),
        "finalized_at": str(row.get("finalized_at") or ""),
    }


def reconciliation_run_summary(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "run_id": str(row.get("run_id") or ""),
        "run_date": str(row.get("run_date") or ""),
        "status": str(row.get("status") or ""),
        "item_count": int(row.get("item_count") or 0),
        "open_item_count": int(row.get("open_item_count") or 0),
        "updated_at": str(row.get("updated_at") or ""),
    }


def order_journey_summary(
    *,
    intent: dict[str, Any],
    reconciliation: dict[str, Any],
    clearance: dict[str, Any],
    posting_by_clearance: dict[str, dict[str, Any]],
    correction_by_posting: dict[str, dict[str, Any]],
    rejection_review: dict[str, Any],
    account_truth_evidence: dict[str, Any],
) -> dict[str, Any]:
    submit_intent_id = str(intent.get("submit_intent_id") or "")
    order_id = str(intent.get("order_id") or "")
    submission_status = str(intent.get("status") or "")
    reconciliation_item = json_object(reconciliation.get("item"))
    reconciliation_run = json_object(reconciliation.get("run"))
    clearance_id = str(clearance.get("clearance_id") or "")
    posting = posting_by_clearance.get(clearance_id, {}) if clearance_id else {}
    posting_id = str(posting.get("posting_id") or "")
    correction = correction_by_posting.get(posting_id, {}) if posting_id else {}
    account_truth_review = post_ledger_account_truth_review(
        posting=posting,
        correction=correction,
        evidence=account_truth_evidence,
    )

    suggested_action = str(reconciliation_item.get("suggested_action") or "")
    submitted = submission_status == "submitted"
    if correction and account_truth_review["complete"]:
        status = "ledger_corrected_account_truth_confirmed"
        next_action = "no_action_order_journey_complete"
    elif correction:
        status = "ledger_corrected_account_truth_review_required"
        next_action = "review_account_truth_after_ledger_correction"
    elif posting and account_truth_review["complete"]:
        status = "ledger_posted_account_truth_confirmed"
        next_action = "no_action_order_journey_complete"
    elif posting:
        status = "ledger_posted_account_truth_review_required"
        next_action = "review_account_truth_after_ledger_posting"
    elif clearance:
        status = "terminal_cleared_posting_review_required"
        next_action = "preview_reconciled_ledger_posting"
    elif submission_status == "submission_unknown":
        status = "submission_unknown"
        next_action = "query_submission_outcome_without_resubmit"
    elif submission_status == "prepared":
        status = "prepared_outcome_review_required"
        next_action = "query_prepared_submission_outcome_without_resubmit"
    elif submission_status == "rejected" and rejection_review:
        status = "submission_rejection_reviewed"
        next_action = "no_retry_create_new_decision_if_needed"
    elif submission_status == "rejected":
        status = "submission_rejected"
        next_action = "review_rejection_evidence_without_retry"
    elif not reconciliation_item:
        status = "execution_reconciliation_required"
        next_action = "run_or_review_execution_reconciliation"
    elif suggested_action in {
        "poll_or_import_controlled_submission_lifecycle_evidence",
        "review_partial_fill_and_import_account_truth",
    }:
        status = "open_broker_order_review_required"
        next_action = "review_open_order_or_prepare_manual_cancel_ticket"
    elif suggested_action and suggested_action != "no_action":
        status = "execution_reconciliation_review_required"
        next_action = "review_execution_reconciliation"
    else:
        status = "terminal_clearance_review_required"
        next_action = "preview_terminal_reconciliation_clearance"

    reconciliation_status = str(
        reconciliation_item.get("item_status")
        or reconciliation_item.get("status")
        or (
            "missing"
            if submitted and not reconciliation_item
            else ("not_applicable" if not reconciliation_item else "recorded")
        )
    )
    correction_status = (
        str(correction.get("status") or "recorded")
        if correction
        else ("not_required" if posting else "not_applicable")
    )
    attention = ORDER_JOURNEY_ATTENTION.get(status)
    return {
        "submit_intent_id": submit_intent_id,
        "order_id": order_id,
        "broker_order_id": str(intent.get("broker_order_id") or ""),
        "client_order_id": str(intent.get("client_order_id") or ""),
        "gateway_id": str(intent.get("gateway_id") or ""),
        "status": status,
        "next_operator_action": next_action,
        "attention_required": attention is not None,
        "attention_severity": attention[1] if attention is not None else "none",
        "blocks_new_submissions": bool(
            not clearance and submission_status in UNRECONCILED_SUBMISSION_STATUSES
        ),
        "prepared_at": str(intent.get("prepared_at") or ""),
        "updated_at": str(intent.get("updated_at") or ""),
        "last_recovery_at": str(intent.get("last_recovery_at") or ""),
        "stages": [
            {
                "key": "controlled_submission",
                "status": submission_status or "missing",
                "evidence_id": submit_intent_id,
                "complete": submission_status in {"submitted", "rejected"},
                "required": True,
            },
            *(
                [
                    {
                        "key": "controlled_submission_rejection_review",
                        "status": str(
                            rejection_review.get("disposition") or "not_recorded"
                        ),
                        "evidence_id": str(rejection_review.get("review_id") or ""),
                        "complete": bool(rejection_review),
                        "required": True,
                        "reviewer_id": str(rejection_review.get("reviewer_id") or ""),
                        "reviewed_at": str(rejection_review.get("recorded_at") or ""),
                        "review_fingerprint": str(
                            rejection_review.get("review_fingerprint") or ""
                        ),
                    }
                ]
                if submission_status == "rejected"
                else []
            ),
            {
                "key": "execution_reconciliation",
                "status": reconciliation_status,
                "evidence_id": str(reconciliation_run.get("run_id") or ""),
                "complete": bool(reconciliation_item)
                and suggested_action == "no_action",
                "required": submitted,
            },
            {
                "key": "terminal_reconciliation_clearance",
                "status": str(
                    clearance.get("status")
                    or ("missing" if submitted else "not_applicable")
                ),
                "evidence_id": clearance_id,
                "complete": bool(clearance),
                "required": submitted,
                "terminal_status": str(clearance.get("terminal_status") or ""),
                "fill_count": int(clearance.get("fill_count") or 0),
                "fill_quantity": str(clearance.get("fill_quantity") or ""),
                "cancelled_quantity": str(clearance.get("cancelled_quantity") or ""),
            },
            {
                "key": "reconciled_ledger_posting",
                "status": str(
                    posting.get("status")
                    or ("not_applied" if clearance else "not_applicable")
                ),
                "evidence_id": posting_id,
                "complete": bool(posting),
                "required": bool(clearance),
                "ledger_entry_count": int(posting.get("ledger_entry_count") or 0),
                "post_ledger_cutoff_id": int(posting.get("post_ledger_cutoff_id") or 0),
            },
            {
                "key": "append_only_ledger_correction",
                "status": correction_status,
                "evidence_id": str(correction.get("correction_id") or ""),
                "complete": bool(correction),
                "required": False,
                "reason_code": str(correction.get("reason_code") or ""),
                "post_ledger_cutoff_id": int(
                    correction.get("post_ledger_cutoff_id") or 0
                ),
            },
            account_truth_review,
        ],
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "broker_submission_performed": False,
        "broker_cancel_performed": False,
        "ledger_mutation_performed": False,
        "authority_changed": False,
    }


def post_ledger_account_truth_review(
    *,
    posting: dict[str, Any],
    correction: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    required = bool(posting)
    if not required:
        return {
            "key": "post_ledger_account_truth",
            "status": "not_applicable",
            "evidence_id": "",
            "complete": False,
            "required": False,
            "account_truth_gate_status": "not_evaluated",
            "ledger_coverage_status": "not_evaluated",
            "post_ledger_cutoff_id": 0,
            "blockers": [],
        }

    blockers: list[str] = []
    ledger_coverage = json_object(evidence.get("ledger_coverage"))
    if evidence.get("status") != "clear":
        blockers.append("post_ledger_account_truth_not_clear")
    if evidence.get("gate_status") != "pass":
        blockers.append("post_ledger_account_truth_gate_not_pass")
    if evidence.get("reconciliation_status") not in {"clear", "pass"}:
        blockers.append("post_ledger_account_truth_reconciliation_not_clear")
    unresolved_mismatch_count = integer(evidence.get("unresolved_mismatch_count"))
    if unresolved_mismatch_count is None:
        blockers.append("post_ledger_account_truth_mismatch_count_invalid")
    elif unresolved_mismatch_count != 0:
        blockers.append("post_ledger_account_truth_mismatch_unresolved")
    if evidence.get("data_freshness_status") != "fresh":
        blockers.append("post_ledger_account_truth_not_fresh")
    if ledger_coverage.get("status") != "covered":
        blockers.append("post_ledger_account_truth_ledger_not_covered")
    if not str(evidence.get("import_run_id") or ""):
        blockers.append("post_ledger_account_truth_import_identity_missing")
    if not str(evidence.get("source_fingerprint") or ""):
        blockers.append("post_ledger_account_truth_fingerprint_missing")
    if evidence.get("does_not_mutate_production_ledger") is not True:
        blockers.append("post_ledger_account_truth_ledger_boundary_invalid")
    if evidence.get("does_not_issue_execution_authority") is not True:
        blockers.append("post_ledger_account_truth_authority_boundary_invalid")
    if evidence.get("broker_submission_enabled") is not False:
        blockers.append("post_ledger_account_truth_submission_boundary_invalid")

    captured_at = parse_datetime(str(evidence.get("captured_at") or ""))
    latest_fact = correction or posting
    latest_fact_at = parse_datetime(
        str(
            latest_fact.get("applied_at")
            or latest_fact.get("recorded_at")
            or latest_fact.get("created_at")
            or ""
        )
    )
    same_posting_import = bool(
        not correction
        and str(posting.get("account_truth_import_run_id") or "")
        and str(posting.get("account_truth_import_run_id") or "")
        == str(evidence.get("import_run_id") or "")
    )
    if captured_at is None:
        blockers.append("post_ledger_account_truth_timestamp_invalid")
    elif latest_fact_at is None:
        if not same_posting_import:
            blockers.append("post_ledger_fact_timestamp_invalid")
    elif captured_at <= latest_fact_at and not same_posting_import:
        blockers.append("post_ledger_account_truth_predates_latest_fact")

    cutoff = integer(
        (correction or posting).get("post_ledger_cutoff_id")
        or posting.get("post_ledger_cutoff_id")
        or 0
    )
    if cutoff is None or (correction and cutoff <= 0):
        blockers.append("post_ledger_cutoff_invalid")
        cutoff = 0
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "key": "post_ledger_account_truth",
        "status": "pass" if not unique_blockers else "blocked",
        "evidence_id": str(evidence.get("import_run_id") or ""),
        "complete": not unique_blockers,
        "required": True,
        "account_truth_gate_status": str(evidence.get("gate_status") or "missing"),
        "ledger_coverage_status": str(ledger_coverage.get("status") or "missing"),
        "source_fingerprint": str(evidence.get("source_fingerprint") or ""),
        "captured_at": str(evidence.get("captured_at") or ""),
        "post_ledger_cutoff_id": cutoff,
        "blockers": unique_blockers,
    }


def prioritize_order_journey_attention(
    journeys: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep unresolved journeys visible even when newer journeys are closed."""

    indexed_attention = [
        (index, journey)
        for index, journey in enumerate(journeys)
        if journey.get("attention_required") is True
    ]
    indexed_attention.sort(
        key=lambda item: (
            ORDER_JOURNEY_ATTENTION.get(
                str(item[1].get("status") or ""),
                (999, "warning"),
            )[0],
            -item[0],
        )
    )
    return [journey for _, journey in indexed_attention]


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return aware_utc(parsed)


def integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def decimal_string(value: Any) -> str | None:
    parsed = decimal_value(value)
    return format(parsed, "f") if parsed is not None else None


def nonnegative_difference(capacity: Any, reserved: Any) -> str | None:
    parsed_capacity = decimal_value(capacity)
    parsed_reserved = decimal_value(reserved)
    if parsed_capacity is None or parsed_reserved is None:
        return None
    return format(max(Decimal("0"), parsed_capacity - parsed_reserved), "f")


def nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
