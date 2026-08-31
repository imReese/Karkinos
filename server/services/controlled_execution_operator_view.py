"""Read-only operator projection for persisted controlled-execution facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from server.services.controlled_broker_rejection_evidence import (
    controlled_broker_rejection_review_binding_blockers,
    list_controlled_broker_rejection_reviews,
)
from server.services.controlled_execution_operator_projection import (
    UNRECONCILED_SUBMISSION_STATUSES as _UNRECONCILED_SUBMISSION_STATUSES,
)
from server.services.controlled_execution_operator_projection import (
    aware_utc as _aware_utc,
)
from server.services.controlled_execution_operator_projection import (
    decimal_string as _decimal_string,
)
from server.services.controlled_execution_operator_projection import (
    first_row_by_key as _first_row_by_key,
)
from server.services.controlled_execution_operator_projection import (
    group_rows as _group_rows,
)
from server.services.controlled_execution_operator_projection import (
    json_list as _json_list,
)
from server.services.controlled_execution_operator_projection import (
    json_object as _json_object,
)
from server.services.controlled_execution_operator_projection import (
    nonnegative_difference as _nonnegative_difference,
)
from server.services.controlled_execution_operator_projection import (
    nonnegative_int as _nonnegative_int,
)
from server.services.controlled_execution_operator_projection import (
    order_journey_summary as _order_journey_summary,
)
from server.services.controlled_execution_operator_projection import (
    parse_datetime as _parse_datetime,
)
from server.services.controlled_execution_operator_projection import (
    prioritize_order_journey_attention as _prioritize_order_journey_attention,
)
from server.services.controlled_execution_operator_projection import (
    reconciliation_run_summary as _reconciliation_run_summary,
)
from server.services.controlled_execution_operator_projection import (
    submission_intent_summary as _submission_intent_summary,
)
from server.services.controlled_session_gate_contract import (
    CONTROLLED_SESSION_LIVE_GATE_MAX_AGE_SECONDS,
)

CONTROLLED_EXECUTION_OPERATOR_VIEW_SCHEMA_VERSION = (
    "karkinos.controlled_execution_operator_view.v4"
)

MAX_CONTROLLED_EXECUTION_SOURCE_ROWS = 500
MAX_RECONCILIATION_RUNS = 100
MAX_VISIBLE_SESSIONS = 50
MAX_VISIBLE_ORDER_JOURNEYS = 20
MAX_VISIBLE_ORDER_ATTENTION_ITEMS = 20


class ControlledExecutionOperatorViewService:
    """Project bounded authority and gate evidence without evaluating authority."""

    def __init__(
        self,
        *,
        db: Any,
        account_truth_evidence_reader: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._account_truth_evidence_reader = account_truth_evidence_reader
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
        try:
            rejection_reviews = list_controlled_broker_rejection_reviews(
                self._db,
                limit=MAX_CONTROLLED_EXECUTION_SOURCE_ROWS,
            )
        except Exception:
            rejection_reviews = []
            source_blockers.append("controlled_rejection_review_source_failed")
        if len(rejection_reviews) >= MAX_CONTROLLED_EXECUTION_SOURCE_ROWS:
            source_blockers.append("controlled_rejection_review_scan_truncated")
        reconciliation_runs = self._read_rows(
            "list_execution_reconciliation_runs_sync",
            limit=MAX_RECONCILIATION_RUNS,
            blocker_prefix="execution_reconciliation",
            blockers=source_blockers,
        )
        account_truth_evidence = self._read_account_truth_evidence(
            required=bool(ledger_postings),
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
        persisted_rejection_review_by_intent = _first_row_by_key(
            rejection_reviews,
            "submit_intent_id",
        )
        rejection_review_by_intent: dict[str, dict[str, Any]] = {}
        for intent in submission_intents:
            submit_intent_id = str(intent.get("submit_intent_id") or "")
            review = persisted_rejection_review_by_intent.get(submit_intent_id, {})
            review_blockers = controlled_broker_rejection_review_binding_blockers(
                review=review,
                intent=intent,
            )
            if review_blockers:
                source_blockers.extend(review_blockers)
            elif review:
                rejection_review_by_intent[submit_intent_id] = review
        reconciliation_by_order = self._reconciliation_by_order(
            reconciliation_runs,
            blockers=source_blockers,
        )

        all_order_journeys = [
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
                rejection_review=rejection_review_by_intent.get(
                    str(intent.get("submit_intent_id") or ""), {}
                ),
                account_truth_evidence=account_truth_evidence,
            )
            for intent in submission_intents
        ]
        recent_order_journeys = all_order_journeys[:MAX_VISIBLE_ORDER_JOURNEYS]
        all_attention_journeys = _prioritize_order_journey_attention(all_order_journeys)
        attention_order_journeys = all_attention_journeys[
            :MAX_VISIBLE_ORDER_ATTENTION_ITEMS
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
        primary_attention_order_journey = (
            attention_order_journeys[0] if attention_order_journeys else None
        )
        unique_source_blockers = list(dict.fromkeys(source_blockers))
        if unique_source_blockers:
            status = "blocked"
            next_action = "review_controlled_execution_blockers"
        elif primary_attention_order_journey is not None:
            next_action = str(primary_attention_order_journey["next_operator_action"])
            status = (
                "blocked_order_journey_attention_required"
                if blocked
                else "order_journey_attention_required"
            )
        elif blocked:
            status = "blocked"
            next_action = "review_controlled_execution_blockers"
        elif latest_order_journey is not None:
            next_action = str(latest_order_journey["next_operator_action"])
            status = "order_journey_closed"
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
            "attention_order_journey_count": len(all_attention_journeys),
            "visible_attention_order_journey_count": len(attention_order_journeys),
            "attention_queue_truncated": (
                len(all_attention_journeys) > len(attention_order_journeys)
            ),
            "primary_attention_order_journey": (primary_attention_order_journey),
            "attention_order_journeys": attention_order_journeys,
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
                "Order journeys project persisted submission, rejection-review, reconciliation, terminal-clearance, ledger-posting, and correction facts without applying any transition.",
                "A post-ledger journey closes only when canonical Account Truth evidence covers the current ledger and remains bound to the applicable posting or a newer correction review.",
                "The attention queue evaluates every bounded source row and prioritizes unresolved critical outcomes before newer lower-risk or closed journeys.",
                "A paused session has no resume action; recovery requires a separate signed equal-or-narrower replacement.",
            ],
        }

    def _read_account_truth_evidence(
        self,
        *,
        required: bool,
        blockers: list[str],
    ) -> dict[str, Any]:
        if not required or not callable(self._account_truth_evidence_reader):
            return {}
        try:
            evidence = self._account_truth_evidence_reader() or {}
        except Exception:
            blockers.append("post_ledger_account_truth_source_failed")
            return {}
        if not isinstance(evidence, dict):
            blockers.append("post_ledger_account_truth_source_invalid")
            return {}
        return dict(evidence)

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
