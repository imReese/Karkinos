"""Forward operating-trial evidence for production daily strategy candidates."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from server.services.account_truth_replay import (
    build_account_truth_replay_evidence,
    verify_account_truth_replay_evidence,
)
from server.services.daily_candidate_execution_closure import (
    build_daily_candidate_execution_closure,
    project_daily_candidate_execution_evidence_summary,
    verify_daily_candidate_execution_closure,
)
from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE,
    DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION,
    DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE,
    DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
    DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION,
    DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
    DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
    build_daily_candidate_strategy_gate_binding,
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
    daily_candidate_strategy_operating_constraints_blockers,
    manual_ticket_candidate_fingerprint,
    project_daily_candidate_background_schedule,
)
from server.services.strategy_promotion_pipeline import (
    resolve_strategy_order_generation_gate,
)

DAILY_CANDIDATE_TRIAL_SCHEMA_VERSION = "karkinos.daily_candidate_trial.v2"
DAILY_CANDIDATE_TRIAL_REVIEW_SCHEMA_VERSION = "karkinos.daily_candidate_trial_review.v2"
DAILY_CANDIDATE_TRIAL_REVIEW_EVENT_TYPE = "daily_candidate_trial.review_recorded"
DAILY_CANDIDATE_TRIAL_REVIEW_ENTITY_TYPE = "daily_candidate_trial_review"
DAILY_CANDIDATE_TRIAL_EVENT_SOURCE = "daily_candidate_trial"
DAILY_CANDIDATE_TRIAL_REVIEW_CONFIRMATION = (
    "record_daily_candidate_trial_review_without_trade_or_capital_authority"
)

TARGET_QUALIFYING_TRADING_DAYS = 20
TARGET_SIMULATED_ORDERS = 50

StrategyGateResolver = Callable[..., tuple[dict[str, Any], list[str]]]
ExecutionClosureResolver = Callable[[Any], dict[str, Any]]
AccountTruthReplayResolver = Callable[..., dict[str, Any]]

_SUPPORTED_REVIEW_DECISIONS = {
    "go_to_bounded_manual_trial",
    "continue_paper_shadow",
    "no_go",
}
_VERIFIED_CALENDAR_STATUSES = {"accepted", "confirmed", "verified"}
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class DailyCandidateTrialReviewRejected(ValueError):
    """Raised when a human trial review is stale or exceeds evidence."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class DailyCandidateTrialService:
    """Project and review a frozen-strategy paper/shadow operating sample."""

    def __init__(
        self,
        *,
        db: Any,
        clock: Callable[[], datetime] | None = None,
        strategy_gate_resolver: StrategyGateResolver | None = None,
        execution_closure_resolver: ExecutionClosureResolver | None = None,
        account_truth_replay_resolver: AccountTruthReplayResolver | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._strategy_gate_resolver = (
            strategy_gate_resolver or resolve_strategy_order_generation_gate
        )
        self._execution_closure_resolver = (
            execution_closure_resolver or build_daily_candidate_execution_closure
        )
        self._account_truth_replay_resolver = (
            account_truth_replay_resolver or build_account_truth_replay_evidence
        )

    def get_status(self) -> dict[str, Any]:
        as_of = _aware_utc(self._clock())
        try:
            current_execution_closure = self._execution_closure_resolver(self._db)
        except Exception:
            current_execution_closure = None
        current_execution_evidence = project_daily_candidate_execution_evidence_summary(
            current_execution_closure
        )
        rows, scan_truncated = self._read_complete_run_history()
        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_date[str(row.get("run_date") or "")].append(row)

        all_qualifying_days: list[dict[str, Any]] = []
        excluded_days: list[dict[str, Any]] = []

        for run_date in sorted(by_date):
            day = self._evaluate_day(
                run_date=run_date,
                rows=by_date[run_date],
                as_of=as_of,
                current_execution_closure=current_execution_closure,
            )
            if day["status"] == "qualifying":
                all_qualifying_days.append(day)
            else:
                excluded_days.append(day)

        evaluated_days = sorted(
            [*all_qualifying_days, *excluded_days],
            key=lambda item: str(item.get("run_date") or ""),
        )
        latest_daily_run = evaluated_days[-1] if evaluated_days else None
        active_binding = _latest_complete_trial_binding(evaluated_days)
        epoch_days = _current_trial_epoch_days(
            evaluated_days=evaluated_days,
            active_binding=active_binding,
        )
        qualifying_days = [
            day
            for day in epoch_days
            if day["status"] == "qualifying" and _trial_binding(day) == active_binding
        ]
        current_dates = {str(day.get("run_date") or "") for day in qualifying_days}
        superseded_qualifying_days = [
            day
            for day in all_qualifying_days
            if str(day.get("run_date") or "") not in current_dates
        ]
        strategy_refs = list(active_binding[0]) if active_binding is not None else []
        fee_schedule_refs = (
            list(active_binding[1]) if active_binding is not None else []
        )
        strategy_operating_constraint_refs = (
            list(active_binding[2]) if active_binding is not None else []
        )
        epoch_binding_days = [
            day for day in epoch_days if _trial_binding(day) == active_binding
        ]
        trial_epoch_start_date = (
            str(epoch_binding_days[0].get("run_date") or "")
            if epoch_binding_days
            else None
        )
        trial_epoch_id = (
            _fingerprint(
                {
                    "schema_version": "karkinos.daily_candidate_trial_epoch.v2",
                    "trial_epoch_start_date": trial_epoch_start_date,
                    "strategy_advancement_refs": strategy_refs,
                    "reviewed_fee_schedule_refs": fee_schedule_refs,
                    "strategy_operating_constraint_refs": (
                        strategy_operating_constraint_refs
                    ),
                }
            )
            if trial_epoch_start_date and active_binding is not None
            else None
        )

        global_blockers: list[str] = []
        if active_binding is None and evaluated_days:
            global_blockers.append("current_trial_binding_missing")
        if latest_daily_run is not None and _trial_binding(latest_daily_run) is None:
            global_blockers.append("latest_daily_candidate_binding_unresolved")
        if latest_daily_run is not None and latest_daily_run.get("status") != (
            "qualifying"
        ):
            global_blockers.append("latest_daily_candidate_not_qualifying")
        if not current_execution_evidence["comparison_coverage_complete"]:
            global_blockers.append("current_execution_evidence_incomplete")

        order_count = sum(int(day["simulated_order_count"]) for day in qualifying_days)
        day_count = len(qualifying_days)
        if day_count < TARGET_QUALIFYING_TRADING_DAYS:
            global_blockers.append("qualifying_trading_days_insufficient")
        if order_count < TARGET_SIMULATED_ORDERS:
            global_blockers.append("simulated_order_count_insufficient")
        if scan_truncated:
            global_blockers.append("daily_candidate_run_scan_truncated")

        global_blockers = list(dict.fromkeys(global_blockers))
        eligible = not global_blockers
        trial_core = {
            "schema_version": DAILY_CANDIDATE_TRIAL_SCHEMA_VERSION,
            "trial_epoch_id": trial_epoch_id,
            "trial_epoch_start_date": trial_epoch_start_date,
            "target_qualifying_trading_days": TARGET_QUALIFYING_TRADING_DAYS,
            "target_simulated_orders": TARGET_SIMULATED_ORDERS,
            "qualifying_trading_day_count": day_count,
            "simulated_order_count": order_count,
            "remaining_trading_days": max(
                TARGET_QUALIFYING_TRADING_DAYS - day_count,
                0,
            ),
            "remaining_simulated_orders": max(TARGET_SIMULATED_ORDERS - order_count, 0),
            "strategy_advancement_refs": strategy_refs,
            "reviewed_fee_schedule_refs": fee_schedule_refs,
            "strategy_operating_constraint_refs": (strategy_operating_constraint_refs),
            "qualifying_days": qualifying_days,
            "superseded_qualifying_day_count": len(superseded_qualifying_days),
            "superseded_qualifying_days": superseded_qualifying_days,
            "excluded_days": excluded_days,
            "run_scan_truncated": scan_truncated,
            "latest_daily_run": latest_daily_run,
            "current_execution_evidence": current_execution_evidence,
            "blockers": global_blockers,
        }
        trial_fingerprint = _fingerprint(trial_core)
        latest_review = self._latest_review(trial_fingerprint)
        status = (
            "eligible_for_human_go_no_go_review"
            if eligible
            else "collecting_forward_operating_evidence"
        )
        if latest_review is not None:
            status = f"human_{latest_review['decision']}_recorded_without_authority"

        return {
            **trial_core,
            "status": status,
            "eligible_for_human_go_no_go_review": eligible,
            "trial_fingerprint": trial_fingerprint,
            "latest_review": latest_review,
            "background_schedule": project_daily_candidate_background_schedule(
                db=self._db,
                now=as_of,
            ),
            "next_safe_action": (
                "record_human_go_no_go_review"
                if eligible and latest_review is None
                else (
                    "continue_daily_paper_shadow_collection"
                    if latest_review is None
                    else "follow_recorded_review_without_automatic_authority_change"
                )
            ),
            "profitability_claim": "not_established",
            "does_not_establish_future_profitability": True,
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "automatic_order_submission_enabled": False,
            "automatic_capital_scaling_enabled": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
            "limitations": [
                "The trial measures deterministic forward operating evidence, not guaranteed profit.",
                "A GO review is only a research conclusion for a separately bounded manual trial.",
                "Every future order must still re-pass current Account Truth, market, risk, paper/shadow, reconciliation, and human-confirmation gates.",
            ],
        }

    def _read_complete_run_history(self) -> tuple[list[dict[str, Any]], bool]:
        reader = getattr(self._db, "list_all_automation_runs_for_type_sync", None)
        if callable(reader):
            return (
                reader(run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE),
                False,
            )
        rows = self._db.list_automation_runs_sync(
            run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
            limit=501,
            offset=0,
        )
        return rows[:500], len(rows) > 500

    def record_review(
        self,
        *,
        expected_trial_fingerprint: str,
        decision: str,
        reviewed_by: str,
        note: str,
        confirmation: str,
    ) -> dict[str, Any]:
        current = self.get_status()
        rejection_reasons: list[str] = []
        if expected_trial_fingerprint != current["trial_fingerprint"]:
            rejection_reasons.append("trial_fingerprint_drifted")
        if decision not in _SUPPORTED_REVIEW_DECISIONS:
            rejection_reasons.append("unsupported_review_decision")
        if not str(reviewed_by or "").strip():
            rejection_reasons.append("reviewed_by_missing")
        if not str(note or "").strip():
            rejection_reasons.append("review_note_missing")
        if confirmation != DAILY_CANDIDATE_TRIAL_REVIEW_CONFIRMATION:
            rejection_reasons.append("review_confirmation_mismatch")
        if (
            decision == "go_to_bounded_manual_trial"
            and not current["eligible_for_human_go_no_go_review"]
        ):
            rejection_reasons.append("go_decision_exceeds_operating_evidence")

        recorded_at = _aware_utc(self._clock()).isoformat()
        identity = {
            "trial_fingerprint": expected_trial_fingerprint,
            "execution_evidence_fingerprint": current["current_execution_evidence"][
                "evidence_fingerprint"
            ],
            "decision": decision,
            "reviewed_by": str(reviewed_by or "").strip(),
            "note": str(note or "").strip(),
            "confirmation": confirmation,
            "rejection_reasons": rejection_reasons,
        }
        review_id = _fingerprint(identity)
        existing = self._db.list_events_sync(
            event_type=DAILY_CANDIDATE_TRIAL_REVIEW_EVENT_TYPE,
            entity_type=DAILY_CANDIDATE_TRIAL_REVIEW_ENTITY_TYPE,
            entity_id=review_id,
            source=DAILY_CANDIDATE_TRIAL_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            response = _review_event_response(existing[0], reused=True)
        else:
            payload = {
                "schema_version": DAILY_CANDIDATE_TRIAL_REVIEW_SCHEMA_VERSION,
                "review_id": review_id,
                "trial_fingerprint": expected_trial_fingerprint,
                "execution_evidence_fingerprint": current["current_execution_evidence"][
                    "evidence_fingerprint"
                ],
                "decision": decision,
                "reviewed_by": str(reviewed_by or "").strip(),
                "note": str(note or "").strip(),
                "confirmation": confirmation,
                "status": "rejected" if rejection_reasons else "recorded",
                "rejection_reasons": rejection_reasons,
                "operating_evidence_eligible": current[
                    "eligible_for_human_go_no_go_review"
                ],
                "runtime_authority_status": "unchanged",
                "broker_submission_enabled": False,
                "authorizes_execution": False,
                "changes_capital_authority": False,
            }
            self._db.append_event_sync(
                event_type=DAILY_CANDIDATE_TRIAL_REVIEW_EVENT_TYPE,
                timestamp=recorded_at,
                entity_type=DAILY_CANDIDATE_TRIAL_REVIEW_ENTITY_TYPE,
                entity_id=review_id,
                source=DAILY_CANDIDATE_TRIAL_EVENT_SOURCE,
                source_ref=expected_trial_fingerprint,
                payload=payload,
            )
            saved = self._db.list_events_sync(
                event_type=DAILY_CANDIDATE_TRIAL_REVIEW_EVENT_TYPE,
                entity_type=DAILY_CANDIDATE_TRIAL_REVIEW_ENTITY_TYPE,
                entity_id=review_id,
                source=DAILY_CANDIDATE_TRIAL_EVENT_SOURCE,
                limit=1,
            )
            if not saved:
                raise RuntimeError("daily candidate trial review was not recorded")
            response = _review_event_response(saved[0], reused=False)

        if rejection_reasons:
            raise DailyCandidateTrialReviewRejected(
                "daily candidate trial review rejected: "
                + ", ".join(rejection_reasons),
                evidence=response,
            )
        return response

    def list_reviews(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=DAILY_CANDIDATE_TRIAL_REVIEW_EVENT_TYPE,
            entity_type=DAILY_CANDIDATE_TRIAL_REVIEW_ENTITY_TYPE,
            source=DAILY_CANDIDATE_TRIAL_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_review_event_response(row, reused=False) for row in rows]

    def _evaluate_day(
        self,
        *,
        run_date: str,
        rows: list[dict[str, Any]],
        as_of: datetime,
        current_execution_closure: dict[str, Any] | None,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        try:
            parsed_run_date = date.fromisoformat(run_date)
        except ValueError:
            parsed_run_date = None
            blockers.append("daily_candidate_run_date_invalid")
        if (
            parsed_run_date is not None
            and parsed_run_date > as_of.astimezone(_SHANGHAI_TZ).date()
        ):
            blockers.append("daily_candidate_run_date_in_future")
        payloads = [(_payload(row), row) for row in rows]
        v2 = [
            (payload, row)
            for payload, row in payloads
            if payload.get("schema_version")
            == DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION
        ]
        if not v2:
            blockers.append("daily_candidate_contract_missing")
            return _day_result(run_date=run_date, blockers=blockers)

        fingerprints = {
            str(payload.get("input_fingerprint") or "") for payload, _ in v2
        }
        if "" in fingerprints:
            blockers.append("daily_candidate_input_fingerprint_missing")
        if any(not _is_sha256(value) for value in fingerprints if value):
            blockers.append("daily_candidate_input_fingerprint_invalid")
        if any(
            str(payload.get("input_fingerprint") or "")
            != daily_candidate_input_fingerprint(payload)
            for payload, _ in v2
        ):
            blockers.append("daily_candidate_input_fingerprint_mismatch")
        if any(
            payload.get("input_identity_schema_version")
            != DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION
            for payload, _ in v2
        ):
            blockers.append("daily_candidate_input_identity_contract_invalid")
        if len(fingerprints) != 1:
            blockers.append("daily_candidate_input_conflict")

        payload, row = max(
            v2,
            key=lambda item: str(
                item[1].get("finished_at")
                or item[1].get("updated_at")
                or item[1].get("started_at")
                or ""
            ),
        )
        for field in ("started_at", "finished_at"):
            timestamp = _aware_datetime(row.get(field))
            if timestamp is None:
                blockers.append(f"daily_candidate_run_{field}_invalid")
            elif timestamp > as_of:
                blockers.append(f"daily_candidate_run_{field}_in_future")
        gate = _object(payload.get("production_gate"))
        record_fingerprint = str(payload.get("production_record_fingerprint") or "")
        if not record_fingerprint:
            blockers.append("production_record_fingerprint_missing")
        elif record_fingerprint != daily_candidate_record_fingerprint(payload):
            blockers.append("production_record_fingerprint_mismatch")
        if gate.get("status") != "pass":
            blockers.extend(str(item) for item in gate.get("blockers") or [])
            blockers.append("daily_candidate_production_gate_not_pass")
        if payload.get("decision_outcome") != "manual_order_ticket_candidate":
            blockers.append("manual_order_ticket_candidate_missing")
        ticket_candidates = _list(payload.get("manual_order_ticket_candidates"))
        ticket_candidate_count = _nonnegative_int(
            payload.get("manual_ticket_candidate_count")
        )
        if ticket_candidate_count is None:
            blockers.append("manual_order_ticket_candidate_count_invalid")
            ticket_candidate_count = 0
        if ticket_candidate_count <= 0:
            blockers.append("manual_order_ticket_candidate_missing")
        if len(ticket_candidates) != ticket_candidate_count:
            blockers.append("manual_order_ticket_candidate_count_mismatch")
        if payload.get("broker_submission_enabled") is not False:
            blockers.append("broker_submission_boundary_invalid")
        if payload.get("does_not_submit_broker_order") is not True:
            blockers.append("broker_no_submit_evidence_missing")
        if str(row.get("status") or "") != "paper_shadow_completed":
            blockers.append("daily_candidate_run_status_not_complete")

        snapshot = _object(payload.get("input_snapshot"))
        if not _is_sha256(snapshot.get("decision_plan_fingerprint")):
            blockers.append("daily_candidate_decision_plan_fingerprint_invalid")
        if str(snapshot.get("decision_date") or "") != run_date:
            blockers.append("daily_candidate_decision_date_mismatch")
        if str(snapshot.get("plan_date") or "") != run_date:
            blockers.append("daily_candidate_plan_date_mismatch")
        decision_window = _object(snapshot.get("decision_window"))
        if decision_window.get("schema_version") != (
            DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION
        ):
            blockers.append("daily_candidate_decision_window_contract_invalid")
        if decision_window.get("timezone") != "Asia/Shanghai":
            blockers.append("daily_candidate_decision_window_timezone_invalid")
        if decision_window.get("start") != "09:35":
            blockers.append("daily_candidate_decision_window_start_invalid")
        if decision_window.get("end_exclusive") != "09:45":
            blockers.append("daily_candidate_decision_window_end_invalid")
        if decision_window.get("status") != "pass":
            blockers.append("daily_candidate_decision_window_not_pass")
        if not _in_daily_candidate_decision_window(
            decision_window.get("decision_generated_at"),
            run_date=run_date,
        ):
            blockers.append("daily_candidate_decision_generated_outside_window")
        if not _in_daily_candidate_decision_window(
            decision_window.get("plan_generated_at"),
            run_date=run_date,
        ):
            blockers.append("daily_candidate_plan_generated_outside_window")
        if not _in_daily_candidate_decision_window(
            row.get("started_at"),
            run_date=run_date,
        ):
            blockers.append("daily_candidate_run_started_outside_reviewed_window")
        if snapshot.get("market_quote_max_age_seconds") != (
            DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS
        ):
            blockers.append("daily_candidate_market_quote_max_age_invalid")
        snapshot_quote_age = _elapsed_seconds(
            later=decision_window.get("decision_generated_at"),
            earlier=snapshot.get("market_quote_timestamp"),
        )
        if snapshot_quote_age is None:
            blockers.append("daily_candidate_market_quote_age_invalid")
        elif snapshot_quote_age > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
            blockers.append("daily_candidate_market_quote_too_old")
        if snapshot.get("market_quote_age_seconds_at_decision") != snapshot_quote_age:
            blockers.append("daily_candidate_market_quote_age_snapshot_mismatch")
        account_truth_source_fingerprint = str(
            snapshot.get("account_truth_source_fingerprint") or ""
        )
        if not _is_sha256(account_truth_source_fingerprint):
            blockers.append("daily_candidate_account_truth_fingerprint_invalid")
        if not str(snapshot.get("account_truth_ref") or ""):
            blockers.append("daily_candidate_account_truth_ref_missing")
        if not str(snapshot.get("valuation_snapshot_id") or ""):
            blockers.append("daily_candidate_valuation_snapshot_id_missing")
        ledger_cutoff_id = _nonnegative_int(snapshot.get("ledger_cutoff_id"))
        if ledger_cutoff_id is None or ledger_cutoff_id <= 0:
            blockers.append("daily_candidate_ledger_cutoff_invalid")
        if snapshot.get("account_truth_reconciliation_status") != "pass":
            blockers.append("daily_candidate_account_truth_reconciliation_not_pass")
        account_truth_captured_at = snapshot.get("account_truth_captured_at")
        if _shanghai_date(account_truth_captured_at) != run_date:
            blockers.append("daily_candidate_account_truth_date_mismatch")
        account_truth_age = _elapsed_seconds(
            later=decision_window.get("decision_generated_at"),
            earlier=account_truth_captured_at,
        )
        account_truth_max_age = _nonnegative_int(
            snapshot.get("account_truth_max_age_seconds")
        )
        if account_truth_age is None:
            blockers.append("daily_candidate_account_truth_age_invalid")
        if account_truth_max_age is None or account_truth_max_age <= 0:
            blockers.append("daily_candidate_account_truth_max_age_invalid")
        elif (
            account_truth_age is not None and account_truth_age > account_truth_max_age
        ):
            blockers.append("daily_candidate_account_truth_too_old")
        if snapshot.get("account_truth_age_seconds_at_decision") != account_truth_age:
            blockers.append("daily_candidate_account_truth_age_snapshot_mismatch")
        if snapshot.get("account_truth_ledger_coverage_status") != "covered":
            blockers.append("daily_candidate_account_truth_ledger_not_covered")
        account_truth_binding = _object(snapshot.get("account_truth_binding"))
        if account_truth_binding.get("schema_version") != (
            "karkinos.daily_candidate_account_truth_binding.v2"
        ):
            blockers.append("daily_candidate_account_truth_binding_contract_invalid")
        stored_account_truth_replay = _object(
            snapshot.get("account_truth_replay_evidence")
        )
        expected_account_truth_binding = {
            "schema_version": "karkinos.daily_candidate_account_truth_binding.v2",
            "account_truth_ref": snapshot.get("account_truth_ref"),
            "source_fingerprint": snapshot.get("account_truth_source_fingerprint"),
            "captured_at": snapshot.get("account_truth_captured_at"),
            "age_seconds_at_decision": snapshot.get(
                "account_truth_age_seconds_at_decision"
            ),
            "max_age_seconds": snapshot.get("account_truth_max_age_seconds"),
            "valuation_snapshot_id": snapshot.get("valuation_snapshot_id"),
            "ledger_cutoff_id": snapshot.get("ledger_cutoff_id"),
            "reconciliation_status": snapshot.get(
                "account_truth_reconciliation_status"
            ),
            "ledger_coverage_status": snapshot.get(
                "account_truth_ledger_coverage_status"
            ),
            "replay_evidence": stored_account_truth_replay,
            "persisted_facts_only": True,
            "provider_contact_performed": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }
        if account_truth_binding != expected_account_truth_binding:
            blockers.append("daily_candidate_account_truth_binding_mismatch")
        if not verify_account_truth_replay_evidence(stored_account_truth_replay):
            blockers.append("daily_candidate_account_truth_replay_invalid")
        elif stored_account_truth_replay.get("status") != "pass":
            blockers.append("daily_candidate_account_truth_replay_not_clear")
        try:
            current_account_truth_replay = self._account_truth_replay_resolver(
                self._db,
                account_truth_ref=str(snapshot.get("account_truth_ref") or ""),
                source_fingerprint=account_truth_source_fingerprint,
                valuation_snapshot_id=str(snapshot.get("valuation_snapshot_id") or ""),
                ledger_cutoff_id=ledger_cutoff_id,
            )
        except Exception:
            current_account_truth_replay = {}
        if not verify_account_truth_replay_evidence(current_account_truth_replay):
            blockers.append("current_account_truth_replay_invalid")
        elif current_account_truth_replay.get("status") != "pass":
            blockers.append("current_account_truth_replay_not_clear")
        elif current_account_truth_replay.get("evidence_fingerprint") != (
            stored_account_truth_replay.get("evidence_fingerprint")
        ):
            blockers.append("current_account_truth_replay_drifted")

        execution_closure = _object(payload.get("execution_closure"))
        execution_closure_fingerprint = str(
            execution_closure.get("evidence_fingerprint") or ""
        )
        if execution_closure.get("schema_version") != (
            "karkinos.daily_candidate_execution_closure.v1"
        ):
            blockers.append("daily_candidate_execution_closure_contract_invalid")
        if not verify_daily_candidate_execution_closure(execution_closure):
            blockers.append("daily_candidate_execution_closure_fingerprint_mismatch")
        if execution_closure.get("status") not in {"pass", "not_required"}:
            blockers.append("daily_candidate_prior_execution_not_reconciled")
        if not _is_sha256(execution_closure_fingerprint):
            blockers.append("daily_candidate_execution_closure_fingerprint_invalid")
        if str(snapshot.get("execution_closure_fingerprint") or "") != (
            execution_closure_fingerprint
        ):
            blockers.append("daily_candidate_execution_closure_snapshot_mismatch")
        if not verify_daily_candidate_execution_closure(current_execution_closure):
            blockers.append("current_execution_closure_invalid")
        elif current_execution_closure.get("status") not in {
            "pass",
            "not_required",
        }:
            blockers.append("current_execution_closure_not_clear")
        else:
            current_orders = {
                str(item.get("order_ref") or ""): item
                for item in _list(current_execution_closure.get("orders"))
                if str(item.get("order_ref") or "")
            }
            for historical_order in _list(execution_closure.get("orders")):
                order_ref = str(historical_order.get("order_ref") or "")
                current_order = current_orders.get(order_ref)
                if not order_ref or current_order is None:
                    blockers.append("current_execution_closure_order_missing")
                    continue
                if current_order.get("status") != "pass":
                    blockers.append("current_execution_closure_order_not_clear")
                historical_comparison = str(
                    historical_order.get("plan_paper_actual_fingerprint") or ""
                )
                if historical_comparison and historical_comparison != str(
                    current_order.get("plan_paper_actual_fingerprint") or ""
                ):
                    blockers.append("current_execution_closure_order_drifted")

        market_quote_bindings = {
            str(item.get("intent_ref") or ""): item
            for item in _list(snapshot.get("market_quote_bindings"))
            if str(item.get("intent_ref") or "")
        }
        strategy_gate_bindings = {
            str(item.get("action_id") or ""): item
            for item in _list(snapshot.get("strategy_gate_bindings"))
            if str(item.get("action_id") or "")
        }
        if len(strategy_gate_bindings) != ticket_candidate_count:
            blockers.append("daily_candidate_strategy_gate_binding_count_mismatch")
        paper = _object(payload.get("paper_shadow"))
        current_strategy_gates: dict[str, tuple[dict[str, Any], list[str]]] = {}
        strategy_operating_constraint_refs: set[str] = set()

        for index, ticket in enumerate(ticket_candidates):
            prefix = f"manual_order_ticket_candidate_{index}"
            if ticket.get("schema_version") != (
                DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION
            ):
                blockers.append(f"{prefix}:contract_invalid")
            stored_ticket_fingerprint = str(
                ticket.get("ticket_candidate_fingerprint") or ""
            )
            if not _is_sha256(stored_ticket_fingerprint):
                blockers.append(f"{prefix}:fingerprint_invalid")
            elif stored_ticket_fingerprint != manual_ticket_candidate_fingerprint(
                ticket
            ):
                blockers.append(f"{prefix}:fingerprint_mismatch")
            if str(ticket.get("plan_date") or "") != run_date:
                blockers.append(f"{prefix}:plan_date_mismatch")
            intent_ref = str(ticket.get("intent_id") or ticket.get("action_id") or "")
            if not intent_ref:
                blockers.append(f"{prefix}:intent_identity_missing")
            if str(ticket.get("side") or "").lower() not in {"buy", "sell"}:
                blockers.append(f"{prefix}:side_invalid")
            if _positive_float(ticket.get("quantity")) is None:
                blockers.append(f"{prefix}:quantity_invalid")
            if _positive_float(ticket.get("limit_price")) is None:
                blockers.append(f"{prefix}:limit_price_invalid")
            market_quote = _object(ticket.get("market_quote"))
            if market_quote.get("price") != ticket.get("limit_price"):
                blockers.append(f"{prefix}:market_quote_price_mismatch")
            if _shanghai_date(market_quote.get("timestamp")) != run_date:
                blockers.append(f"{prefix}:market_quote_date_mismatch")
            if not str(market_quote.get("source") or "").strip():
                blockers.append(f"{prefix}:market_quote_source_missing")
            quote_age = _elapsed_seconds(
                later=decision_window.get("decision_generated_at"),
                earlier=market_quote.get("timestamp"),
            )
            if quote_age is None:
                blockers.append(f"{prefix}:market_quote_age_invalid")
            elif quote_age > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
                blockers.append(f"{prefix}:market_quote_too_old")
            if market_quote.get("age_seconds_at_decision") != quote_age:
                blockers.append(f"{prefix}:market_quote_age_mismatch")
            if market_quote.get("max_age_seconds") != (
                DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS
            ):
                blockers.append(f"{prefix}:market_quote_max_age_invalid")
            quote_binding = market_quote_bindings.get(intent_ref)
            if quote_binding is None:
                blockers.append(f"{prefix}:market_quote_snapshot_missing")
            else:
                if quote_binding.get("price") != market_quote.get("price"):
                    blockers.append(f"{prefix}:market_quote_snapshot_price_mismatch")
                if str(quote_binding.get("source") or "") != str(
                    market_quote.get("source") or ""
                ):
                    blockers.append(f"{prefix}:market_quote_snapshot_source_mismatch")
                if _aware_iso(quote_binding.get("timestamp")) != _aware_iso(
                    market_quote.get("timestamp")
                ):
                    blockers.append(f"{prefix}:market_quote_snapshot_time_mismatch")
            ticket_paper = _object(ticket.get("paper_shadow"))
            if str(ticket_paper.get("run_id") or "") != str(
                snapshot.get("paper_shadow_run_id") or ""
            ):
                blockers.append(f"{prefix}:paper_shadow_run_mismatch")
            if str(ticket_paper.get("input_fingerprint") or "") != str(
                paper.get("input_fingerprint") or ""
            ):
                blockers.append(f"{prefix}:paper_shadow_fingerprint_mismatch")
            if ticket_paper.get("status") != "within_expectations":
                blockers.append(f"{prefix}:paper_shadow_status_not_clear")
            if ticket_paper.get("divergence_status") != "within_expectations":
                blockers.append(f"{prefix}:paper_shadow_divergence_not_clear")
            if str(ticket.get("prior_execution_closure_fingerprint") or "") != (
                execution_closure_fingerprint
            ):
                blockers.append(f"{prefix}:execution_closure_mismatch")
            evidence_refs = {
                str(item) for item in ticket.get("evidence_refs") or [] if str(item)
            }
            strategy_binding = strategy_gate_bindings.get(
                str(ticket.get("action_id") or "")
            )
            if strategy_binding is None:
                blockers.append(f"{prefix}:strategy_gate_binding_missing")
            else:
                if _object(ticket.get("strategy_gate_binding")) != strategy_binding:
                    blockers.append(f"{prefix}:strategy_gate_ticket_binding_mismatch")
                if strategy_binding.get("schema_version") != (
                    DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION
                ):
                    blockers.append(f"{prefix}:strategy_gate_binding_contract_invalid")
                ticket_constraints = _object(
                    ticket.get("strategy_operating_constraints")
                )
                binding_constraints = _object(
                    strategy_binding.get("strategy_operating_constraints")
                )
                if ticket_constraints != binding_constraints:
                    blockers.append(
                        f"{prefix}:strategy_operating_constraints_binding_mismatch"
                    )
                daily_artifact_binding = _object(
                    strategy_binding.get("daily_strategy_artifact_binding")
                )
                constraint_blockers = (
                    daily_candidate_strategy_operating_constraints_blockers(
                        binding_constraints,
                        expected_candidate_id=str(
                            daily_artifact_binding.get("winner_candidate_id") or ""
                        ),
                        expected_backup_fingerprint=str(
                            daily_artifact_binding.get("backup_artifact_fingerprint")
                            or ""
                        ),
                    )
                )
                blockers.extend(
                    f"{prefix}:{blocker}" for blocker in constraint_blockers
                )
                constraint_fingerprint = str(
                    binding_constraints.get("evidence_fingerprint") or ""
                )
                if not constraint_blockers and _is_sha256(constraint_fingerprint):
                    strategy_operating_constraint_refs.add(
                        f"strategy_operating_constraints:{constraint_fingerprint}"
                    )
                for ref_field in (
                    "strategy_ref",
                    "strategy_advancement_ref",
                    "reviewed_fee_schedule_ref",
                ):
                    if str(strategy_binding.get(ref_field) or "") not in evidence_refs:
                        blockers.append(f"{prefix}:{ref_field}_binding_mismatch")
                for fingerprint_field in (
                    "comparison_fingerprint",
                    "dataset_replay_fingerprint",
                ):
                    if not _is_sha256(strategy_binding.get(fingerprint_field)):
                        blockers.append(f"{prefix}:{fingerprint_field}_invalid")
                if not str(strategy_binding.get("human_approval_id") or ""):
                    blockers.append(f"{prefix}:strategy_human_approval_missing")
                if not str(strategy_binding.get("baseline_snapshot_id") or ""):
                    blockers.append(f"{prefix}:baseline_snapshot_id_missing")
                if not str(strategy_binding.get("candidate_snapshot_id") or ""):
                    blockers.append(f"{prefix}:candidate_snapshot_id_missing")
                if strategy_binding.get("persisted_facts_only") is not True:
                    blockers.append(f"{prefix}:strategy_persisted_facts_invalid")
                if strategy_binding.get("provider_contact_performed") is not False:
                    blockers.append(f"{prefix}:strategy_provider_boundary_invalid")
                if strategy_binding.get("paper_shadow_evaluation_only") is not True:
                    blockers.append(f"{prefix}:strategy_paper_shadow_boundary_invalid")
                if strategy_binding.get("authorizes_execution") is not False:
                    blockers.append(f"{prefix}:strategy_execution_boundary_invalid")
                if strategy_binding.get("changes_capital_authority") is not False:
                    blockers.append(f"{prefix}:strategy_capital_boundary_invalid")
                strategy_ref = str(strategy_binding.get("strategy_ref") or "")
                strategy_id = strategy_ref.removeprefix("strategy:")
                if not strategy_ref.startswith("strategy:") or not strategy_id:
                    blockers.append(f"{prefix}:current_strategy_identity_invalid")
                else:
                    if strategy_id not in current_strategy_gates:
                        try:
                            current_strategy_gates[strategy_id] = (
                                self._strategy_gate_resolver(
                                    self._db,
                                    strategy_id,
                                    as_of_date=run_date,
                                )
                            )
                        except Exception:
                            current_strategy_gates[strategy_id] = (
                                {},
                                ["strategy_gate_resolution_failed"],
                            )
                    current_gate, current_gate_blockers = current_strategy_gates[
                        strategy_id
                    ]
                    if current_gate_blockers:
                        blockers.extend(
                            f"{prefix}:current_{blocker}"
                            for blocker in current_gate_blockers
                        )
                    else:
                        current_binding, current_binding_blockers = (
                            build_daily_candidate_strategy_gate_binding(
                                candidate={
                                    "evidence": {
                                        "strategy": {
                                            "strategy_id": strategy_id,
                                            "order_generation_gate": current_gate,
                                        }
                                    }
                                },
                                plan_date=run_date,
                                expected_strategy_ref=strategy_ref,
                                expected_advancement_ref=str(
                                    strategy_binding.get("strategy_advancement_ref")
                                    or ""
                                ),
                                expected_fee_review_ref=str(
                                    strategy_binding.get("reviewed_fee_schedule_ref")
                                    or ""
                                ),
                                action_id=strategy_binding.get("action_id"),
                            )
                        )
                        blockers.extend(
                            f"{prefix}:current_{blocker}"
                            for blocker in current_binding_blockers
                        )
                        if (
                            not current_binding_blockers
                            and current_binding != strategy_binding
                        ):
                            blockers.append(
                                f"{prefix}:current_strategy_gate_binding_mismatch"
                            )
            if _object(ticket.get("account_truth_binding")) != account_truth_binding:
                blockers.append(f"{prefix}:account_truth_binding_mismatch")
            if not any(
                ref.startswith("strategy_advancement:") for ref in evidence_refs
            ):
                blockers.append(f"{prefix}:strategy_advancement_ref_missing")
            if not any(
                ref.startswith("reviewed_fee_schedule:") for ref in evidence_refs
            ):
                blockers.append(f"{prefix}:reviewed_fee_schedule_ref_missing")
            if not any(ref.startswith("risk:") for ref in evidence_refs):
                blockers.append(f"{prefix}:risk_ref_missing")
            if str(snapshot.get("account_truth_ref") or "") not in evidence_refs:
                blockers.append(f"{prefix}:account_truth_ref_mismatch")
            if ticket.get("manual_confirmation_required") is not True:
                blockers.append(f"{prefix}:manual_confirmation_boundary_invalid")
            if ticket.get("creates_oms_order") is not False:
                blockers.append(f"{prefix}:oms_creation_boundary_invalid")
            if ticket.get("authorizes_execution") is not False:
                blockers.append(f"{prefix}:execution_authority_boundary_invalid")
            if ticket.get("broker_submission_enabled") is not False:
                blockers.append(f"{prefix}:broker_submission_boundary_invalid")
            if ticket.get("does_not_change_capital_authority") is not True:
                blockers.append(f"{prefix}:capital_authority_boundary_invalid")
            invalidation_conditions = ticket.get("invalidation_conditions")
            if (
                not isinstance(invalidation_conditions, list)
                or not invalidation_conditions
                or any(not str(item).strip() for item in invalidation_conditions)
            ):
                blockers.append(f"{prefix}:invalidation_conditions_invalid")

        calendar = self._calendar_day(run_date)
        blockers.extend(calendar["blockers"])

        paper_run_id = str(paper.get("run_id") or "")
        if str(row.get("source_ref") or "") != paper_run_id:
            blockers.append("daily_candidate_source_ref_mismatch")
        if str(snapshot.get("paper_shadow_run_id") or "") != paper_run_id:
            blockers.append("daily_candidate_paper_snapshot_mismatch")
        if str(snapshot.get("paper_shadow_input_fingerprint") or "") != str(
            paper.get("input_fingerprint") or ""
        ):
            blockers.append("daily_candidate_paper_fingerprint_snapshot_mismatch")
        paper_row = self._paper_run(paper_run_id)
        if paper_row is None:
            blockers.append("paper_shadow_run_missing")
        else:
            if str(paper_row.get("plan_date") or "") != run_date:
                blockers.append("paper_shadow_plan_date_mismatch")
            if str(paper_row.get("input_fingerprint") or "") != str(
                paper.get("input_fingerprint") or ""
            ):
                blockers.append("paper_shadow_input_fingerprint_mismatch")
            if str(paper_row.get("status") or "") != "within_expectations":
                blockers.append("paper_shadow_status_not_clear")
            if str(paper_row.get("divergence_status") or "") != "within_expectations":
                blockers.append("paper_shadow_divergence_not_clear")
            source_order_count = _nonnegative_int(
                paper_row.get("simulated_order_count")
            )
            source_fill_count = _nonnegative_int(paper_row.get("simulated_fill_count"))
            payload_order_count = _nonnegative_int(paper.get("simulated_order_count"))
            payload_fill_count = _nonnegative_int(paper.get("simulated_fill_count"))
            if source_order_count is None or source_fill_count is None:
                blockers.append("paper_shadow_source_count_invalid")
            if payload_order_count is None or payload_fill_count is None:
                blockers.append("paper_shadow_payload_count_invalid")
            if source_order_count != ticket_candidate_count:
                blockers.append("paper_shadow_candidate_count_mismatch")
            if source_order_count != payload_order_count:
                blockers.append("paper_shadow_order_count_source_mismatch")
            if source_fill_count != payload_fill_count:
                blockers.append("paper_shadow_fill_count_source_mismatch")
            if source_fill_count != source_order_count:
                blockers.append("paper_shadow_fill_coverage_incomplete")

        advancement_refs = sorted(
            {
                str(item)
                for item in snapshot.get("strategy_advancement_refs") or []
                if str(item).startswith("strategy_advancement:")
            }
        )
        if not advancement_refs:
            blockers.append("strategy_advancement_binding_missing")
        fee_schedule_refs = sorted(
            {
                str(item)
                for item in snapshot.get("reviewed_fee_schedule_refs") or []
                if str(item).startswith("reviewed_fee_schedule:")
            }
        )
        if not fee_schedule_refs:
            blockers.append("reviewed_fee_schedule_binding_missing")

        blockers = list(dict.fromkeys(blockers))
        return {
            "run_date": run_date,
            "status": "qualifying" if not blockers else "excluded",
            "run_id": row.get("run_id"),
            "input_fingerprint": payload.get("input_fingerprint"),
            "decision_outcome": payload.get("decision_outcome"),
            "simulated_order_count": (
                int(paper.get("simulated_order_count") or 0) if not blockers else 0
            ),
            "strategy_advancement_refs": advancement_refs,
            "reviewed_fee_schedule_refs": fee_schedule_refs,
            "strategy_operating_constraint_refs": sorted(
                strategy_operating_constraint_refs
            ),
            "market_calendar_ref": calendar.get("evidence_ref"),
            "paper_shadow_run_id": paper_run_id or None,
            "execution_closure_fingerprint": execution_closure_fingerprint or None,
            "blockers": blockers,
        }

    def _calendar_day(self, run_date: str) -> dict[str, Any]:
        blockers: list[str] = []
        try:
            year = int(run_date[:4])
        except (TypeError, ValueError):
            return {"blockers": ["market_calendar_date_invalid"], "evidence_ref": None}
        reader = getattr(self._db, "get_market_calendar_snapshot_sync", None)
        row = reader(exchange="SSE", year=year) if callable(reader) else None
        if not isinstance(row, dict):
            return {
                "blockers": ["market_calendar_snapshot_missing"],
                "evidence_ref": None,
            }
        if str(row.get("official_verification_status") or "").lower() not in (
            _VERIFIED_CALENDAR_STATUSES
        ):
            blockers.append("market_calendar_not_officially_verified")
        source_fingerprint = str(row.get("source_fingerprint") or "")
        if not source_fingerprint:
            blockers.append("market_calendar_source_fingerprint_missing")
        days = _list(row.get("days_json"))
        day = next(
            (item for item in days if str(item.get("date") or "") == run_date),
            None,
        )
        if day is None:
            blockers.append("market_calendar_day_missing")
        elif day.get("is_trading_day") is not True:
            blockers.append("run_date_not_market_trading_day")
        return {
            "blockers": blockers,
            "evidence_ref": (
                f"market_calendar:SSE:{year}:{source_fingerprint}"
                if source_fingerprint
                else None
            ),
        }

    def _paper_run(self, run_id: str) -> dict[str, Any] | None:
        reader = getattr(self._db, "get_paper_shadow_run_sync", None)
        if not run_id or not callable(reader):
            return None
        row = reader(run_id)
        return row if isinstance(row, dict) else None

    def _latest_review(self, trial_fingerprint: str) -> dict[str, Any] | None:
        rows = self._db.list_events_sync(
            event_type=DAILY_CANDIDATE_TRIAL_REVIEW_EVENT_TYPE,
            entity_type=DAILY_CANDIDATE_TRIAL_REVIEW_ENTITY_TYPE,
            source=DAILY_CANDIDATE_TRIAL_EVENT_SOURCE,
            limit=500,
        )
        for row in rows:
            response = _review_event_response(row, reused=False)
            if (
                response.get("trial_fingerprint") == trial_fingerprint
                and response.get("status") == "recorded"
            ):
                return response
        return None


def _trial_binding(
    day: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    strategy_refs = tuple(
        sorted(str(item) for item in day.get("strategy_advancement_refs") or [])
    )
    fee_schedule_refs = tuple(
        sorted(str(item) for item in day.get("reviewed_fee_schedule_refs") or [])
    )
    strategy_operating_constraint_refs = tuple(
        sorted(
            str(item) for item in day.get("strategy_operating_constraint_refs") or []
        )
    )
    if (
        not strategy_refs
        or not fee_schedule_refs
        or not strategy_operating_constraint_refs
    ):
        return None
    return strategy_refs, fee_schedule_refs, strategy_operating_constraint_refs


def _latest_complete_trial_binding(
    evaluated_days: list[dict[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    for day in reversed(evaluated_days):
        binding = _trial_binding(day)
        if binding is not None:
            return binding
    return None


def _current_trial_epoch_days(
    *,
    evaluated_days: list[dict[str, Any]],
    active_binding: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None,
) -> list[dict[str, Any]]:
    if active_binding is None:
        return []
    boundary_index = -1
    for index, day in enumerate(evaluated_days):
        binding = _trial_binding(day)
        if binding is not None and binding != active_binding:
            boundary_index = index
    return evaluated_days[boundary_index + 1 :]


def _day_result(*, run_date: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "run_date": run_date,
        "status": "excluded",
        "run_id": None,
        "input_fingerprint": None,
        "decision_outcome": None,
        "simulated_order_count": 0,
        "strategy_advancement_refs": [],
        "reviewed_fee_schedule_refs": [],
        "strategy_operating_constraint_refs": [],
        "market_calendar_ref": None,
        "paper_shadow_run_id": None,
        "execution_closure_fingerprint": None,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    return _object(row.get("payload_json"))


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _review_event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _payload(row)
    return {
        **payload,
        "recorded_at": row.get("timestamp"),
        "event_id": row.get("id"),
        "reused": reused,
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _shanghai_date(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(_SHANGHAI_TZ).date().isoformat()


def _aware_iso(value: Any) -> str | None:
    parsed = _aware_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _aware_datetime(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _in_daily_candidate_decision_window(value: Any, *, run_date: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    shanghai_value = parsed.astimezone(_SHANGHAI_TZ)
    minute_of_day = shanghai_value.hour * 60 + shanghai_value.minute
    return bool(
        shanghai_value.date().isoformat() == run_date
        and DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE
        <= minute_of_day
        < DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE
    )


def _elapsed_seconds(*, later: Any, earlier: Any) -> int | None:
    normalized_later = str(later or "").strip()
    normalized_earlier = str(earlier or "").strip()
    if not normalized_later or not normalized_earlier:
        return None
    try:
        later_at = datetime.fromisoformat(normalized_later.replace("Z", "+00:00"))
        earlier_at = datetime.fromisoformat(normalized_earlier.replace("Z", "+00:00"))
    except ValueError:
        return None
    if (
        later_at.tzinfo is None
        or later_at.utcoffset() is None
        or earlier_at.tzinfo is None
        or earlier_at.utcoffset() is None
        or earlier_at > later_at
    ):
        return None
    return int((later_at - earlier_at).total_seconds())


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    normalized = str(value or "").strip()
    if not normalized.isdigit():
        return None
    parsed = int(normalized)
    return parsed if parsed >= 0 else None


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_float(value: Any) -> float | None:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) and normalized > 0 else None
