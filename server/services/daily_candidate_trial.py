"""Forward operating-trial evidence for production daily strategy candidates."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

from server.services.account_truth_replay import build_account_truth_replay_evidence
from server.services.daily_candidate_execution_closure import (
    build_daily_candidate_execution_closure,
    project_daily_candidate_execution_evidence_summary,
)
from server.services.daily_candidate_trial_evaluation import (
    evaluate_daily_candidate_day,
)
from server.services.daily_candidate_trial_values import aware_utc as _aware_utc
from server.services.daily_candidate_trial_values import (
    current_trial_epoch_days as _current_trial_epoch_days,
)
from server.services.daily_candidate_trial_values import fingerprint as _fingerprint
from server.services.daily_candidate_trial_values import (
    latest_complete_trial_binding as _latest_complete_trial_binding,
)
from server.services.daily_candidate_trial_values import object_list as _list
from server.services.daily_candidate_trial_values import (
    review_event_response as _review_event_response,
)
from server.services.daily_candidate_trial_values import trial_binding as _trial_binding
from server.services.daily_decision_evidence_automation import (
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    project_daily_candidate_background_schedule,
)
from server.services.market_calendar_evidence import (
    validate_verified_market_calendar,
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
        return evaluate_daily_candidate_day(
            db=self._db,
            run_date=run_date,
            rows=rows,
            as_of=as_of,
            current_execution_closure=current_execution_closure,
            strategy_gate_resolver=self._strategy_gate_resolver,
            account_truth_replay_resolver=self._account_truth_replay_resolver,
            calendar_day_resolver=self._calendar_day,
            paper_run_resolver=self._paper_run,
        )

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
        validation = validate_verified_market_calendar(row)
        blockers.extend(validation.blockers)
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
            "evidence_ref": validation.evidence_ref,
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
