"""Deterministic per-day evaluation for daily-candidate operating trials."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from server.services.account_truth_replay import verify_account_truth_replay_evidence
from server.services.daily_candidate_execution_closure import (
    verify_daily_candidate_execution_closure,
)
from server.services.daily_candidate_trial_ticket_evaluation import (
    DailyCandidateTicketEvaluationMixin,
)
from server.services.daily_candidate_trial_values import (
    SHANGHAI_TIMEZONE,
    aware_datetime,
    elapsed_seconds,
    event_payload,
    excluded_day_result,
    in_daily_candidate_decision_window,
    is_sha256,
    nonnegative_int,
    object_list,
    object_value,
    shanghai_date,
)
from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION,
    DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
    DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
    DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
)

VERIFIED_CALENDAR_STATUSES = {"accepted", "confirmed", "verified"}

StrategyGateResolver = Callable[..., tuple[dict[str, Any], list[str]]]
AccountTruthReplayResolver = Callable[..., dict[str, Any]]
CalendarDayResolver = Callable[[str], dict[str, Any]]
PaperRunResolver = Callable[[str], dict[str, Any] | None]


class DailyCandidateDayEvaluator(DailyCandidateTicketEvaluationMixin):
    """Replay one persisted candidate day against current safety evidence."""

    def __init__(
        self,
        *,
        db: Any,
        run_date: str,
        rows: list[dict[str, Any]],
        as_of: datetime,
        current_execution_closure: dict[str, Any] | None,
        strategy_gate_resolver: StrategyGateResolver,
        account_truth_replay_resolver: AccountTruthReplayResolver,
        calendar_day_resolver: CalendarDayResolver,
        paper_run_resolver: PaperRunResolver,
    ) -> None:
        self.db = db
        self.run_date = run_date
        self.rows = rows
        self.as_of = as_of
        self.current_execution_closure = current_execution_closure
        self.strategy_gate_resolver = strategy_gate_resolver
        self.account_truth_replay_resolver = account_truth_replay_resolver
        self.calendar_day_resolver = calendar_day_resolver
        self.paper_run_resolver = paper_run_resolver

        self.blockers: list[str] = []
        self.payload: dict[str, Any] = {}
        self.row: dict[str, Any] = {}
        self.snapshot: dict[str, Any] = {}
        self.decision_window: dict[str, Any] = {}
        self.paper: dict[str, Any] = {}
        self.ticket_candidates: list[dict[str, Any]] = []
        self.ticket_candidate_count = 0
        self.record_fingerprint = ""
        self.ledger_cutoff_id: int | None = None
        self.account_truth_binding: dict[str, Any] = {}
        self.execution_closure: dict[str, Any] = {}
        self.execution_closure_fingerprint = ""
        self.strategy_operating_constraint_refs: set[str] = set()
        self.current_strategy_gates: dict[str, tuple[dict[str, Any], list[str]]] = {}

    def evaluate(self) -> dict[str, Any]:
        self._validate_run_date()
        if not self._select_contract():
            return excluded_day_result(
                run_date=self.run_date,
                blockers=self.blockers,
            )
        self._validate_selected_run()
        self._validate_snapshot_timing()
        self._validate_account_truth()
        self._validate_execution_closure()
        self._validate_ticket_candidates()
        calendar = self.calendar_day_resolver(self.run_date)
        self.blockers.extend(calendar["blockers"])
        paper_run_id = self._validate_paper_shadow()
        return self._build_result(calendar=calendar, paper_run_id=paper_run_id)

    def _validate_run_date(self) -> None:
        try:
            parsed_run_date = date.fromisoformat(self.run_date)
        except ValueError:
            parsed_run_date = None
            self.blockers.append("daily_candidate_run_date_invalid")
        if (
            parsed_run_date is not None
            and parsed_run_date > self.as_of.astimezone(SHANGHAI_TIMEZONE).date()
        ):
            self.blockers.append("daily_candidate_run_date_in_future")

    def _select_contract(self) -> bool:
        payloads = [(event_payload(row), row) for row in self.rows]
        candidates = [
            (payload, row)
            for payload, row in payloads
            if payload.get("schema_version")
            == DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION
        ]
        if not candidates:
            self.blockers.append("daily_candidate_contract_missing")
            return False

        fingerprints = {
            str(payload.get("input_fingerprint") or "") for payload, _ in candidates
        }
        if "" in fingerprints:
            self.blockers.append("daily_candidate_input_fingerprint_missing")
        if any(not is_sha256(value) for value in fingerprints if value):
            self.blockers.append("daily_candidate_input_fingerprint_invalid")
        if any(
            str(payload.get("input_fingerprint") or "")
            != daily_candidate_input_fingerprint(payload)
            for payload, _ in candidates
        ):
            self.blockers.append("daily_candidate_input_fingerprint_mismatch")
        if any(
            payload.get("input_identity_schema_version")
            != DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION
            for payload, _ in candidates
        ):
            self.blockers.append("daily_candidate_input_identity_contract_invalid")
        if len(fingerprints) != 1:
            self.blockers.append("daily_candidate_input_conflict")

        self.payload, self.row = max(
            candidates,
            key=lambda item: str(
                item[1].get("finished_at")
                or item[1].get("updated_at")
                or item[1].get("started_at")
                or ""
            ),
        )
        return True

    def _validate_selected_run(self) -> None:
        for field in ("started_at", "finished_at"):
            timestamp = aware_datetime(self.row.get(field))
            if timestamp is None:
                self.blockers.append(f"daily_candidate_run_{field}_invalid")
            elif timestamp > self.as_of:
                self.blockers.append(f"daily_candidate_run_{field}_in_future")

        gate = object_value(self.payload.get("production_gate"))
        self.record_fingerprint = str(
            self.payload.get("production_record_fingerprint") or ""
        )
        if not self.record_fingerprint:
            self.blockers.append("production_record_fingerprint_missing")
        elif self.record_fingerprint != daily_candidate_record_fingerprint(
            self.payload
        ):
            self.blockers.append("production_record_fingerprint_mismatch")
        if gate.get("status") != "pass":
            self.blockers.extend(str(item) for item in gate.get("blockers") or [])
            self.blockers.append("daily_candidate_production_gate_not_pass")
        if self.payload.get("decision_outcome") != "manual_order_ticket_candidate":
            self.blockers.append("manual_order_ticket_candidate_missing")

        self.ticket_candidates = object_list(
            self.payload.get("manual_order_ticket_candidates")
        )
        parsed_count = nonnegative_int(
            self.payload.get("manual_ticket_candidate_count")
        )
        if parsed_count is None:
            self.blockers.append("manual_order_ticket_candidate_count_invalid")
            parsed_count = 0
        self.ticket_candidate_count = parsed_count
        if self.ticket_candidate_count <= 0:
            self.blockers.append("manual_order_ticket_candidate_missing")
        if len(self.ticket_candidates) != self.ticket_candidate_count:
            self.blockers.append("manual_order_ticket_candidate_count_mismatch")
        if self.payload.get("broker_submission_enabled") is not False:
            self.blockers.append("broker_submission_boundary_invalid")
        if self.payload.get("does_not_submit_broker_order") is not True:
            self.blockers.append("broker_no_submit_evidence_missing")
        if str(self.row.get("status") or "") != "paper_shadow_completed":
            self.blockers.append("daily_candidate_run_status_not_complete")

        self.snapshot = object_value(self.payload.get("input_snapshot"))
        self.decision_window = object_value(self.snapshot.get("decision_window"))
        self.paper = object_value(self.payload.get("paper_shadow"))

    def _validate_snapshot_timing(self) -> None:
        snapshot = self.snapshot
        window = self.decision_window
        if not is_sha256(snapshot.get("decision_plan_fingerprint")):
            self.blockers.append("daily_candidate_decision_plan_fingerprint_invalid")
        if str(snapshot.get("decision_date") or "") != self.run_date:
            self.blockers.append("daily_candidate_decision_date_mismatch")
        if str(snapshot.get("plan_date") or "") != self.run_date:
            self.blockers.append("daily_candidate_plan_date_mismatch")
        if window.get("schema_version") != (
            DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION
        ):
            self.blockers.append("daily_candidate_decision_window_contract_invalid")
        if window.get("timezone") != "Asia/Shanghai":
            self.blockers.append("daily_candidate_decision_window_timezone_invalid")
        if window.get("start") != "09:35":
            self.blockers.append("daily_candidate_decision_window_start_invalid")
        if window.get("end_exclusive") != "09:45":
            self.blockers.append("daily_candidate_decision_window_end_invalid")
        if window.get("status") != "pass":
            self.blockers.append("daily_candidate_decision_window_not_pass")
        for field, blocker in (
            (
                "decision_generated_at",
                "daily_candidate_decision_generated_outside_window",
            ),
            ("plan_generated_at", "daily_candidate_plan_generated_outside_window"),
        ):
            if not in_daily_candidate_decision_window(
                window.get(field),
                run_date=self.run_date,
            ):
                self.blockers.append(blocker)
        if not in_daily_candidate_decision_window(
            self.row.get("started_at"),
            run_date=self.run_date,
        ):
            self.blockers.append("daily_candidate_run_started_outside_reviewed_window")
        if snapshot.get("market_quote_max_age_seconds") != (
            DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS
        ):
            self.blockers.append("daily_candidate_market_quote_max_age_invalid")
        snapshot_quote_age = elapsed_seconds(
            later=window.get("decision_generated_at"),
            earlier=snapshot.get("market_quote_timestamp"),
        )
        if snapshot_quote_age is None:
            self.blockers.append("daily_candidate_market_quote_age_invalid")
        elif snapshot_quote_age > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
            self.blockers.append("daily_candidate_market_quote_too_old")
        if snapshot.get("market_quote_age_seconds_at_decision") != snapshot_quote_age:
            self.blockers.append("daily_candidate_market_quote_age_snapshot_mismatch")

        if not is_sha256(snapshot.get("account_truth_source_fingerprint")):
            self.blockers.append("daily_candidate_account_truth_fingerprint_invalid")
        if not str(snapshot.get("account_truth_ref") or ""):
            self.blockers.append("daily_candidate_account_truth_ref_missing")
        if not str(snapshot.get("valuation_snapshot_id") or ""):
            self.blockers.append("daily_candidate_valuation_snapshot_id_missing")
        self.ledger_cutoff_id = nonnegative_int(snapshot.get("ledger_cutoff_id"))
        if self.ledger_cutoff_id is None or self.ledger_cutoff_id <= 0:
            self.blockers.append("daily_candidate_ledger_cutoff_invalid")
        if snapshot.get("account_truth_reconciliation_status") != "pass":
            self.blockers.append(
                "daily_candidate_account_truth_reconciliation_not_pass"
            )
        captured_at = snapshot.get("account_truth_captured_at")
        if shanghai_date(captured_at) != self.run_date:
            self.blockers.append("daily_candidate_account_truth_date_mismatch")
        account_truth_age = elapsed_seconds(
            later=window.get("decision_generated_at"),
            earlier=captured_at,
        )
        account_truth_max_age = nonnegative_int(
            snapshot.get("account_truth_max_age_seconds")
        )
        if account_truth_age is None:
            self.blockers.append("daily_candidate_account_truth_age_invalid")
        if account_truth_max_age is None or account_truth_max_age <= 0:
            self.blockers.append("daily_candidate_account_truth_max_age_invalid")
        elif (
            account_truth_age is not None and account_truth_age > account_truth_max_age
        ):
            self.blockers.append("daily_candidate_account_truth_too_old")
        if snapshot.get("account_truth_age_seconds_at_decision") != account_truth_age:
            self.blockers.append("daily_candidate_account_truth_age_snapshot_mismatch")
        if snapshot.get("account_truth_ledger_coverage_status") != "covered":
            self.blockers.append("daily_candidate_account_truth_ledger_not_covered")

    def _validate_account_truth(self) -> None:
        snapshot = self.snapshot
        stored_replay = object_value(snapshot.get("account_truth_replay_evidence"))
        self.account_truth_binding = object_value(snapshot.get("account_truth_binding"))
        if self.account_truth_binding.get("schema_version") != (
            "karkinos.daily_candidate_account_truth_binding.v2"
        ):
            self.blockers.append(
                "daily_candidate_account_truth_binding_contract_invalid"
            )
        expected_binding = {
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
            "replay_evidence": stored_replay,
            "persisted_facts_only": True,
            "provider_contact_performed": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }
        if self.account_truth_binding != expected_binding:
            self.blockers.append("daily_candidate_account_truth_binding_mismatch")
        if not verify_account_truth_replay_evidence(stored_replay):
            self.blockers.append("daily_candidate_account_truth_replay_invalid")
        elif stored_replay.get("status") != "pass":
            self.blockers.append("daily_candidate_account_truth_replay_not_clear")

        source_fingerprint = str(snapshot.get("account_truth_source_fingerprint") or "")
        try:
            current_replay = self.account_truth_replay_resolver(
                self.db,
                account_truth_ref=str(snapshot.get("account_truth_ref") or ""),
                source_fingerprint=source_fingerprint,
                valuation_snapshot_id=str(snapshot.get("valuation_snapshot_id") or ""),
                ledger_cutoff_id=self.ledger_cutoff_id,
            )
        except Exception:
            current_replay = {}
        if not verify_account_truth_replay_evidence(current_replay):
            self.blockers.append("current_account_truth_replay_invalid")
        elif current_replay.get("status") != "pass":
            self.blockers.append("current_account_truth_replay_not_clear")
        elif current_replay.get("evidence_fingerprint") != stored_replay.get(
            "evidence_fingerprint"
        ):
            self.blockers.append("current_account_truth_replay_drifted")

    def _validate_execution_closure(self) -> None:
        self.execution_closure = object_value(self.payload.get("execution_closure"))
        self.execution_closure_fingerprint = str(
            self.execution_closure.get("evidence_fingerprint") or ""
        )
        if self.execution_closure.get("schema_version") != (
            "karkinos.daily_candidate_execution_closure.v1"
        ):
            self.blockers.append("daily_candidate_execution_closure_contract_invalid")
        if not verify_daily_candidate_execution_closure(self.execution_closure):
            self.blockers.append(
                "daily_candidate_execution_closure_fingerprint_mismatch"
            )
        if self.execution_closure.get("status") not in {"pass", "not_required"}:
            self.blockers.append("daily_candidate_prior_execution_not_reconciled")
        if not is_sha256(self.execution_closure_fingerprint):
            self.blockers.append(
                "daily_candidate_execution_closure_fingerprint_invalid"
            )
        if str(self.snapshot.get("execution_closure_fingerprint") or "") != (
            self.execution_closure_fingerprint
        ):
            self.blockers.append("daily_candidate_execution_closure_snapshot_mismatch")
        if not verify_daily_candidate_execution_closure(self.current_execution_closure):
            self.blockers.append("current_execution_closure_invalid")
            return
        if self.current_execution_closure.get("status") not in {
            "pass",
            "not_required",
        }:
            self.blockers.append("current_execution_closure_not_clear")
            return

        current_orders = {
            str(item.get("order_ref") or ""): item
            for item in object_list(self.current_execution_closure.get("orders"))
            if str(item.get("order_ref") or "")
        }
        for historical_order in object_list(self.execution_closure.get("orders")):
            order_ref = str(historical_order.get("order_ref") or "")
            current_order = current_orders.get(order_ref)
            if not order_ref or current_order is None:
                self.blockers.append("current_execution_closure_order_missing")
                continue
            if current_order.get("status") != "pass":
                self.blockers.append("current_execution_closure_order_not_clear")
            historical_comparison = str(
                historical_order.get("plan_paper_actual_fingerprint") or ""
            )
            if historical_comparison and historical_comparison != str(
                current_order.get("plan_paper_actual_fingerprint") or ""
            ):
                self.blockers.append("current_execution_closure_order_drifted")

    def _validate_paper_shadow(self) -> str:
        paper_run_id = str(self.paper.get("run_id") or "")
        if str(self.row.get("source_ref") or "") != paper_run_id:
            self.blockers.append("daily_candidate_source_ref_mismatch")
        if str(self.snapshot.get("paper_shadow_run_id") or "") != paper_run_id:
            self.blockers.append("daily_candidate_paper_snapshot_mismatch")
        if str(self.snapshot.get("paper_shadow_input_fingerprint") or "") != str(
            self.paper.get("input_fingerprint") or ""
        ):
            self.blockers.append("daily_candidate_paper_fingerprint_snapshot_mismatch")
        paper_row = self.paper_run_resolver(paper_run_id)
        if paper_row is None:
            self.blockers.append("paper_shadow_run_missing")
            return paper_run_id
        if str(paper_row.get("plan_date") or "") != self.run_date:
            self.blockers.append("paper_shadow_plan_date_mismatch")
        if str(paper_row.get("input_fingerprint") or "") != str(
            self.paper.get("input_fingerprint") or ""
        ):
            self.blockers.append("paper_shadow_input_fingerprint_mismatch")
        if str(paper_row.get("status") or "") != "within_expectations":
            self.blockers.append("paper_shadow_status_not_clear")
        if str(paper_row.get("divergence_status") or "") != "within_expectations":
            self.blockers.append("paper_shadow_divergence_not_clear")
        source_order_count = nonnegative_int(paper_row.get("simulated_order_count"))
        source_fill_count = nonnegative_int(paper_row.get("simulated_fill_count"))
        payload_order_count = nonnegative_int(self.paper.get("simulated_order_count"))
        payload_fill_count = nonnegative_int(self.paper.get("simulated_fill_count"))
        if source_order_count is None or source_fill_count is None:
            self.blockers.append("paper_shadow_source_count_invalid")
        if payload_order_count is None or payload_fill_count is None:
            self.blockers.append("paper_shadow_payload_count_invalid")
        if source_order_count != self.ticket_candidate_count:
            self.blockers.append("paper_shadow_candidate_count_mismatch")
        if source_order_count != payload_order_count:
            self.blockers.append("paper_shadow_order_count_source_mismatch")
        if source_fill_count != payload_fill_count:
            self.blockers.append("paper_shadow_fill_count_source_mismatch")
        if source_fill_count != source_order_count:
            self.blockers.append("paper_shadow_fill_coverage_incomplete")
        return paper_run_id

    def _build_result(
        self,
        *,
        calendar: dict[str, Any],
        paper_run_id: str,
    ) -> dict[str, Any]:
        advancement_refs = sorted(
            {
                str(item)
                for item in self.snapshot.get("strategy_advancement_refs") or []
                if str(item).startswith("strategy_advancement:")
            }
        )
        if not advancement_refs:
            self.blockers.append("strategy_advancement_binding_missing")
        fee_schedule_refs = sorted(
            {
                str(item)
                for item in self.snapshot.get("reviewed_fee_schedule_refs") or []
                if str(item).startswith("reviewed_fee_schedule:")
            }
        )
        if not fee_schedule_refs:
            self.blockers.append("reviewed_fee_schedule_binding_missing")
        blockers = list(dict.fromkeys(self.blockers))
        return {
            "run_date": self.run_date,
            "status": "qualifying" if not blockers else "excluded",
            "run_id": self.row.get("run_id"),
            "input_fingerprint": self.payload.get("input_fingerprint"),
            "decision_outcome": self.payload.get("decision_outcome"),
            "simulated_order_count": (
                int(self.paper.get("simulated_order_count") or 0) if not blockers else 0
            ),
            "manual_order_ticket_candidates": (
                self.ticket_candidates if not blockers else []
            ),
            "production_record_fingerprint": (
                self.record_fingerprint if not blockers else None
            ),
            "strategy_advancement_refs": advancement_refs,
            "reviewed_fee_schedule_refs": fee_schedule_refs,
            "strategy_operating_constraint_refs": sorted(
                self.strategy_operating_constraint_refs
            ),
            "market_calendar_ref": calendar.get("evidence_ref"),
            "paper_shadow_run_id": paper_run_id or None,
            "execution_closure_fingerprint": (
                self.execution_closure_fingerprint or None
            ),
            "blockers": blockers,
        }


def evaluate_daily_candidate_day(
    *,
    db: Any,
    run_date: str,
    rows: list[dict[str, Any]],
    as_of: datetime,
    current_execution_closure: dict[str, Any] | None,
    strategy_gate_resolver: StrategyGateResolver,
    account_truth_replay_resolver: AccountTruthReplayResolver,
    calendar_day_resolver: CalendarDayResolver,
    paper_run_resolver: PaperRunResolver,
) -> dict[str, Any]:
    """Evaluate one day using explicit resolvers for current evidence."""

    return DailyCandidateDayEvaluator(
        db=db,
        run_date=run_date,
        rows=rows,
        as_of=as_of,
        current_execution_closure=current_execution_closure,
        strategy_gate_resolver=strategy_gate_resolver,
        account_truth_replay_resolver=account_truth_replay_resolver,
        calendar_day_resolver=calendar_day_resolver,
        paper_run_resolver=paper_run_resolver,
    ).evaluate()
