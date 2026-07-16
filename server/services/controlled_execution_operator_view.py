"""Read-only operator projection for persisted controlled-execution facts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from server.services.controlled_session_gate_contract import (
    CONTROLLED_SESSION_LIVE_GATE_MAX_AGE_SECONDS,
)

CONTROLLED_EXECUTION_OPERATOR_VIEW_SCHEMA_VERSION = (
    "karkinos.controlled_execution_operator_view.v2"
)

MAX_CONTROLLED_EXECUTION_SOURCE_ROWS = 500
MAX_RECONCILIATION_RUNS = 100
MAX_VISIBLE_SESSIONS = 50
MAX_VISIBLE_ORDER_JOURNEYS = 20

_UNRECONCILED_SUBMISSION_STATUSES = frozenset(
    {"prepared", "submitted", "submission_unknown"}
)


class ControlledExecutionOperatorViewService:
    """Project bounded authority and gate evidence without evaluating authority."""

    def __init__(
        self,
        *,
        db: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def summary(self) -> dict[str, Any]:
        as_of = _aware_utc(self._clock())
        source_blockers: list[str] = []
        sessions = self._read_rows(
            "list_controlled_session_runtime_sessions_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="runtime_session",
            blockers=source_blockers,
        )
        reservations = self._read_rows(
            "list_controlled_session_budget_reservations_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="budget_reservation",
            blockers=source_blockers,
        )
        admissions = self._read_rows(
            "list_controlled_session_rate_admissions_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="runtime_admission",
            blockers=source_blockers,
        )
        gate_snapshots = self._read_rows(
            "list_controlled_session_gate_snapshots_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="live_gate_snapshot",
            blockers=source_blockers,
        )
        submission_intents = self._read_rows(
            "list_controlled_broker_submit_intents_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="controlled_submission",
            blockers=source_blockers,
        )
        clearances = self._read_rows(
            "list_controlled_submission_reconciliation_clearances_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="terminal_clearance",
            blockers=source_blockers,
        )
        ledger_postings = self._read_rows(
            "list_controlled_submission_ledger_postings_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="controlled_ledger_posting",
            blockers=source_blockers,
        )
        ledger_corrections = self._read_rows(
            "list_controlled_submission_ledger_corrections_sync",
            limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            blocker_prefix="controlled_ledger_correction",
            blockers=source_blockers,
        )
        reconciliation_runs = self._read_rows(
            "list_execution_reconciliation_runs_sync",
            limit=MAX_RECONCILIATION_RUNS,
            blocker_prefix="execution_reconciliation",
            blockers=source_blockers,
        )

        reservations_by_id = {
            str(row.get("reservation_id") or ""): row
            for row in reservations
            if str(row.get("reservation_id") or "")
        }
        admissions_by_session = _group_rows(admissions, "session_id")
        latest_gate_by_session = _first_row_by_key(gate_snapshots, "session_id")
        intents_by_order = _group_rows(submission_intents, "order_id")
        clearance_by_intent = _first_row_by_key(clearances, "submit_intent_id")
        posting_by_clearance = _first_row_by_key(ledger_postings, "clearance_id")
        correction_by_posting = _first_row_by_key(
            ledger_corrections,
            "posting_id",
        )
        reconciliation_by_order = self._reconciliation_by_order(
            reconciliation_runs,
            blockers=source_blockers,
        )

        recent_order_journeys = [
            _order_journey_summary(
                intent=intent,
                reconciliation=reconciliation_by_order.get(
                    str(intent.get("order_id") or ""), {}
                ),
                clearance=clearance_by_intent.get(
                    str(intent.get("submit_intent_id") or ""), {}
                ),
                posting_by_clearance=posting_by_clearance,
                correction_by_posting=correction_by_posting,
            )
            for intent in submission_intents[:MAX_VISIBLE_ORDER_JOURNEYS]
        ]

        projected_sessions = [
            self._session_summary(
                row=row,
                reservation=reservations_by_id.get(
                    str(row.get("reservation_id") or ""), {}
                ),
                admissions=admissions_by_session.get(
                    str(row.get("session_id") or ""), []
                ),
                gate_snapshot=latest_gate_by_session.get(
                    str(row.get("session_id") or ""), {}
                ),
                intents_by_order=intents_by_order,
                cleared_intent_ids=frozenset(clearance_by_intent),
                reconciliation_by_order=reconciliation_by_order,
                as_of=as_of,
                source_blockers=source_blockers,
            )
            for row in sessions[:MAX_VISIBLE_SESSIONS]
        ]
        active = [item for item in projected_sessions if item["is_current_window"]]
        blocked = [item for item in active if item["blockers"]]
        paused = [item for item in projected_sessions if item["status"] == "paused"]
        latest_intent = _submission_intent_summary(
            submission_intents[0] if submission_intents else {}
        )
        latest_reconciliation = _reconciliation_run_summary(
            reconciliation_runs[0] if reconciliation_runs else {}
        )
        latest_order_journey = (
            recent_order_journeys[0] if recent_order_journeys else None
        )
        unique_source_blockers = list(dict.fromkeys(source_blockers))
        if unique_source_blockers:
            status = "blocked"
            next_action = "review_controlled_execution_blockers"
        elif blocked:
            status = "blocked"
            next_action = "review_controlled_execution_blockers"
        elif latest_order_journey is not None:
            status = "order_journey_review_required"
            next_action = str(latest_order_journey["next_operator_action"])
        elif not projected_sessions:
            status = "no_session_evidence"
            next_action = "no_action_default_disabled"
        elif active:
            status = "clear_read_only_evidence"
            next_action = "monitor_only_no_broker_submission"
        else:
            status = "historical_sessions_only"
            next_action = "no_action_default_disabled"
        return {
            "schema_version": CONTROLLED_EXECUTION_OPERATOR_VIEW_SCHEMA_VERSION,
            "as_of": as_of.isoformat(),
            "status": status,
            "next_operator_action": next_action,
            "session_count": len(sessions),
            "visible_session_count": len(projected_sessions),
            "current_window_session_count": len(active),
            "blocked_current_session_count": len(blocked),
            "paused_session_count": len(paused),
            "sessions": projected_sessions,
            "latest_submission": latest_intent,
            "latest_reconciliation": latest_reconciliation,
            "order_journey_count": len(submission_intents),
            "visible_order_journey_count": len(recent_order_journeys),
            "latest_order_journey": latest_order_journey,
            "recent_order_journeys": recent_order_journeys,
            "source_blockers": unique_source_blockers,
            "reads_persisted_facts_only": True,
            "provider_contact_performed": False,
            "runtime_connector_query_performed": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "authority_issue_enabled": False,
            "authority_renew_enabled": False,
            "authority_resume_enabled": False,
            "automatic_scale_up_enabled": False,
            "does_not_mutate_account_truth": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "limitations": [
                "This view projects persisted evidence and never contacts a broker or provider.",
                "Current-window status is not runtime authentication and does not authorize submission or cancellation.",
                "Remaining capital values are reservation headroom; remaining order slots count persisted admissions only.",
                "Order journeys project persisted submission, reconciliation, terminal-clearance, ledger-posting, and correction facts without applying any transition.",
                "A paused session has no resume action; recovery requires a separate signed equal-or-narrower replacement.",
            ],
        }

    def _read_rows(
        self,
        method_name: str,
        *,
        limit: int,
        blocker_prefix: str,
        blockers: list[str],
    ) -> list[dict[str, Any]]:
        method = getattr(self._db, method_name, None)
        if not callable(method):
            blockers.append(f"{blocker_prefix}_source_unavailable")
            return []
        try:
            rows = method(limit=limit)
        except Exception:
            blockers.append(f"{blocker_prefix}_source_failed")
            return []
        normalized = [dict(row) for row in rows if isinstance(row, dict)]
        if len(normalized) >= limit:
            blockers.append(f"{blocker_prefix}_scan_truncated")
        return normalized

    def _reconciliation_by_order(
        self,
        runs: list[dict[str, Any]],
        *,
        blockers: list[str],
    ) -> dict[str, dict[str, Any]]:
        method = getattr(self._db, "list_execution_reconciliation_items_sync", None)
        if not callable(method):
            blockers.append("execution_reconciliation_item_source_unavailable")
            return {}
        result: dict[str, dict[str, Any]] = {}
        for run in runs:
            run_id = str(run.get("run_id") or "")
            if not run_id:
                blockers.append("execution_reconciliation_run_identity_missing")
                continue
            try:
                items = method(run_id)
            except Exception:
                blockers.append(f"execution_reconciliation_item_source_failed:{run_id}")
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                order_id = str(item.get("order_id") or "")
                if not order_id or order_id in result:
                    continue
                result[order_id] = {"run": run, "item": dict(item)}
        return result

    def _session_summary(
        self,
        *,
        row: dict[str, Any],
        reservation: dict[str, Any],
        admissions: list[dict[str, Any]],
        gate_snapshot: dict[str, Any],
        intents_by_order: dict[str, list[dict[str, Any]]],
        cleared_intent_ids: frozenset[str],
        reconciliation_by_order: dict[str, dict[str, Any]],
        as_of: datetime,
        source_blockers: list[str],
    ) -> dict[str, Any]:
        session_id = str(row.get("session_id") or "")
        blockers: list[str] = []
        effective_at = _parse_datetime(str(row.get("effective_at") or ""))
        expires_at = _parse_datetime(str(row.get("expires_at") or ""))
        persisted_status = str(row.get("status") or "")
        is_current_window = bool(
            persisted_status == "enabled"
            and effective_at is not None
            and expires_at is not None
            and effective_at <= as_of < expires_at
        )
        if not session_id:
            blockers.append("runtime_session_identity_missing")
        if persisted_status == "revoked":
            blockers.append("runtime_session_revoked")
        elif persisted_status != "enabled":
            blockers.append("runtime_session_status_invalid")
        if effective_at is None or expires_at is None or expires_at <= effective_at:
            blockers.append("runtime_session_window_invalid")
        elif as_of < effective_at:
            blockers.append("runtime_session_not_yet_effective")
        elif as_of >= expires_at:
            blockers.append("runtime_session_expired")

        pause_state = self._runtime_state(session_id, blockers=source_blockers)
        pause_reasons = _json_list(pause_state.get("reasons_json"))
        if pause_state.get("status") == "paused":
            blockers.append("runtime_session_paused")

        reservation_payload = _json_object(reservation.get("payload_json"))
        reserved_budget = _json_object(reservation_payload.get("reserved_budget"))
        reservation_capacity = _json_object(
            reservation_payload.get("reservation_capacity")
        )
        if not reservation or str(reservation.get("status") or "") != "reserved":
            blockers.append("runtime_session_budget_reservation_missing")
        elif not reserved_budget or not reservation_capacity:
            blockers.append("runtime_session_budget_payload_invalid")

        ordered_admissions = sorted(
            admissions,
            key=lambda item: (
                int(item.get("admitted_at_epoch_ms") or 0),
                int(item.get("id") or 0),
            ),
            reverse=True,
        )
        admitted_order_ids = list(
            dict.fromkeys(
                str(item.get("order_id") or "")
                for item in ordered_admissions
                if str(item.get("order_id") or "")
            )
        )
        reserved_order_count = _nonnegative_int(reserved_budget.get("order_count"))
        remaining_order_slots = max(0, reserved_order_count - len(admitted_order_ids))
        last_admission = ordered_admissions[0] if ordered_admissions else {}
        last_order_id = str(last_admission.get("order_id") or "")
        last_intent = (
            (intents_by_order.get(last_order_id) or [{}])[0] if last_order_id else {}
        )
        last_reconciliation = reconciliation_by_order.get(last_order_id, {})
        last_reconciliation_item = _json_object(last_reconciliation.get("item"))
        last_reconciliation_run = _json_object(last_reconciliation.get("run"))
        if last_order_id and not last_reconciliation:
            blockers.append("latest_order_reconciliation_missing")
        elif (
            last_order_id
            and str(last_reconciliation_item.get("suggested_action") or "")
            != "no_action"
        ):
            blockers.append("latest_order_reconciliation_not_clear")

        relevant_intents = [
            item
            for order_id in admitted_order_ids
            for item in intents_by_order.get(order_id, [])
        ]
        if any(
            str(item.get("status") or "") in _UNRECONCILED_SUBMISSION_STATUSES
            and str(item.get("submit_intent_id") or "") not in cleared_intent_ids
            for item in relevant_intents
        ):
            blockers.append("unreconciled_controlled_submission_present")

        gate_blockers = _json_list(gate_snapshot.get("blockers_json"))
        if is_current_window:
            if not gate_snapshot:
                blockers.append("runtime_live_gate_snapshot_missing")
            else:
                if str(gate_snapshot.get("status") or "") != "clear":
                    blockers.append("runtime_live_gate_snapshot_not_clear")
                observed_at_ms = _nonnegative_int(
                    gate_snapshot.get("observed_at_epoch_ms")
                )
                as_of_ms = int(as_of.timestamp() * 1000)
                if observed_at_ms > as_of_ms:
                    blockers.append("runtime_live_gate_snapshot_in_future")
                elif as_of_ms - observed_at_ms > (
                    CONTROLLED_SESSION_LIVE_GATE_MAX_AGE_SECONDS * 1000
                ):
                    blockers.append("runtime_live_gate_snapshot_stale")
                blockers.extend(
                    f"runtime_live_gate:{item}" for item in gate_blockers if item
                )

        unique_blockers = list(dict.fromkeys(blockers))
        if pause_state.get("status") == "paused":
            status = "paused"
        elif persisted_status == "revoked":
            status = "revoked"
        elif expires_at is not None and as_of >= expires_at:
            status = "expired"
        elif effective_at is not None and as_of < effective_at:
            status = "scheduled"
        elif unique_blockers:
            status = "blocked"
        else:
            status = "current_clear_evidence"
        return {
            "session_id": session_id,
            "session_fingerprint": str(row.get("session_fingerprint") or ""),
            "reservation_id": str(row.get("reservation_id") or ""),
            "authorization_id": str(row.get("authorization_id") or ""),
            "account_alias": str(row.get("account_alias") or ""),
            "strategy_id": str(row.get("strategy_id") or ""),
            "status": status,
            "persisted_status": persisted_status,
            "is_current_window": is_current_window,
            "effective_at": str(row.get("effective_at") or ""),
            "expires_at": str(row.get("expires_at") or ""),
            "authorized_capital": _decimal_string(
                reservation_capacity.get("capital_value")
            ),
            "effective_capital_at_risk": _decimal_string(
                reserved_budget.get("gross_order_value")
            ),
            "remaining_budget": {
                "capital_headroom": _nonnegative_difference(
                    reservation_capacity.get("capital_value"),
                    reserved_budget.get("gross_order_value"),
                ),
                "cash_headroom": _nonnegative_difference(
                    reservation_capacity.get("cash_value"),
                    reserved_budget.get("buy_value"),
                ),
                "turnover_headroom": _nonnegative_difference(
                    reservation_capacity.get("daily_turnover_value"),
                    reserved_budget.get("daily_turnover_value"),
                ),
                "remaining_order_slots": remaining_order_slots,
                "reserved_order_count": reserved_order_count,
                "admitted_order_count": len(admitted_order_ids),
            },
            "allowed_symbols": sorted(
                str(item)
                for item in _json_object(reserved_budget.get("by_symbol"))
                if str(item)
            ),
            "last_order": {
                "order_id": last_order_id,
                "admitted_at": str(last_admission.get("admitted_at") or ""),
                "admission_id": str(last_admission.get("admission_id") or ""),
                "submission_status": str(last_intent.get("status") or ""),
                "submit_intent_id": str(last_intent.get("submit_intent_id") or ""),
            },
            "last_reconciliation": {
                "run_id": str(last_reconciliation_run.get("run_id") or ""),
                "run_status": str(last_reconciliation_run.get("status") or ""),
                "item_status": str(last_reconciliation_item.get("item_status") or ""),
                "suggested_action": str(
                    last_reconciliation_item.get("suggested_action") or ""
                ),
                "updated_at": str(last_reconciliation_run.get("updated_at") or ""),
            },
            "latest_gate_snapshot": {
                "snapshot_id": str(gate_snapshot.get("snapshot_id") or ""),
                "status": str(gate_snapshot.get("status") or ""),
                "observed_at": str(gate_snapshot.get("observed_at") or ""),
                "blockers": gate_blockers,
            },
            "pause": {
                "status": str(pause_state.get("status") or "not_paused"),
                "pause_event_id": str(pause_state.get("pause_event_id") or ""),
                "paused_at": str(pause_state.get("paused_at") or ""),
                "reasons": pause_reasons,
                "resume_available": False,
                "replacement_review_required": bool(pause_reasons),
            },
            "blockers": unique_blockers,
            "runtime_authentication_evaluated": False,
            "runtime_authority_granted": False,
            "broker_submission_enabled": False,
        }

    def _runtime_state(
        self,
        session_id: str,
        *,
        blockers: list[str],
    ) -> dict[str, Any]:
        method = getattr(self._db, "get_controlled_session_runtime_state_sync", None)
        if not callable(method):
            blockers.append("runtime_pause_state_source_unavailable")
            return {}
        try:
            row = method(session_id)
        except Exception:
            blockers.append("runtime_pause_state_source_failed")
            return {}
        return dict(row) if isinstance(row, dict) else {}


def _group_rows(
    rows: list[dict[str, Any]],
    key: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            grouped.setdefault(value, []).append(row)
    return grouped


def _first_row_by_key(
    rows: list[dict[str, Any]],
    key: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value and value not in result:
            result[value] = row
    return result


def _submission_intent_summary(row: dict[str, Any]) -> dict[str, Any] | None:
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


def _reconciliation_run_summary(row: dict[str, Any]) -> dict[str, Any] | None:
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


def _order_journey_summary(
    *,
    intent: dict[str, Any],
    reconciliation: dict[str, Any],
    clearance: dict[str, Any],
    posting_by_clearance: dict[str, dict[str, Any]],
    correction_by_posting: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    submit_intent_id = str(intent.get("submit_intent_id") or "")
    order_id = str(intent.get("order_id") or "")
    submission_status = str(intent.get("status") or "")
    reconciliation_item = _json_object(reconciliation.get("item"))
    reconciliation_run = _json_object(reconciliation.get("run"))
    clearance_id = str(clearance.get("clearance_id") or "")
    posting = posting_by_clearance.get(clearance_id, {}) if clearance_id else {}
    posting_id = str(posting.get("posting_id") or "")
    correction = correction_by_posting.get(posting_id, {}) if posting_id else {}

    suggested_action = str(reconciliation_item.get("suggested_action") or "")
    submitted = submission_status == "submitted"
    if correction:
        status = "ledger_corrected_account_truth_review_required"
        next_action = "review_account_truth_after_ledger_correction"
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
    return {
        "submit_intent_id": submit_intent_id,
        "order_id": order_id,
        "broker_order_id": str(intent.get("broker_order_id") or ""),
        "client_order_id": str(intent.get("client_order_id") or ""),
        "gateway_id": str(intent.get("gateway_id") or ""),
        "status": status,
        "next_operator_action": next_action,
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
        ],
        "reads_persisted_facts_only": True,
        "provider_contact_performed": False,
        "broker_submission_performed": False,
        "broker_cancel_performed": False,
        "ledger_mutation_performed": False,
        "authority_changed": False,
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return _aware_utc(parsed)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _decimal_string(value: Any) -> str | None:
    parsed = _decimal(value)
    return format(parsed, "f") if parsed is not None else None


def _nonnegative_difference(capacity: Any, reserved: Any) -> str | None:
    parsed_capacity = _decimal(capacity)
    parsed_reserved = _decimal(reserved)
    if parsed_capacity is None or parsed_reserved is None:
        return None
    return format(max(Decimal("0"), parsed_capacity - parsed_reserved), "f")


def _nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
