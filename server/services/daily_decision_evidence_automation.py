"""Automatic risk-to-paper/shadow evidence chain for daily decisions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from account_truth.broker_statement_roll_forward import (
    roll_forward_daily_broker_statement_for_state,
)
from server.services.account_truth_replay import (
    build_account_truth_replay_evidence,
    verify_account_truth_replay_evidence,
)
from server.services.automation_control import AutomationControlService
from server.services.daily_candidate_execution_closure import (
    build_daily_candidate_execution_closure,
)
from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan

DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION = (
    "karkinos.daily_decision_evidence_automation.v3"
)
DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE = "daily_decision_evidence"
DAILY_DECISION_EVIDENCE_AUTOMATION_TASK_NAME = "daily-decision-evidence-automation"
DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE = "daily_candidate_background_attempt"
DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE = "daily_candidate_preparation_check"
DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION = (
    "karkinos.daily_candidate_background_schedule.v3"
)
DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION = (
    "karkinos.daily_candidate_preparation_check.v1"
)
DAILY_CANDIDATE_NEXT_REVIEWED_WINDOW_SCHEMA_VERSION = (
    "karkinos.daily_candidate_next_reviewed_window.v1"
)
DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION = (
    "karkinos.daily_candidate_decision_window.v1"
)
DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE = 9 * 60 + 35
DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE = 9 * 60 + 45
DAILY_CANDIDATE_PREPARATION_WINDOW_START_MINUTE = 8 * 60 + 45
DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS = 300
DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS = 10
DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION = (
    "karkinos.daily_candidate_input_identity.v2"
)
DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION = (
    "karkinos.daily_candidate_financial_preflight.v1"
)
DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION = (
    "karkinos.daily_candidate_strategy_gate_binding.v2"
)
DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION = (
    "karkinos.manual_order_ticket_candidate.v2"
)
DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA_VERSION = (
    "karkinos.ai.daily_strategy_promotion_binding.v2"
)
DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA_VERSION = (
    "karkinos.ai.strategy_operating_constraints.v1"
)

_TRUSTED_MARKET_STATUSES = {"complete", "confirmed", "fresh", "live", "pass"}
_TERMINAL_EVIDENCE_STATUSES = {
    "no_candidates",
    "no_risk_passed_order_intents",
    "paper_shadow_completed",
}
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_VERIFIED_CALENDAR_STATUSES = {"accepted", "confirmed", "verified"}
_PRODUCTION_RECORD_FIELDS = (
    "schema_version",
    "input_identity_schema_version",
    "input_fingerprint",
    "input_snapshot",
    "candidate_count",
    "risk",
    "paper_shadow",
    "execution_closure",
    "production_gate",
    "decision_outcome",
    "manual_ticket_candidate_count",
    "manual_order_ticket_candidates",
    "no_action_reasons",
    "strategy_bindings",
    "profitability_claim",
    "manual_confirmation_required",
    "broker_submission_enabled",
    "does_not_submit_broker_order",
    "does_not_mutate_production_ledger",
    "limitations",
)

logger = logging.getLogger(__name__)

PlanReader = Callable[[], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]
RiskRunner = Callable[[], Awaitable[dict[str, Any]]]
AccountTruthReplayResolver = Callable[..., dict[str, Any]]


class DailyDecisionEvidenceAutomationService:
    """Run risk and paper/shadow automatically without execution authority."""

    def __init__(
        self,
        *,
        db: Any,
        trading_controls: Any,
        notifier: Any,
        plan_reader: PlanReader,
        risk_runner: RiskRunner,
        account_truth_replay_resolver: AccountTruthReplayResolver | None = None,
    ) -> None:
        self._db = db
        self._trading_controls = trading_controls
        self._notifier = notifier
        self._plan_reader = plan_reader
        self._risk_runner = risk_runner
        self._account_truth_replay_resolver = (
            account_truth_replay_resolver or build_account_truth_replay_evidence
        )
        self._automation = AutomationControlService(
            db=db,
            trading_controls=trading_controls,
        )

    async def run_once(
        self,
        *,
        expected_plan_date: str | None = None,
    ) -> dict[str, Any]:
        """Advance one fail-closed, idempotent evidence cycle."""
        if expected_plan_date is not None:
            try:
                parsed_expected_date = datetime.strptime(
                    expected_plan_date,
                    "%Y-%m-%d",
                ).date()
            except (TypeError, ValueError) as exc:
                raise ValueError("daily candidate expected plan date invalid") from exc
            if parsed_expected_date.isoformat() != expected_plan_date:
                raise ValueError("daily candidate expected plan date invalid")

        started_at = datetime.now(timezone.utc).isoformat()
        decision_before, plan_before = await self._plan_reader()
        plan_date = _plan_date(decision_before, plan_before)
        candidate_count = _candidate_count(decision_before, plan_before)
        policy_status = self._automation.get_status()

        if expected_plan_date is not None and (
            str(decision_before.get("decision_date") or "") != expected_plan_date
            or str(plan_before.get("plan_date") or "") != expected_plan_date
        ):
            return self._record_cycle(
                status="blocked_by_plan_date_mismatch",
                plan_date=expected_plan_date,
                decision_payload=decision_before,
                trading_plan=plan_before,
                started_at=started_at,
                risk_result=None,
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "The claimed trading date does not match the persisted decision "
                    "and plan; risk and paper/shadow remained closed."
                ],
                additional_blockers=["daily_candidate_claimed_plan_date_mismatch"],
            )

        if not _policy_allows_paper_shadow(policy_status):
            return self._record_cycle(
                status=(
                    "blocked_by_kill_switch"
                    if policy_status.get("kill_switch_enabled")
                    else "blocked_by_automation_policy"
                ),
                plan_date=plan_date,
                decision_payload=decision_before,
                trading_plan=plan_before,
                started_at=started_at,
                risk_result=None,
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "Automatic evidence generation is disabled by the current "
                    "kill switch or safe automation policy."
                ],
            )

        asset_scope_blockers = _daily_candidate_asset_scope_blockers(
            decision_payload=decision_before,
            trading_plan=plan_before,
        )
        if asset_scope_blockers:
            return self._record_cycle(
                status="blocked_by_strategy_asset_scope",
                plan_date=plan_date,
                decision_payload=decision_before,
                trading_plan=plan_before,
                started_at=started_at,
                risk_result=None,
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "Daily candidate risk and paper/shadow evaluation are limited "
                    "to stock candidates."
                ],
                additional_blockers=asset_scope_blockers,
            )

        if candidate_count <= 0:
            return self._record_cycle(
                status="no_candidates",
                plan_date=plan_date,
                decision_payload=decision_before,
                trading_plan=plan_before,
                started_at=started_at,
                risk_result=None,
                paper_shadow_run=None,
                candidate_count=0,
                limitations=[],
            )

        try:
            risk_result = await self._risk_runner()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._record_cycle(
                status="risk_gate_failed",
                plan_date=plan_date,
                decision_payload=decision_before,
                trading_plan=plan_before,
                started_at=started_at,
                risk_result={
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "Automatic risk evaluation failed; no paper/shadow run or "
                    "broker action was created."
                ],
            )

        decision_after, plan_after = await self._plan_reader()
        plan_date = _plan_date(decision_after, plan_after)
        candidate_count = _candidate_count(decision_after, plan_after)
        if expected_plan_date is not None and (
            str(decision_after.get("decision_date") or "") != expected_plan_date
            or str(plan_after.get("plan_date") or "") != expected_plan_date
        ):
            return self._record_cycle(
                status="blocked_by_plan_date_mismatch",
                plan_date=expected_plan_date,
                decision_payload=decision_after,
                trading_plan=plan_after,
                started_at=started_at,
                risk_result=risk_result,
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "The claimed trading date drifted while risk evidence was being "
                    "evaluated; paper/shadow remained closed."
                ],
                additional_blockers=["daily_candidate_claimed_plan_date_mismatch"],
            )
        risk_status = str(risk_result.get("status") or "unknown")
        asset_scope_blockers = _daily_candidate_asset_scope_blockers(
            decision_payload=decision_after,
            trading_plan=plan_after,
        )
        if asset_scope_blockers:
            return self._record_cycle(
                status="blocked_by_strategy_asset_scope",
                plan_date=plan_date,
                decision_payload=decision_after,
                trading_plan=plan_after,
                started_at=started_at,
                risk_result=risk_result,
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "The post-risk Decision or plan left the stock-only daily "
                    "candidate scope; paper/shadow remained closed."
                ],
                additional_blockers=asset_scope_blockers,
            )
        if risk_status != "completed":
            return self._record_cycle(
                status=(
                    "blocked_by_data_quality"
                    if risk_status == "blocked_by_data_quality"
                    else "risk_gate_not_completed"
                ),
                plan_date=plan_date,
                decision_payload=decision_after,
                trading_plan=plan_after,
                started_at=started_at,
                risk_result=risk_result,
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "Risk evidence did not reach a completed state; automatic "
                    "paper/shadow execution remained blocked."
                ],
            )

        order_intents = _object_list(plan_after.get("order_intents"))
        if not order_intents:
            return self._record_cycle(
                status="no_risk_passed_order_intents",
                plan_date=plan_date,
                decision_payload=decision_after,
                trading_plan=plan_after,
                started_at=started_at,
                risk_result=risk_result,
                paper_shadow_run=None,
                candidate_count=candidate_count,
                limitations=[
                    "No risk-passed order intent was available for paper/shadow "
                    "simulation."
                ],
            )

        previous_run = _latest_paper_shadow_run(self._db, plan_date=plan_date)
        try:
            paper_shadow_run = await asyncio.to_thread(
                run_paper_shadow_from_trading_plan,
                db=self._db,
                trading_plan=plan_after,
                generated_at=(
                    plan_after.get("generated_at") or decision_after.get("generated_at")
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._record_cycle(
                status="paper_shadow_failed",
                plan_date=plan_date,
                decision_payload=decision_after,
                trading_plan=plan_after,
                started_at=started_at,
                risk_result=risk_result,
                paper_shadow_run={
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                candidate_count=candidate_count,
                limitations=[
                    "Paper/shadow simulation failed; no broker action or ledger "
                    "mutation was performed."
                ],
            )

        self._automation.record_paper_shadow_run(
            run_date=plan_date,
            source_ref=paper_shadow_run.get("run_id"),
            paper_shadow_run=paper_shadow_run,
        )
        try:
            decision_final, plan_final = await self._plan_reader()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._record_cycle(
                status="post_shadow_plan_failed",
                plan_date=plan_date,
                decision_payload=decision_after,
                trading_plan=plan_after,
                started_at=started_at,
                risk_result=risk_result,
                paper_shadow_run=paper_shadow_run,
                candidate_count=candidate_count,
                limitations=[
                    "Paper/shadow evidence was persisted, but the current plan "
                    "could not be rebuilt; the production outcome is NO-ACTION."
                ],
                additional_blockers=[
                    f"post_shadow_plan_read_failed:{type(exc).__name__}"
                ],
            )

        final_plan_date = _plan_date(decision_final, plan_final)
        if expected_plan_date is not None and (
            str(decision_final.get("decision_date") or "") != expected_plan_date
            or str(plan_final.get("plan_date") or "") != expected_plan_date
        ):
            return self._record_cycle(
                status="blocked_by_plan_date_mismatch",
                plan_date=expected_plan_date,
                decision_payload=decision_final,
                trading_plan=plan_final,
                started_at=started_at,
                risk_result=risk_result,
                paper_shadow_run=paper_shadow_run,
                candidate_count=_candidate_count(decision_final, plan_final),
                limitations=[
                    "The claimed trading date drifted after paper/shadow evidence was "
                    "persisted; notification and ticket candidacy remained closed."
                ],
                additional_blockers=["daily_candidate_claimed_plan_date_mismatch"],
            )
        result = self._record_cycle(
            status="paper_shadow_completed",
            plan_date=final_plan_date,
            decision_payload=decision_final,
            trading_plan=plan_final,
            started_at=started_at,
            risk_result=risk_result,
            paper_shadow_run=paper_shadow_run,
            candidate_count=_candidate_count(decision_final, plan_final),
            limitations=[],
        )
        if _is_new_paper_shadow_evidence(previous_run, paper_shadow_run):
            result["notification"] = await self._send_notification(
                plan_date=plan_date,
                risk_summary=result["risk"],
                paper_shadow_run=paper_shadow_run,
            )
        else:
            result["notification"] = {
                "status": "skipped_duplicate_evidence",
                "sent": False,
            }
        return result

    def _record_cycle(
        self,
        *,
        status: str,
        plan_date: str,
        decision_payload: dict[str, Any],
        trading_plan: dict[str, Any],
        started_at: str,
        risk_result: dict[str, Any] | None,
        paper_shadow_run: dict[str, Any] | None,
        candidate_count: int,
        limitations: list[str],
        additional_blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        finished_at = datetime.now(timezone.utc).isoformat()
        decision_plan_fingerprint = _evidence_fingerprint(
            decision_payload,
            trading_plan,
        )
        risk_summary = _risk_summary(risk_result, decision_payload)
        paper_shadow_summary = _paper_shadow_summary(paper_shadow_run)
        execution_closure = build_daily_candidate_execution_closure(self._db)
        summary = _object_dict(decision_payload.get("summary"))
        portfolio = _object_dict(summary.get("portfolio"))
        account_truth = _object_dict(summary.get("account_truth"))
        try:
            account_truth_replay = self._account_truth_replay_resolver(
                self._db,
                account_truth_ref=str(account_truth.get("import_run_id") or ""),
                source_fingerprint=str(account_truth.get("source_fingerprint") or ""),
                valuation_snapshot_id=str(portfolio.get("valuation_snapshot_id") or ""),
                ledger_cutoff_id=_nonnegative_int(portfolio.get("ledger_cutoff_id")),
            )
        except Exception:
            account_truth_replay = {}
        production = _production_outcome(
            cycle_status=status,
            plan_date=plan_date,
            decision_payload=decision_payload,
            trading_plan=trading_plan,
            paper_shadow=paper_shadow_summary,
            execution_closure=execution_closure,
            account_truth_replay=account_truth_replay,
            additional_blockers=additional_blockers or [],
        )
        production["input_snapshot"][
            "decision_plan_fingerprint"
        ] = decision_plan_fingerprint
        fingerprint = daily_candidate_input_fingerprint(
            {
                **production,
                "risk": risk_summary,
                "paper_shadow": paper_shadow_summary,
                "execution_closure": execution_closure,
            }
        )
        payload = {
            "schema_version": DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
            "input_identity_schema_version": (
                DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION
            ),
            "input_fingerprint": fingerprint,
            "input_snapshot": production["input_snapshot"],
            "candidate_count": candidate_count,
            "risk": risk_summary,
            "paper_shadow": paper_shadow_summary,
            "execution_closure": execution_closure,
            "production_gate": production["production_gate"],
            "decision_outcome": production["decision_outcome"],
            "manual_ticket_candidate_count": production[
                "manual_ticket_candidate_count"
            ],
            "manual_order_ticket_candidates": production[
                "manual_order_ticket_candidates"
            ],
            "no_action_reasons": production["no_action_reasons"],
            "strategy_bindings": production["strategy_bindings"],
            "profitability_claim": "not_established_by_daily_run",
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
            "limitations": list(limitations),
        }
        production_record_fingerprint = daily_candidate_record_fingerprint(payload)
        payload["production_record_fingerprint"] = production_record_fingerprint
        row = self._db.upsert_automation_run_sync(
            {
                "run_id": (
                    f"automation:daily-decision-evidence:{plan_date}:"
                    f"{fingerprint[:12]}"
                ),
                "run_type": DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
                "run_date": plan_date,
                "status": status,
                "execution_mode": "paper_shadow",
                "started_at": started_at,
                "finished_at": finished_at,
                "source_ref": paper_shadow_summary.get("run_id"),
                "payload": payload,
            }
        )
        return {
            "schema_version": DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
            "input_identity_schema_version": (
                DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION
            ),
            "status": status,
            "run_id": row["run_id"],
            "plan_date": plan_date,
            "input_fingerprint": fingerprint,
            "input_snapshot": production["input_snapshot"],
            "candidate_count": candidate_count,
            "risk": risk_summary,
            "paper_shadow": paper_shadow_summary,
            "execution_closure": execution_closure,
            "production_gate": production["production_gate"],
            "decision_outcome": production["decision_outcome"],
            "manual_ticket_candidate_count": production[
                "manual_ticket_candidate_count"
            ],
            "manual_order_ticket_candidates": production[
                "manual_order_ticket_candidates"
            ],
            "no_action_reasons": production["no_action_reasons"],
            "strategy_bindings": production["strategy_bindings"],
            "profitability_claim": "not_established_by_daily_run",
            "production_record_fingerprint": production_record_fingerprint,
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
            "limitations": list(limitations),
        }

    async def _send_notification(
        self,
        *,
        plan_date: str,
        risk_summary: dict[str, Any],
        paper_shadow_run: dict[str, Any],
    ) -> dict[str, Any]:
        sender = getattr(self._notifier, "send", None)
        if not callable(sender):
            return {"status": "notifier_unavailable", "sent": False}
        title = f"Karkinos 自动证据链: {plan_date}"
        message = (
            "批量风控与 paper/shadow 模拟已自动完成。\n"
            f"当前风控通过: {int(risk_summary.get('passed_count') or 0)}\n"
            f"当前风控阻断: {int(risk_summary.get('blocked_count') or 0)}\n"
            f"本轮风控跳过: {int(risk_summary.get('skipped_count') or 0)}\n"
            f"模拟订单: {int(paper_shadow_run.get('simulated_order_count') or 0)}\n"
            f"模拟状态: {paper_shadow_run.get('status') or 'unknown'}\n"
            "仍需在 Web 中人工复核；未创建或提交真实订单。"
        )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(sender, title=title, message=message),
                timeout=DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("Automatic evidence notification failed", exc_info=True)
            return {
                "status": "failed",
                "sent": False,
                "error_type": type(exc).__name__,
            }
        return {"status": "sent", "sent": True}

    async def _send_no_action_notification(
        self,
        *,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Notify a background NO-ACTION without exposing financial values."""

        sender = getattr(self._notifier, "send", None)
        if not callable(sender):
            return {"status": "notifier_unavailable", "sent": False}
        plan_date = str(result.get("plan_date") or "unknown")
        reasons = [
            str(item) for item in result.get("no_action_reasons") or [] if str(item)
        ]
        reason_lines = "\n".join(f"- {item}" for item in reasons[:8])
        if len(reasons) > 8:
            reason_lines += f"\n- 其余 {len(reasons) - 8} 项请在 Web 中复核"
        message = (
            "每日候选运行已安全结束为 NO-ACTION。\n"
            f"市场日期: {plan_date}\n"
            f"阻断项:\n{reason_lines or '- no_strategy_action'}\n"
            "请在决策窗口内查看持久化证据；未创建 OMS 订单、未提交券商订单、"
            "未改变资金额度。"
        )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    sender,
                    title=f"Karkinos 每日候选 NO-ACTION: {plan_date}",
                    message=message,
                ),
                timeout=DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "Daily candidate NO-ACTION notification failed", exc_info=True
            )
            return {
                "status": "failed",
                "sent": False,
                "error_type": type(exc).__name__,
            }
        return {"status": "sent", "sent": True}


def build_daily_decision_evidence_automation_service(
    state: Any,
) -> DailyDecisionEvidenceAutomationService:
    """Bind the canonical route adapters to the background evidence service."""
    from server.routes.decision import run_batch_pre_trade_risk_for_state
    from server.routes.operations import _current_decision_and_trading_plan

    async def read_plan() -> tuple[dict[str, Any], dict[str, Any]]:
        return await _current_decision_and_trading_plan(state)

    async def run_risk() -> dict[str, Any]:
        return await run_batch_pre_trade_risk_for_state(state)

    return DailyDecisionEvidenceAutomationService(
        db=state.db,
        trading_controls=state.trading_controls,
        notifier=state.notifier,
        plan_reader=read_plan,
        risk_runner=run_risk,
    )


async def run_daily_decision_evidence_automation_loop(
    *,
    state: Any,
    interval_seconds: float,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run at most once in the verified trading day's decision window."""
    service = build_daily_decision_evidence_automation_service(state)
    interval = max(float(interval_seconds), 1.0)
    current_time = clock or (lambda: datetime.now(timezone.utc))
    while True:
        try:
            schedule = project_daily_candidate_background_schedule(
                db=state.db,
                now=current_time(),
            )
            if schedule["preparation_check_due"]:
                roll_forward = await asyncio.to_thread(
                    roll_forward_daily_broker_statement_for_state,
                    state=state,
                    run_date=str(schedule["run_date"]),
                )
                # A changed file must first pass the independent collector's
                # stability delay and canonical staging.  Leave the once-only
                # preparation claim open until the next polling iteration.
                if roll_forward.status != "rolled_forward":
                    await _run_claimed_daily_candidate_preparation_check(
                        state=state,
                        schedule=schedule,
                    )
            if schedule["due"]:
                await _run_claimed_background_attempt(
                    db=state.db,
                    service=service,
                    schedule=schedule,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected daily decision evidence automation failure")
        await sleep(interval)


def project_daily_candidate_background_schedule(
    *,
    db: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project the persisted-calendar, once-per-day background schedule.

    The projection is read-only. Missing calendar evidence, an unverified day,
    a missed cutoff, or an existing run all keep the background writer closed.
    Manual endpoint runs remain separately available and auditable.
    """
    evaluated_at = now or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        return _background_schedule_result(
            status="blocked_clock_not_timezone_aware",
            evaluated_at=None,
            run_date=None,
            due=False,
            blockers=["background_schedule_clock_not_timezone_aware"],
        )

    shanghai_now = evaluated_at.astimezone(_SHANGHAI_TZ)
    run_date = shanghai_now.date().isoformat()
    evaluated_at_text = evaluated_at.isoformat()
    calendar_reader = getattr(db, "get_market_calendar_snapshot_sync", None)
    calendar = (
        calendar_reader(exchange="SSE", year=shanghai_now.year)
        if callable(calendar_reader)
        else None
    )
    if not isinstance(calendar, dict):
        return _background_schedule_result(
            status="blocked_market_calendar_missing",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=["market_calendar_snapshot_missing"],
        )
    if str(calendar.get("official_verification_status") or "").lower() not in (
        _VERIFIED_CALENDAR_STATUSES
    ):
        return _background_schedule_result(
            status="blocked_market_calendar_not_verified",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=["market_calendar_not_officially_verified"],
        )
    days = _json_object_list(calendar.get("days_json"))
    calendar_day = next(
        (item for item in days if str(item.get("date") or "") == run_date),
        None,
    )
    if calendar_day is None:
        return _background_schedule_result(
            status="blocked_market_calendar_day_missing",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=["market_calendar_day_missing"],
        )
    if calendar_day.get("is_trading_day") is not True:
        next_reviewed_window = _next_verified_trading_window(
            calendar_reader=calendar_reader,
            shanghai_now=shanghai_now,
            current_days=days,
            include_current_date=False,
        )
        return _background_schedule_result(
            status="not_trading_day",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=[],
            next_reviewed_window=next_reviewed_window,
        )

    run_reader = getattr(db, "list_automation_runs_sync", None)
    attempts = (
        run_reader(
            run_type=DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
            run_date=run_date,
            limit=1,
            offset=0,
        )
        if callable(run_reader)
        else []
    )
    if attempts:
        next_reviewed_window = _next_verified_trading_window(
            calendar_reader=calendar_reader,
            shanghai_now=shanghai_now,
            current_days=days,
            include_current_date=False,
        )
        return _background_schedule_result(
            status="already_attempted",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=[],
            existing_run_id=str(attempts[0].get("run_id") or "") or None,
            next_reviewed_window=next_reviewed_window,
        )
    existing = (
        run_reader(
            run_type=DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
            run_date=run_date,
            limit=1,
            offset=0,
        )
        if callable(run_reader)
        else []
    )
    if existing:
        next_reviewed_window = _next_verified_trading_window(
            calendar_reader=calendar_reader,
            shanghai_now=shanghai_now,
            current_days=days,
            include_current_date=False,
        )
        return _background_schedule_result(
            status="already_recorded",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=[],
            existing_run_id=str(existing[0].get("run_id") or "") or None,
            next_reviewed_window=next_reviewed_window,
        )

    minute_of_day = shanghai_now.hour * 60 + shanghai_now.minute
    preparation_checks = (
        run_reader(
            run_type=DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
            run_date=run_date,
            limit=1,
            offset=0,
        )
        if callable(run_reader)
        else []
    )
    preparation_check_existing_run_id = (
        str(preparation_checks[0].get("run_id") or "") or None
        if preparation_checks
        else None
    )
    preparation_check_due = bool(
        preparation_check_existing_run_id is None
        and DAILY_CANDIDATE_PREPARATION_WINDOW_START_MINUTE
        <= minute_of_day
        < DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE
    )
    if minute_of_day < DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE:
        status = "waiting_for_decision_window"
        blockers: list[str] = []
    elif minute_of_day >= DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE:
        status = "missed_decision_window"
        blockers = ["daily_candidate_background_window_missed"]
    else:
        status = "due"
        blockers = []
    next_reviewed_window = _next_verified_trading_window(
        calendar_reader=calendar_reader,
        shanghai_now=shanghai_now,
        current_days=days,
        include_current_date=status != "missed_decision_window",
    )
    return _background_schedule_result(
        status=status,
        evaluated_at=evaluated_at_text,
        run_date=run_date,
        due=status == "due",
        blockers=blockers,
        next_reviewed_window=next_reviewed_window,
        preparation_check_due=preparation_check_due,
        preparation_check_existing_run_id=preparation_check_existing_run_id,
    )


def _background_schedule_result(
    *,
    status: str,
    evaluated_at: str | None,
    run_date: str | None,
    due: bool,
    blockers: list[str],
    existing_run_id: str | None = None,
    next_reviewed_window: dict[str, Any] | None = None,
    preparation_check_due: bool = False,
    preparation_check_existing_run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION,
        "status": status,
        "evaluated_at": evaluated_at,
        "timezone": "Asia/Shanghai",
        "run_date": run_date,
        "decision_window_start": "09:35",
        "decision_window_end": "09:45",
        "preparation_window_start": "08:45",
        "preparation_window_end": "09:35",
        "due": due,
        "existing_run_id": existing_run_id,
        "preparation_check_due": preparation_check_due,
        "preparation_check_existing_run_id": preparation_check_existing_run_id,
        "blockers": list(dict.fromkeys(blockers)),
        "next_reviewed_window": (
            dict(next_reviewed_window)
            if isinstance(next_reviewed_window, dict)
            else _unavailable_next_reviewed_window(
                "next_verified_trading_window_source_unavailable"
            )
        ),
        "background_attempt_writes_enabled": due,
        "preparation_check_writes_enabled": preparation_check_due,
        "background_writes_enabled": due or preparation_check_due,
        "preparation_check_changes_attempt_eligibility": False,
        "preparation_check_permits_retry_or_backfill": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _next_verified_trading_window(
    *,
    calendar_reader: Any,
    shanghai_now: datetime,
    current_days: list[dict[str, Any]],
    include_current_date: bool,
) -> dict[str, Any]:
    run_date = shanghai_now.date().isoformat()
    candidate = _next_trading_day(
        days=current_days,
        run_date=run_date,
        include_current_date=include_current_date,
    )
    if candidate is None and callable(calendar_reader):
        next_calendar = calendar_reader(
            exchange="SSE",
            year=shanghai_now.year + 1,
        )
        if (
            isinstance(next_calendar, dict)
            and str(next_calendar.get("official_verification_status") or "").lower()
            in _VERIFIED_CALENDAR_STATUSES
        ):
            candidate = _next_trading_day(
                days=_json_object_list(next_calendar.get("days_json")),
                run_date=run_date,
                include_current_date=False,
            )
    if candidate is None:
        return _unavailable_next_reviewed_window(
            "next_verified_trading_day_not_available"
        )

    market_date = datetime.strptime(candidate, "%Y-%m-%d").date()
    window_start = datetime(
        market_date.year,
        market_date.month,
        market_date.day,
        DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE // 60,
        DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE % 60,
        tzinfo=_SHANGHAI_TZ,
    )
    window_end = datetime(
        market_date.year,
        market_date.month,
        market_date.day,
        DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE // 60,
        DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE % 60,
        tzinfo=_SHANGHAI_TZ,
    )
    return {
        "schema_version": DAILY_CANDIDATE_NEXT_REVIEWED_WINDOW_SCHEMA_VERSION,
        "status": "available",
        "market_date": candidate,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "is_current_market_date": candidate == run_date,
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


def _next_trading_day(
    *,
    days: list[dict[str, Any]],
    run_date: str,
    include_current_date: bool,
) -> str | None:
    candidates = []
    for item in days:
        candidate = str(item.get("date") or "")
        try:
            parsed = datetime.strptime(candidate, "%Y-%m-%d").date()
        except ValueError:
            continue
        if parsed.isoformat() != candidate or item.get("is_trading_day") is not True:
            continue
        if candidate > run_date or (include_current_date and candidate == run_date):
            candidates.append(candidate)
    return min(candidates) if candidates else None


def _unavailable_next_reviewed_window(blocker: str) -> dict[str, Any]:
    return {
        "schema_version": DAILY_CANDIDATE_NEXT_REVIEWED_WINDOW_SCHEMA_VERSION,
        "status": "unavailable",
        "market_date": None,
        "window_start": None,
        "window_end": None,
        "is_current_market_date": False,
        "official_calendar_verified": False,
        "blockers": [blocker],
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "permits_retry_or_backfill": False,
        "changes_attempt_eligibility": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def build_daily_candidate_preparation_check(
    state: Any,
    *,
    run_date: str,
) -> dict[str, Any]:
    """Project durable pre-window gates from persisted facts only."""

    from server.account_truth_gate import (
        ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        build_latest_account_truth_promotion_evidence,
    )
    from server.services.daily_candidate_execution_closure import (
        verify_daily_candidate_execution_closure,
    )
    from server.services.reviewed_fee_schedule import (
        build_reviewed_fee_schedule_review_status,
    )
    from server.services.strategy_promotion_pipeline import (
        StrategyPromotionPipeline,
        resolve_strategy_order_generation_gate,
    )

    automation_status = AutomationControlService(
        db=state.db,
        trading_controls=getattr(state, "trading_controls", None),
    ).get_status()
    account_truth = build_latest_account_truth_promotion_evidence(state)
    reviewed_fees = build_reviewed_fee_schedule_review_status(
        state,
        as_of_date=run_date,
    )
    execution_closure = build_daily_candidate_execution_closure(state.db)

    policy_blockers = []
    if not _policy_allows_paper_shadow(automation_status):
        policy_blockers.append(
            "daily_candidate_kill_switch_enabled"
            if automation_status.get("kill_switch_enabled") is True
            else "daily_candidate_safe_automation_policy_blocked"
        )

    account_truth_blockers = [
        str(item) for item in account_truth.get("blockers") or [] if str(item)
    ]
    if account_truth.get("schema_version") != (
        ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION
    ):
        account_truth_blockers.append("account_truth_promotion_contract_invalid")
    if account_truth.get("status") != "clear":
        account_truth_blockers.append("account_truth_promotion_not_clear")
    if account_truth.get("gate_status") != "pass":
        account_truth_blockers.append("account_truth_gate_not_pass")
    if account_truth.get("data_freshness_status") != "fresh":
        account_truth_blockers.append("account_truth_not_fresh")
    if account_truth.get("reconciliation_status") != "pass":
        account_truth_blockers.append("account_truth_reconciliation_not_pass")
    captured_at = _aware_datetime(account_truth.get("captured_at"))
    if _shanghai_date(captured_at) != run_date:
        account_truth_blockers.append("account_truth_not_captured_on_market_date")
    if not _is_sha256(account_truth.get("source_fingerprint")):
        account_truth_blockers.append("account_truth_source_fingerprint_invalid")
    if account_truth.get("does_not_mutate_production_ledger") is not True:
        account_truth_blockers.append("account_truth_read_boundary_invalid")
    if account_truth.get("does_not_issue_execution_authority") is not True:
        account_truth_blockers.append("account_truth_authority_boundary_invalid")
    if account_truth.get("broker_submission_enabled") is not False:
        account_truth_blockers.append("account_truth_broker_boundary_invalid")

    fee_blockers = [
        str(item) for item in reviewed_fees.get("blockers") or [] if str(item)
    ]
    fee_review = _object_dict(reviewed_fees.get("review"))
    fee_review_fingerprint = str(fee_review.get("review_fingerprint") or "")
    if reviewed_fees.get("status") != "active":
        fee_blockers.append("reviewed_fee_schedule_not_active")
    if not _is_sha256(fee_review_fingerprint):
        fee_blockers.append("reviewed_fee_schedule_review_fingerprint_invalid")
    expected_fee_boundaries = {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_fee_boundaries.items():
        if reviewed_fees.get(field) is not expected:
            fee_blockers.append(f"reviewed_fee_schedule_{field}_invalid")

    strategy_states = sorted(
        StrategyPromotionPipeline(db=state.db).list_states(),
        key=lambda item: str(item.get("strategy_id") or ""),
    )
    strategy_blockers: list[str] = []
    passing_strategy_count = 0
    if len(strategy_states) > 100:
        strategy_blockers.append("strategy_promotion_state_scan_truncated")
    for promotion_state in strategy_states[:100]:
        strategy_id = str(promotion_state.get("strategy_id") or "")
        if not strategy_id:
            strategy_blockers.append("strategy_promotion_identity_missing")
            continue
        try:
            gate, gate_blockers = resolve_strategy_order_generation_gate(
                state.db,
                strategy_id,
                as_of_date=run_date,
            )
        except Exception:  # noqa: BLE001 - projection failure remains fail-closed
            strategy_blockers.append("strategy_promotion_projection_failed_closed")
            continue
        boundaries_valid = bool(
            gate.get("persisted_facts_only") is True
            and gate.get("provider_contact_performed") is False
            and gate.get("does_not_create_order") is True
            and gate.get("does_not_authorize_execution") is True
            and gate.get("does_not_change_capital_authority") is True
            and gate.get("broker_submission_enabled") is False
        )
        if gate.get("status") == "pass" and not gate_blockers and boundaries_valid:
            passing_strategy_count += 1
            continue
        strategy_blockers.extend(str(item) for item in gate_blockers if str(item))
        if not boundaries_valid:
            strategy_blockers.append("strategy_order_generation_boundary_invalid")
    if not strategy_states:
        strategy_blockers.append("strategy_promotion_state_missing")
    if passing_strategy_count == 0:
        strategy_blockers.append("strategy_paper_shadow_promotion_not_ready")

    closure_blockers = [
        str(item) for item in execution_closure.get("blockers") or [] if str(item)
    ]
    if not verify_daily_candidate_execution_closure(execution_closure):
        closure_blockers.append("execution_closure_contract_invalid")
    if execution_closure.get("status") not in {"pass", "not_required"}:
        closure_blockers.append("prior_execution_not_reconciled")

    gates = [
        _preflight_gate("automation_policy", policy_blockers),
        _preflight_gate("account_truth", account_truth_blockers),
        _preflight_gate("reviewed_fees", fee_blockers),
        _preflight_gate("strategy", strategy_blockers),
        _preflight_gate("execution_closure", closure_blockers),
    ]
    blockers = list(
        dict.fromkeys(
            str(blocker)
            for gate in gates
            for blocker in gate.get("blockers") or []
            if str(blocker)
        )
    )
    actions = {
        "automation_policy": "restore_paper_shadow_only_automation_policy",
        "account_truth": "complete_current_account_truth_evidence_review",
        "reviewed_fees": "review_account_specific_fee_schedule",
        "strategy": "promote_evidence_bound_strategy_for_paper_shadow",
        "execution_closure": "complete_plan_paper_actual_reconciliation",
    }
    first_blocked_gate = next(
        (gate for gate in gates if gate.get("status") != "pass"),
        None,
    )
    first_blocking_gate = (
        str(first_blocked_gate.get("gate") or "") or None
        if first_blocked_gate
        else None
    )
    status = "blocked" if blockers else "ready_for_window_time_evidence"
    core = {
        "schema_version": DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION,
        "status": status,
        "run_date": run_date,
        "gates": gates,
        "blockers": blockers[:100],
        "blocker_count": len(blockers),
        "blockers_truncated": len(blockers) > 100,
        "first_blocking_gate": first_blocking_gate,
        "first_safe_action": (
            actions.get(first_blocking_gate)
            if first_blocking_gate
            else "persist_current_market_quotes_and_build_reviewed_window_plan"
        ),
        "strategy_state_count": len(strategy_states),
        "passing_strategy_count": passing_strategy_count,
        "reviewed_fee_schedule_fingerprint": (
            fee_review_fingerprint if _is_sha256(fee_review_fingerprint) else None
        ),
        "execution_closure_fingerprint": execution_closure.get("evidence_fingerprint"),
        "deferred_window_time_gates": [
            "market_data",
            "decision_plan",
            "runtime_window",
        ],
        "permits_risk_or_paper_shadow": False,
        "changes_attempt_eligibility": False,
        "permits_retry_or_backfill": False,
        "qualifies_forward_trial": False,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "profitability_claim": "not_established",
    }
    return {**core, "preparation_fingerprint": _fingerprint_json(core)}


def verify_daily_candidate_preparation_check(
    value: Any,
    *,
    run_date: str,
) -> bool:
    """Verify the privacy-minimized preparation contract deterministically."""

    if not isinstance(value, dict):
        return False
    core = dict(value)
    fingerprint = str(core.pop("preparation_fingerprint", "") or "")
    gates = core.get("gates")
    blockers = core.get("blockers")
    expected_boundaries = {
        "permits_risk_or_paper_shadow": False,
        "changes_attempt_eligibility": False,
        "permits_retry_or_backfill": False,
        "qualifies_forward_trial": False,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    if (
        core.get("schema_version") != DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION
        or core.get("status") not in {"blocked", "ready_for_window_time_evidence"}
        or core.get("run_date") != run_date
        or not _is_sha256(fingerprint)
        or fingerprint != _fingerprint_json(core)
        or not isinstance(gates, list)
        or not isinstance(blockers, list)
        or core.get("profitability_claim") != "not_established"
        or any(
            core.get(field) is not expected
            for field, expected in expected_boundaries.items()
        )
    ):
        return False
    gate_names = [str(_object_dict(gate).get("gate") or "") for gate in gates]
    if gate_names != [
        "automation_policy",
        "account_truth",
        "reviewed_fees",
        "strategy",
        "execution_closure",
    ]:
        return False
    blocked_gates = [
        gate
        for gate in gates
        if _object_dict(gate).get("status") != "pass"
        or _object_dict(gate).get("blockers")
    ]
    first_blocking_gate = (
        str(_object_dict(blocked_gates[0]).get("gate") or "") or None
        if blocked_gates
        else None
    )
    blocker_count = _count(core.get("blocker_count"))
    if (
        core.get("first_blocking_gate") != first_blocking_gate
        or (core.get("status") == "blocked") != bool(blocked_gates)
        or len(blockers) != min(blocker_count, 100)
        or core.get("blockers_truncated") is not (blocker_count > 100)
    ):
        return False
    return True


async def _run_claimed_daily_candidate_preparation_check(
    *,
    state: Any,
    schedule: dict[str, Any],
) -> None:
    """Claim and persist one privacy-minimized pre-window reminder."""

    run_date = str(schedule.get("run_date") or "")
    claimed_at = str(schedule.get("evaluated_at") or "")
    claim_writer = getattr(state.db, "claim_automation_run_once_sync", None)
    if not run_date or not claimed_at or not callable(claim_writer):
        raise RuntimeError("daily candidate preparation claim unavailable")
    claim_payload = {
        "schema_version": DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION,
        "status": "claimed",
        "run_date": run_date,
        "preparation": None,
        "notification": None,
        "operator_alert": None,
        "error_type": None,
        "provider_contact_performed": False,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    claim = claim_writer(
        run_id=f"automation:daily-candidate-preparation:{run_date}",
        run_type=DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
        run_date=run_date,
        claimed_at=claimed_at,
        execution_mode="read_only_preparation",
        payload=claim_payload,
    )
    if claim.get("claimed") is not True:
        return
    run = _object_dict(claim.get("run"))
    try:
        preparation = build_daily_candidate_preparation_check(
            state,
            run_date=run_date,
        )
        if not verify_daily_candidate_preparation_check(
            preparation,
            run_date=run_date,
        ):
            raise ValueError("daily candidate preparation contract invalid")
        notification = await _send_daily_candidate_preparation_notification(
            notifier=getattr(state, "notifier", None),
            preparation=preparation,
        )
        operator_alert = _record_daily_candidate_preparation_alert(
            db=state.db,
            run_date=run_date,
            preparation=preparation,
            error_type=None,
        )
        status = str(preparation.get("status") or "failed_closed")
        state.db.upsert_automation_run_sync(
            {
                **run,
                "status": status,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "source_ref": str(preparation.get("preparation_fingerprint") or "")
                or None,
                "payload": {
                    **claim_payload,
                    "status": status,
                    "preparation": preparation,
                    "notification": notification,
                    "operator_alert": operator_alert,
                },
            }
        )
    except asyncio.CancelledError:
        operator_alert = _record_daily_candidate_preparation_alert(
            db=state.db,
            run_date=run_date,
            preparation=None,
            error_type="CancelledError",
        )
        state.db.upsert_automation_run_sync(
            {
                **run,
                "status": "failed_closed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "source_ref": None,
                "payload": {
                    **claim_payload,
                    "status": "failed_closed",
                    "error_type": "CancelledError",
                    "operator_alert": operator_alert,
                },
            }
        )
        raise
    except Exception as exc:
        operator_alert = _record_daily_candidate_preparation_alert(
            db=state.db,
            run_date=run_date,
            preparation=None,
            error_type=type(exc).__name__,
        )
        state.db.upsert_automation_run_sync(
            {
                **run,
                "status": "failed_closed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "source_ref": None,
                "payload": {
                    **claim_payload,
                    "status": "failed_closed",
                    "error_type": type(exc).__name__,
                    "operator_alert": operator_alert,
                },
            }
        )
        raise


async def _send_daily_candidate_preparation_notification(
    *,
    notifier: Any,
    preparation: dict[str, Any],
) -> dict[str, Any]:
    sender = getattr(notifier, "send", None)
    if not callable(sender):
        return {"status": "notifier_unavailable", "sent": False}
    run_date = str(preparation.get("run_date") or "unknown")
    blockers = [str(item) for item in preparation.get("blockers") or [] if str(item)]
    if blockers:
        lines = "\n".join(f"- {item}" for item in blockers[:8])
        if len(blockers) > 8:
            lines += f"\n- 其余 {len(blockers) - 8} 项请在 Web 中复核"
        title = f"Karkinos 盘前准备阻断: {run_date}"
        message = (
            "盘前持久化证据检查仍有阻断项。\n"
            f"第一阻断门: {preparation.get('first_blocking_gate') or 'unknown'}\n"
            f"下一安全动作: {preparation.get('first_safe_action') or 'review'}\n"
            f"阻断项:\n{lines}\n"
            "本检查不会联系行情或券商、不会创建订单，也不会占用今日正式尝试。"
        )
    else:
        title = f"Karkinos 盘前准备完成: {run_date}"
        message = (
            "盘前持久化证据门已通过。仍需在 09:35-09:45 复核窗口内持久化"
            "当前行情并生成当日决策计划；本检查不代表可交易或可盈利。"
        )
    try:
        await asyncio.wait_for(
            asyncio.to_thread(sender, title=title, message=message),
            timeout=DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("Daily candidate preparation notification failed", exc_info=True)
        return {
            "status": "failed",
            "sent": False,
            "error_type": type(exc).__name__,
        }
    return {"status": "sent", "sent": True}


def _record_daily_candidate_preparation_alert(
    *,
    db: Any,
    run_date: str,
    preparation: dict[str, Any] | None,
    error_type: str | None,
) -> dict[str, Any]:
    writer = getattr(db, "upsert_automation_alert_sync", None)
    if not callable(writer):
        return {"status": "alert_store_unavailable", "recorded": False}
    value = _object_dict(preparation)
    blockers = [str(item) for item in value.get("blockers") or [] if str(item)]
    failed_closed = error_type is not None
    ready = value.get("status") == "ready_for_window_time_evidence"
    if ready and not failed_closed:
        return {
            "status": "not_required",
            "recorded": False,
            "reason": "preparation_gates_ready",
        }
    if failed_closed:
        severity = "critical"
        title = "Daily candidate preparation failed closed"
        detail = (
            f"The {run_date} preparation check failed closed. No retry, order, "
            "broker action, or capital change is permitted."
        )
    else:
        severity = "warning"
        title = "Daily candidate preparation requires review"
        detail = (
            f"The {run_date} preparation check found persisted blockers. Review "
            "the first named gate before the decision window."
        )
    payload = {
        "schema_version": "karkinos.daily_candidate_preparation_alert.v1",
        "run_date": run_date,
        "preparation_status": value.get("status") or "failed_closed",
        "preparation_fingerprint": value.get("preparation_fingerprint"),
        "first_blocking_gate": value.get("first_blocking_gate"),
        "first_safe_action": value.get("first_safe_action"),
        "blockers": blockers[:100],
        "blocker_count": len(blockers),
        "blockers_truncated": len(blockers) > 100,
        "error_type": error_type,
        "requires_manual_review": not ready,
        "changes_attempt_eligibility": False,
        "permits_retry_or_backfill": False,
        "qualifies_forward_trial": False,
        "provider_contact_performed": False,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    try:
        alert = writer(
            alert_key=f"daily_candidate_preparation:{run_date}",
            severity=severity,
            category="daily_candidate_preparation",
            title=title,
            detail=detail,
            source="daily_candidate_preparation_check",
            source_ref=str(value.get("preparation_fingerprint") or "") or run_date,
            payload=payload,
        )
    except Exception as exc:
        logger.warning(
            "Daily candidate preparation alert persistence failed", exc_info=True
        )
        return {
            "status": "alert_store_failed",
            "recorded": False,
            "error_type": type(exc).__name__,
        }
    return {
        "status": "recorded",
        "recorded": True,
        "alert_id": alert.get("id"),
        "alert_key": alert.get("alert_key"),
        "severity": alert.get("severity"),
    }


async def _run_claimed_background_attempt(
    *,
    db: Any,
    service: DailyDecisionEvidenceAutomationService,
    schedule: dict[str, Any],
) -> None:
    run_date = str(schedule.get("run_date") or "")
    claimed_at = str(schedule.get("evaluated_at") or "")
    claim_writer = getattr(db, "claim_daily_candidate_background_attempt_sync", None)
    if not run_date or not claimed_at or not callable(claim_writer):
        raise RuntimeError("daily candidate background attempt claim unavailable")
    claim_payload = {
        "schema_version": "karkinos.daily_candidate_background_attempt.v1",
        "schedule": schedule,
        "status": "claimed",
        "result_run_id": None,
        "result_plan_date": None,
        "result_status": None,
        "decision_outcome": None,
        "input_fingerprint": None,
        "notification": None,
        "operator_alert": None,
        "manual_confirmation_required": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    claim = claim_writer(
        run_date=run_date,
        claimed_at=claimed_at,
        payload=claim_payload,
    )
    if claim.get("claimed") is not True:
        return
    attempt_row = dict(claim.get("run") or {})
    try:
        result = await service.run_once(expected_plan_date=run_date)
    except asyncio.CancelledError:
        operator_alert = _record_daily_candidate_background_alert(
            db=db,
            run_date=run_date,
            outcome="interrupted_fail_closed",
            result=None,
            error_type="CancelledError",
        )
        _finish_background_attempt(
            db=db,
            attempt_row=attempt_row,
            payload={
                **claim_payload,
                "status": "interrupted_fail_closed",
                "operator_alert": operator_alert,
            },
            status="interrupted_fail_closed",
            source_ref=None,
        )
        raise
    except Exception as exc:
        operator_alert = _record_daily_candidate_background_alert(
            db=db,
            run_date=run_date,
            outcome="failed_closed",
            result=None,
            error_type=type(exc).__name__,
        )
        _finish_background_attempt(
            db=db,
            attempt_row=attempt_row,
            payload={
                **claim_payload,
                "status": "failed_closed",
                "error_type": type(exc).__name__,
                "operator_alert": operator_alert,
            },
            status="failed_closed",
            source_ref=None,
        )
        raise
    result_plan_date = str(result.get("plan_date") or "")
    if result_plan_date != run_date:
        error_type = "ResultPlanDateMismatch"
        operator_alert = _record_daily_candidate_background_alert(
            db=db,
            run_date=run_date,
            outcome="failed_closed",
            result=None,
            error_type=error_type,
        )
        _finish_background_attempt(
            db=db,
            attempt_row=attempt_row,
            payload={
                **claim_payload,
                "status": "failed_closed",
                "result_plan_date": result_plan_date or None,
                "result_status": result.get("status"),
                "error_type": error_type,
                "operator_alert": operator_alert,
            },
            status="failed_closed",
            source_ref=None,
        )
        return

    decision_outcome = str(result.get("decision_outcome") or "no_action")
    if decision_outcome == "no_action":
        notifier = getattr(service, "_send_no_action_notification", None)
        notification = (
            await notifier(result=result)
            if callable(notifier)
            else {"status": "notifier_unavailable", "sent": False}
        )
    else:
        notification = _object_dict(result.get("notification")) or {
            "status": "notifier_unavailable",
            "sent": False,
        }
    operator_alert = _record_daily_candidate_background_alert(
        db=db,
        run_date=run_date,
        outcome=decision_outcome,
        result=result,
        error_type=None,
    )
    _finish_background_attempt(
        db=db,
        attempt_row=attempt_row,
        payload={
            **claim_payload,
            "status": "completed",
            "result_run_id": result.get("run_id"),
            "result_plan_date": result.get("plan_date"),
            "result_status": result.get("status"),
            "decision_outcome": decision_outcome,
            "input_fingerprint": result.get("input_fingerprint"),
            "no_action_reasons": list(result.get("no_action_reasons") or [])[:100],
            "no_action_reason_count": len(result.get("no_action_reasons") or []),
            "manual_ticket_candidate_count": _count(
                result.get("manual_ticket_candidate_count")
            ),
            "notification": notification,
            "operator_alert": operator_alert,
        },
        status="completed",
        source_ref=str(result.get("run_id") or "") or None,
    )


def _record_daily_candidate_background_alert(
    *,
    db: Any,
    run_date: str,
    outcome: str,
    result: dict[str, Any] | None,
    error_type: str | None,
) -> dict[str, Any]:
    """Persist one privacy-minimized operator alert for the claimed attempt."""

    writer = getattr(db, "upsert_automation_alert_sync", None)
    if not callable(writer):
        return {"status": "alert_store_unavailable", "recorded": False}
    payload = _object_dict(result)
    no_action_reasons = [
        str(item) for item in payload.get("no_action_reasons") or [] if str(item)
    ]
    normalized_outcome = str(outcome or "failed_closed")
    manual_ticket_count = _count(payload.get("manual_ticket_candidate_count"))
    if normalized_outcome == "manual_order_ticket_candidate":
        title = "Daily candidate tickets require human review"
        detail = (
            f"The {run_date} background run produced {manual_ticket_count} read-only "
            "ticket candidate(s). No OMS or broker order was created."
        )
        severity = "warning"
        suggested_action = "review_read_only_daily_candidate_tickets"
    elif normalized_outcome == "no_action":
        title = "Daily candidate run ended NO-ACTION"
        detail = (
            f"The {run_date} background run ended NO-ACTION. Review the named "
            "persisted blockers before the next clean trading window."
        )
        severity = "warning"
        suggested_action = "review_daily_candidate_no_action_blockers"
    else:
        title = "Daily candidate background attempt failed closed"
        detail = (
            f"The {run_date} background attempt ended {normalized_outcome}. "
            "No automatic retry, OMS order, or broker action is permitted."
        )
        severity = "critical"
        suggested_action = "inspect_background_attempt_and_wait_for_next_window"
    alert_payload = {
        "schema_version": "karkinos.daily_candidate_background_alert.v1",
        "run_date": run_date,
        "outcome": normalized_outcome,
        "result_run_id": payload.get("run_id"),
        "input_fingerprint": payload.get("input_fingerprint"),
        "no_action_reasons": no_action_reasons[:100],
        "no_action_reason_count": len(no_action_reasons),
        "no_action_reasons_truncated": len(no_action_reasons) > 100,
        "manual_ticket_candidate_count": manual_ticket_count,
        "error_type": error_type,
        "suggested_action": suggested_action,
        "requires_manual_review": True,
        "manual_confirmation_required": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "changes_capital_authority": False,
    }
    try:
        alert = writer(
            alert_key=f"daily_candidate_background:{run_date}:{normalized_outcome}",
            severity=severity,
            category="daily_candidate_background",
            title=title,
            detail=detail,
            source="daily_candidate_background_attempt",
            source_ref=str(payload.get("run_id") or "") or run_date,
            payload=alert_payload,
        )
    except Exception as exc:
        logger.warning(
            "Daily candidate background alert persistence failed", exc_info=True
        )
        return {
            "status": "alert_store_failed",
            "recorded": False,
            "error_type": type(exc).__name__,
        }
    return {
        "status": "recorded",
        "recorded": True,
        "alert_id": alert.get("id"),
        "alert_key": alert.get("alert_key"),
        "severity": alert.get("severity"),
    }


def _finish_background_attempt(
    *,
    db: Any,
    attempt_row: dict[str, Any],
    payload: dict[str, Any],
    status: str,
    source_ref: str | None,
) -> None:
    db.upsert_automation_run_sync(
        {
            **attempt_row,
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_ref": source_ref,
            "payload": payload,
        }
    )


def _policy_allows_paper_shadow(status: dict[str, Any]) -> bool:
    allowed_modes = {
        str(mode).strip().lower()
        for mode in status.get("allowed_execution_modes") or []
    }
    return bool(
        status.get("automation_ready")
        and not status.get("kill_switch_enabled")
        and status.get("manual_confirmation_required")
        and not status.get("broker_submission_enabled")
        and "paper_shadow" in allowed_modes
    )


def _plan_date(
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> str:
    return str(
        trading_plan.get("plan_date")
        or decision_payload.get("decision_date")
        or datetime.now().date().isoformat()
    )


def _candidate_count(
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> int:
    summary = _object_dict(decision_payload.get("summary"))
    return _count(
        summary.get("candidate_count"),
        trading_plan.get("candidate_pool_count"),
    )


def _daily_candidate_asset_scope_blockers(
    *,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for index, candidate in enumerate(_object_list(decision_payload.get("candidates"))):
        if str(candidate.get("asset_class") or "").strip().lower() != "stock":
            blockers.append(
                f"candidate_{index}:daily_candidate_asset_class_outside_strategy_scope"
            )
    for index, intent in enumerate(_object_list(trading_plan.get("order_intents"))):
        if str(intent.get("asset_class") or "").strip().lower() != "stock":
            blockers.append(
                f"order_intent_{index}:asset_class_outside_daily_candidate_scope"
            )
    return list(dict.fromkeys(blockers))


def _daily_candidate_base_gate(
    *,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
    plan_date: str,
) -> dict[str, Any]:
    """Own the shared Decision, Account Truth, and market gate calculation."""

    gate_blockers: dict[str, list[str]] = {
        "decision_plan": [],
        "account_truth": [],
        "market_data": [],
    }
    decision_plan_blockers = gate_blockers["decision_plan"]
    account_truth_blockers = gate_blockers["account_truth"]
    market_blockers = gate_blockers["market_data"]

    decision_date = str(decision_payload.get("decision_date") or "")
    plan_contract_date = str(trading_plan.get("plan_date") or "")
    if not plan_date or not decision_date or not plan_contract_date:
        decision_plan_blockers.append("decision_or_plan_date_missing")
    elif len({plan_date, decision_date, plan_contract_date}) != 1:
        decision_plan_blockers.append("decision_plan_date_mismatch")
    if trading_plan.get("schema_version") != "karkinos.daily_trading_plan.v1":
        decision_plan_blockers.append("daily_trading_plan_contract_invalid")

    summary = _object_dict(decision_payload.get("summary"))
    portfolio = _object_dict(summary.get("portfolio"))
    valuation_snapshot_id = str(portfolio.get("valuation_snapshot_id") or "")
    ledger_cutoff_id = _positive_int(portfolio.get("ledger_cutoff_id"))
    if not valuation_snapshot_id:
        decision_plan_blockers.append("valuation_snapshot_id_missing")
    if ledger_cutoff_id is None:
        decision_plan_blockers.append("ledger_cutoff_id_invalid")

    account_truth = _object_dict(summary.get("account_truth"))
    if account_truth.get("schema_version") != (
        "karkinos.account_truth.promotion_evidence.v1"
    ):
        account_truth_blockers.append("account_truth_promotion_contract_invalid")
    if str(account_truth.get("promotion_status") or "").lower() != "clear":
        account_truth_blockers.append("account_truth_promotion_status_not_clear")
    if str(account_truth.get("gate_status") or "").lower() != "pass":
        account_truth_blockers.append("account_truth_gate_not_pass")
    if str(account_truth.get("data_freshness_status") or "").lower() != "fresh":
        account_truth_blockers.append("account_truth_not_fresh")
    if _nonnegative_int(account_truth.get("unresolved_mismatch_count")) != 0:
        account_truth_blockers.append("account_truth_unresolved_mismatch")
    account_truth_ref = str(account_truth.get("import_run_id") or "")
    if not account_truth_ref:
        account_truth_blockers.append("account_truth_import_run_missing")
    account_truth_source_fingerprint = str(
        account_truth.get("source_fingerprint") or ""
    )
    if not _is_sha256(account_truth_source_fingerprint):
        account_truth_blockers.append("account_truth_source_fingerprint_invalid")
    account_truth_captured_at = _aware_datetime(account_truth.get("captured_at"))
    if _shanghai_date(account_truth_captured_at) != plan_date:
        account_truth_blockers.append("account_truth_not_bound_to_plan_date")
    account_truth_age = _nonnegative_int(account_truth.get("current_age_seconds"))
    account_truth_max_age = _positive_int(account_truth.get("max_age_seconds"))
    if account_truth_age is None or account_truth_max_age is None:
        account_truth_blockers.append("account_truth_age_evidence_invalid")
    elif account_truth_age > account_truth_max_age:
        account_truth_blockers.append("account_truth_age_exceeds_reviewed_limit")
    ledger_coverage = _object_dict(account_truth.get("ledger_coverage"))
    if str(account_truth.get("reconciliation_status") or "").lower() != "pass":
        account_truth_blockers.append("account_truth_reconciliation_not_pass")
    if ledger_coverage.get("status") != "covered":
        account_truth_blockers.append("account_truth_ledger_coverage_not_complete")

    market = _object_dict(summary.get("market_data"))
    if str(market.get("source_health") or "").lower() not in _TRUSTED_MARKET_STATUSES:
        market_blockers.append("market_data_not_trusted")
    quote_timestamp = str(market.get("latest_quote_timestamp") or "")
    quote_at = _aware_datetime(quote_timestamp)
    quote_date = _shanghai_date(quote_at)
    if not quote_date:
        market_blockers.append("market_quote_timestamp_missing_or_invalid")
    elif quote_date != plan_date:
        market_blockers.append("market_quote_not_bound_to_plan_date")

    decision_generated_at = _aware_datetime(decision_payload.get("generated_at"))
    plan_generated_at = _aware_datetime(trading_plan.get("generated_at"))
    if _shanghai_date(decision_generated_at) != plan_date:
        decision_plan_blockers.append("decision_generation_time_not_bound_to_plan_date")
    if _shanghai_date(plan_generated_at) != plan_date:
        decision_plan_blockers.append("plan_generation_time_not_bound_to_plan_date")
    if quote_at is not None and decision_generated_at is not None:
        if quote_at > decision_generated_at:
            market_blockers.append("market_quote_after_decision_generation")
        elif (
            decision_generated_at - quote_at
        ).total_seconds() > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
            market_blockers.append("market_quote_too_old_for_decision")
    account_truth_age_at_decision: int | None = None
    if account_truth_captured_at is not None and decision_generated_at is not None:
        if account_truth_captured_at > decision_generated_at:
            account_truth_blockers.append("account_truth_after_decision_generation")
        else:
            account_truth_age_at_decision = int(
                (decision_generated_at - account_truth_captured_at).total_seconds()
            )
            if (
                account_truth_max_age is not None
                and account_truth_age_at_decision > account_truth_max_age
            ):
                account_truth_blockers.append("account_truth_too_old_for_decision")
    if (
        decision_generated_at is not None
        and plan_generated_at is not None
        and decision_generated_at > plan_generated_at
    ):
        decision_plan_blockers.append("plan_generated_before_decision")
    decision_in_window = _in_daily_candidate_decision_window(
        decision_generated_at,
        plan_date=plan_date,
    )
    plan_in_window = _in_daily_candidate_decision_window(
        plan_generated_at,
        plan_date=plan_date,
    )
    if not decision_in_window:
        decision_plan_blockers.append("decision_generated_outside_reviewed_window")
    if not plan_in_window:
        decision_plan_blockers.append("plan_generated_outside_reviewed_window")

    for blockers in gate_blockers.values():
        blockers[:] = list(dict.fromkeys(blockers))
    return {
        "gate_blockers": gate_blockers,
        "blockers": [
            blocker
            for gate_name in ("decision_plan", "account_truth", "market_data")
            for blocker in gate_blockers[gate_name]
        ],
        "decision_date": decision_date,
        "plan_contract_date": plan_contract_date,
        "valuation_snapshot_id": valuation_snapshot_id,
        "ledger_cutoff_id": ledger_cutoff_id,
        "account_truth": account_truth,
        "account_truth_ref": account_truth_ref,
        "account_truth_source_fingerprint": account_truth_source_fingerprint,
        "account_truth_captured_at": account_truth_captured_at,
        "account_truth_max_age": account_truth_max_age,
        "account_truth_age_at_decision": account_truth_age_at_decision,
        "ledger_coverage": ledger_coverage,
        "quote_timestamp": quote_timestamp,
        "quote_at": quote_at,
        "decision_generated_at": decision_generated_at,
        "plan_generated_at": plan_generated_at,
        "decision_in_window": decision_in_window,
        "plan_in_window": plan_in_window,
    }


def project_daily_candidate_financial_preflight(
    *,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
    reviewed_fee_schedule: dict[str, Any],
    execution_closure: dict[str, Any],
    automation_status: dict[str, Any],
    runtime_status: dict[str, Any],
) -> dict[str, Any]:
    """Project whether the current facts may enter risk plus paper/shadow.

    This is a zero-write read model. It does not run risk, simulate an order,
    create a ticket, or replace the canonical post-shadow production gate.
    """

    run_date = str(
        runtime_status.get("run_date")
        or trading_plan.get("plan_date")
        or decision_payload.get("decision_date")
        or ""
    )
    financial_gates: list[dict[str, Any]] = []

    policy_blockers: list[str] = []
    if not _policy_allows_paper_shadow(automation_status):
        if automation_status.get("kill_switch_enabled") is True:
            policy_blockers.append("daily_candidate_kill_switch_enabled")
        else:
            policy_blockers.append("daily_candidate_safe_automation_policy_blocked")
    financial_gates.append(_preflight_gate("automation_policy", policy_blockers))

    base_gate = _daily_candidate_base_gate(
        decision_payload=decision_payload,
        trading_plan=trading_plan,
        plan_date=run_date,
    )
    base_gate_blockers = _object_dict(base_gate.get("gate_blockers"))
    decision_plan_blockers = [
        str(item) for item in base_gate_blockers.get("decision_plan") or []
    ]
    for blocker in _object_list(trading_plan.get("blockers")):
        reason = _safe_preflight_blocker(blocker.get("reason"))
        if reason and reason != "awaiting_risk_gate":
            decision_plan_blockers.append(f"daily_trading_plan:{reason}")
    financial_gates.append(_preflight_gate("decision_plan", decision_plan_blockers))
    financial_gates.append(
        _preflight_gate(
            "account_truth",
            [str(item) for item in base_gate_blockers.get("account_truth") or []],
        )
    )
    market_blockers = [
        str(item) for item in base_gate_blockers.get("market_data") or []
    ]
    decision_generated_at = base_gate.get("decision_generated_at")

    strategy_blockers: list[str] = []
    eligible_candidate_count = 0
    strategy_binding_fingerprints: list[str] = []
    active_fee_review = _object_dict(reviewed_fee_schedule.get("review"))
    active_fee_review_fingerprint = str(
        active_fee_review.get("review_fingerprint") or ""
    )
    candidates = _object_list(decision_payload.get("candidates"))
    if not candidates:
        strategy_blockers.append("daily_candidate_strategy_candidate_missing")
    for index, candidate in enumerate(candidates):
        candidate_blockers: list[str] = []
        if str(candidate.get("asset_class") or "").strip().lower() != "stock":
            candidate_blockers.append(
                "daily_candidate_asset_class_outside_strategy_scope"
            )
        manual_status = str(candidate.get("manual_confirmation_status") or "")
        if manual_status not in {
            "awaiting_risk_gate",
            "paper_shadow_review_required",
            "ready_for_manual_confirmation",
        }:
            candidate_blockers.append("strategy_candidate_not_paper_shadow_eligible")
        strategy = _object_dict(_object_dict(candidate.get("evidence")).get("strategy"))
        strategy_id = str(strategy.get("strategy_id") or "")
        order_generation_gate = _object_dict(strategy.get("order_generation_gate"))
        promotion = _object_dict(order_generation_gate.get("promotion"))
        advancement_fingerprint = str(
            promotion.get("strategy_advancement_gate_fingerprint") or ""
        )
        fee_review_fingerprint = str(
            _object_dict(promotion.get("fee_schedule_binding")).get(
                "fee_schedule_review_fingerprint"
            )
            or ""
        )
        binding, binding_blockers = _strategy_gate_binding(
            candidate=candidate,
            plan_date=run_date,
            expected_strategy_ref=(f"strategy:{strategy_id}" if strategy_id else None),
            expected_advancement_ref=(
                f"strategy_advancement:{advancement_fingerprint}"
                if advancement_fingerprint
                else None
            ),
            expected_fee_review_ref=(
                f"reviewed_fee_schedule:{fee_review_fingerprint}"
                if fee_review_fingerprint
                else None
            ),
            action_id=candidate.get("action_id"),
        )
        candidate_blockers.extend(binding_blockers)
        if fee_review_fingerprint != active_fee_review_fingerprint:
            candidate_blockers.append("reviewed_fee_schedule_active_binding_mismatch")
        candidate_market = _object_dict(
            _object_dict(candidate.get("evidence")).get("data_freshness")
        )
        candidate_quote_at = _aware_datetime(candidate_market.get("quote_timestamp"))
        if _shanghai_date(candidate_quote_at) != run_date:
            candidate_blockers.append("candidate_market_quote_not_bound_to_plan_date")
        if _positive_float(candidate_market.get("price")) is None:
            candidate_blockers.append("candidate_market_quote_price_invalid")
        if not str(candidate_market.get("quote_source") or "").strip():
            candidate_blockers.append("candidate_market_quote_source_missing")
        if candidate_quote_at is not None and decision_generated_at is not None:
            if candidate_quote_at > decision_generated_at:
                candidate_blockers.append("candidate_market_quote_after_decision")
            elif (
                decision_generated_at - candidate_quote_at
            ).total_seconds() > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
                candidate_blockers.append("candidate_market_quote_too_old")
        candidate_blockers = list(dict.fromkeys(candidate_blockers))
        if candidate_blockers:
            strategy_blockers.extend(
                f"candidate_{index}:{item}" for item in candidate_blockers
            )
        else:
            eligible_candidate_count += 1
            strategy_binding_fingerprints.append(_fingerprint_json(binding))
    if candidates and eligible_candidate_count == 0:
        strategy_blockers.append("daily_candidate_strategy_candidate_not_eligible")
    financial_gates.append(_preflight_gate("market_data", market_blockers))
    financial_gates.append(_preflight_gate("strategy", strategy_blockers))

    fee_blockers = [
        str(item) for item in reviewed_fee_schedule.get("blockers") or [] if str(item)
    ]
    if reviewed_fee_schedule.get("status") != "active":
        fee_blockers.append("reviewed_fee_schedule_not_active")
    if not _is_sha256(active_fee_review_fingerprint):
        fee_blockers.append("reviewed_fee_schedule_review_fingerprint_invalid")
    expected_fee_boundaries = {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_fee_boundaries.items():
        if reviewed_fee_schedule.get(field) is not expected:
            fee_blockers.append(f"reviewed_fee_schedule_{field}_invalid")
    financial_gates.append(_preflight_gate("reviewed_fees", fee_blockers))

    closure_blockers: list[str] = []
    if execution_closure.get("schema_version") != (
        "karkinos.daily_candidate_execution_closure.v1"
    ):
        closure_blockers.append("execution_closure_contract_invalid")
    if execution_closure.get("status") not in {"pass", "not_required"}:
        closure_blockers.extend(
            f"execution_closure:{item}"
            for item in execution_closure.get("blockers") or []
            if str(item)
        )
        closure_blockers.append("prior_execution_not_reconciled")
    if not _is_sha256(execution_closure.get("evidence_fingerprint")):
        closure_blockers.append("execution_closure_fingerprint_invalid")
    financial_gates.append(_preflight_gate("execution_closure", closure_blockers))

    financial_blockers = list(
        dict.fromkeys(
            blocker
            for gate in financial_gates
            for blocker in gate.get("blockers") or []
        )
    )
    runtime_blockers = [
        str(item)
        for item in runtime_status.get("operational_blockers") or []
        if str(item)
    ]
    expected_runtime_boundaries = {
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_runtime_boundaries.items():
        if runtime_status.get(field) is not expected:
            runtime_blockers.append(f"daily_candidate_runtime_{field}_invalid")
    if runtime_status.get("schema_version") != (
        "karkinos.daily_candidate_runtime_status.v1"
    ):
        runtime_blockers.append("daily_candidate_runtime_contract_invalid")
    runtime_blockers = list(dict.fromkeys(runtime_blockers))
    schedule_status = str(runtime_status.get("schedule_status") or "invalid")
    financial_clear = not financial_blockers
    manual_window_open = runtime_status.get("manual_run_window_open") is True
    background_ready = bool(
        financial_clear
        and manual_window_open
        and runtime_status.get("background_attempt_due") is True
        and runtime_status.get("background_monitor_running") is True
        and not runtime_blockers
    )
    manual_ready = bool(financial_clear and manual_window_open)

    no_action_reasons = [*financial_blockers, *runtime_blockers]
    if not manual_window_open:
        schedule_reason = {
            "waiting_for_decision_window": "daily_candidate_decision_window_not_open",
            "missed_decision_window": "daily_candidate_background_window_missed",
            "not_trading_day": "market_calendar_not_trading_day",
            "already_attempted": "daily_candidate_attempt_already_recorded",
            "already_recorded": "daily_candidate_run_already_recorded",
        }.get(schedule_status, "daily_candidate_decision_window_unavailable")
        no_action_reasons.append(schedule_reason)
    no_action_reasons = list(dict.fromkeys(no_action_reasons))

    if background_ready:
        status = "ready_for_paper_shadow_attempt"
        next_safe_action = "allow_single_claimed_fail_closed_background_attempt"
    elif manual_ready:
        status = "ready_for_manual_paper_shadow_attempt"
        next_safe_action = "start_one_canonical_daily_candidate_attempt"
    elif financial_blockers:
        status = "no_action"
        next_safe_action = "resolve_named_financial_blockers_before_next_window"
    elif schedule_status == "waiting_for_decision_window":
        status = "waiting_for_decision_window"
        next_safe_action = "keep_monitor_running_and_wait_for_reviewed_window"
    elif schedule_status == "not_trading_day":
        status = "no_action_not_trading_day"
        next_safe_action = "wait_for_next_verified_trading_day"
    elif schedule_status in {"already_attempted", "already_recorded"}:
        status = "daily_attempt_closed"
        next_safe_action = "review_persisted_daily_result"
    else:
        status = "no_action"
        next_safe_action = "resolve_runtime_or_schedule_blockers_before_next_window"

    operator_checklist = _preflight_operator_checklist(
        gates=financial_gates,
        runtime_blockers=runtime_blockers,
        schedule_status=schedule_status,
        manual_window_open=manual_window_open,
        next_safe_action=next_safe_action,
    )

    core = {
        "schema_version": DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION,
        "status": status,
        "run_date": run_date or None,
        "financial_gate_status": "pass" if financial_clear else "blocked",
        "operational_gate_status": "pass" if not runtime_blockers else "blocked",
        "eligible_candidate_count": eligible_candidate_count,
        "eligible_to_start_manual_attempt": manual_ready,
        "eligible_for_background_attempt": background_ready,
        "eligible_to_create_manual_ticket": False,
        "gates": financial_gates,
        "financial_blockers": financial_blockers,
        "operational_blockers": runtime_blockers,
        "no_action_reasons": [] if manual_ready else no_action_reasons,
        "next_safe_action": next_safe_action,
        "operator_checklist": operator_checklist,
        "decision_plan_fingerprint": _evidence_fingerprint(
            decision_payload,
            trading_plan,
        ),
        "strategy_binding_fingerprints": sorted(strategy_binding_fingerprints),
        "reviewed_fee_schedule_fingerprint": (
            active_fee_review_fingerprint
            if _is_sha256(active_fee_review_fingerprint)
            else None
        ),
        "execution_closure_fingerprint": execution_closure.get("evidence_fingerprint"),
        "financial_readiness_scope": "risk_and_paper_shadow_attempt_only",
        "risk_evaluation_performed": False,
        "paper_shadow_run_performed": False,
        "manual_ticket_created": False,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "profitability_claim": "not_established",
        "limitations": [
            "Passing this preflight permits only the canonical risk and paper/shadow attempt.",
            "A manual ticket still requires the post-shadow production gate and separate human confirmation.",
            "This projection does not establish current or future profitability.",
        ],
    }
    return {**core, "preflight_fingerprint": _fingerprint_json(core)}


def unavailable_daily_candidate_financial_preflight(
    *,
    blocker: str = "daily_candidate_financial_preflight_source_unavailable",
) -> dict[str, Any]:
    """Return the canonical fail-closed shape when a read source is unavailable."""

    core = {
        "schema_version": DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION,
        "status": "no_action",
        "run_date": None,
        "financial_gate_status": "blocked",
        "operational_gate_status": "blocked",
        "eligible_candidate_count": 0,
        "eligible_to_start_manual_attempt": False,
        "eligible_for_background_attempt": False,
        "eligible_to_create_manual_ticket": False,
        "gates": [],
        "financial_blockers": [blocker],
        "operational_blockers": [],
        "no_action_reasons": [blocker],
        "next_safe_action": "restore_persisted_preflight_sources_before_next_window",
        "operator_checklist": [
            _preflight_operator_step(
                step=1,
                gate="source_evidence",
                action="restore_persisted_preflight_sources_before_next_window",
                blockers=[blocker],
                completion_mode="persisted_evidence_refresh",
            )
        ],
        "decision_plan_fingerprint": None,
        "strategy_binding_fingerprints": [],
        "reviewed_fee_schedule_fingerprint": None,
        "execution_closure_fingerprint": None,
        "financial_readiness_scope": "risk_and_paper_shadow_attempt_only",
        "risk_evaluation_performed": False,
        "paper_shadow_run_performed": False,
        "manual_ticket_created": False,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "profitability_claim": "not_established",
        "limitations": [
            "A missing or invalid read source fails closed before risk or paper/shadow.",
            "No manual ticket, broker action, ledger mutation, or capital change is authorized.",
        ],
    }
    return {**core, "preflight_fingerprint": _fingerprint_json(core)}


def _preflight_operator_checklist(
    *,
    gates: list[dict[str, Any]],
    runtime_blockers: list[str],
    schedule_status: str,
    manual_window_open: bool,
    next_safe_action: str,
) -> list[dict[str, Any]]:
    """Order blocked evidence work without performing or authorizing it."""

    action_specs = (
        (
            "automation_policy",
            "restore_paper_shadow_only_automation_policy",
            "human_review",
        ),
        (
            "account_truth",
            "complete_current_account_truth_evidence_review",
            "human_review",
        ),
        (
            "reviewed_fees",
            "review_account_specific_fee_schedule",
            "human_review",
        ),
        (
            "strategy",
            "promote_evidence_bound_strategy_for_paper_shadow",
            "human_review",
        ),
        (
            "execution_closure",
            "complete_plan_paper_actual_reconciliation",
            "human_review",
        ),
        (
            "market_data",
            "persist_current_market_quotes_for_reviewed_window",
            "persisted_evidence_refresh",
        ),
        (
            "decision_plan",
            "rebuild_decision_and_plan_in_reviewed_window",
            "canonical_runtime",
        ),
    )
    blockers_by_gate = {
        str(gate.get("gate") or ""): [
            str(blocker) for blocker in gate.get("blockers") or [] if str(blocker)
        ]
        for gate in gates
    }
    checklist: list[dict[str, Any]] = []
    for gate, action, completion_mode in action_specs:
        blockers = blockers_by_gate.get(gate, [])
        if not blockers:
            continue
        checklist.append(
            _preflight_operator_step(
                step=len(checklist) + 1,
                gate=gate,
                action=action,
                blockers=blockers,
                completion_mode=completion_mode,
            )
        )

    schedule_reason = None
    schedule_action = "restore_daily_candidate_runtime_before_reviewed_window"
    if not manual_window_open:
        schedule_reason, schedule_action = {
            "waiting_for_decision_window": (
                "daily_candidate_decision_window_not_open",
                "keep_monitor_running_and_wait_for_reviewed_window",
            ),
            "missed_decision_window": (
                "daily_candidate_background_window_missed",
                "prepare_current_evidence_for_next_reviewed_window",
            ),
            "not_trading_day": (
                "market_calendar_not_trading_day",
                "wait_for_next_verified_trading_day",
            ),
            "already_attempted": (
                "daily_candidate_attempt_already_recorded",
                "review_persisted_daily_result",
            ),
            "already_recorded": (
                "daily_candidate_run_already_recorded",
                "review_persisted_daily_result",
            ),
        }.get(
            schedule_status,
            (
                "daily_candidate_decision_window_unavailable",
                "restore_daily_candidate_runtime_before_reviewed_window",
            ),
        )
    runtime_reasons = list(dict.fromkeys([*runtime_blockers, schedule_reason]))
    runtime_reasons = [reason for reason in runtime_reasons if reason]
    if runtime_reasons:
        checklist.append(
            _preflight_operator_step(
                step=len(checklist) + 1,
                gate="runtime_window",
                action=schedule_action,
                blockers=runtime_reasons,
                completion_mode="canonical_runtime",
            )
        )

    if not checklist:
        checklist.append(
            _preflight_operator_step(
                step=1,
                gate="ready",
                action=next_safe_action,
                blockers=[],
                completion_mode="canonical_runtime",
            )
        )
    return checklist


def _preflight_operator_step(
    *,
    step: int,
    gate: str,
    action: str,
    blockers: list[str],
    completion_mode: str,
) -> dict[str, Any]:
    evidence_contract = _preflight_operator_evidence_contract(gate)
    return {
        "step": step,
        "gate": gate,
        "action": action,
        "completion_mode": completion_mode,
        "blockers": list(dict.fromkeys(blockers)),
        **evidence_contract,
        "automatic_action_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _preflight_operator_evidence_contract(gate: str) -> dict[str, Any]:
    """Describe exact, privacy-minimized evidence without accepting it."""

    contracts = {
        "automation_policy": {
            "required_evidence": [
                "persisted_paper_shadow_only_automation_policy",
                "manual_confirmation_and_kill_switch_controls",
            ],
            "completion_criteria": [
                "broker_submission_remains_disabled",
                "manual_confirmation_remains_required",
                "allowed_modes_exclude_live_like_execution",
            ],
        },
        "account_truth": {
            "required_evidence": [
                "current_cash_snapshot_with_aware_timestamp_and_cash_balance",
                "current_position_snapshots_with_symbol_asset_currency_quantity_and_cost_basis",
                "itemized_trade_rows_with_quantity_price_gross_fee_tax_transfer_fee_and_net_amount",
                "reviewed_source_hash_window_scope_and_completeness_attestations",
                "current_ledger_cutoff_and_reconciliation_evidence",
            ],
            "completion_criteria": [
                "cash_and_position_snapshots_share_current_shanghai_date",
                "snapshots_are_no_more_than_86400_seconds_old_and_not_before_latest_event",
                "account_truth_covers_latest_ledger_cutoff",
                "cash_position_fee_and_cost_basis_pass_with_zero_unresolved_mismatches",
                "private_xls_content_and_account_identifiers_remain_unstored",
            ],
        },
        "reviewed_fees": {
            "required_evidence": [
                "account_specific_commission_minimum_stamp_tax_transfer_fee_and_other_fee_terms",
                "historical_buy_and_sell_itemized_fee_components",
                "human_accepted_fee_effective_date_window",
            ],
            "completion_criteria": [
                "historical_buy_and_sell_fee_component_reconciliation_passes",
                "action_date_is_inside_accepted_fee_window",
                "fee_review_matches_current_account_truth_and_strategy_bindings",
                "fee_review_is_bounded_and_revocable",
            ],
        },
        "strategy": {
            "required_evidence": [
                "five_sequential_research_iterations",
                "deterministic_local_backtest_and_promotion_evidence",
                "content_addressed_daily_strategy_backup",
                "bounded_revocable_human_promotion_review",
            ],
            "completion_criteria": [
                "each_iteration_binds_previous_formula_metrics_blockers_and_critique",
                "research_policy_authorizes_exactly_five_iterations_and_ten_provider_calls",
                "winner_passes_every_deterministic_gate_or_incumbent_remains_unchanged",
                "promoted_strategy_replays_from_frozen_data_and_current_fee_review",
                "live_like_execution_remains_disabled",
            ],
        },
        "execution_closure": {
            "required_evidence": [
                "persisted_plan_paper_and_actual_execution_records",
                "per_order_terminal_and_ledger_reconciliation",
            ],
            "completion_criteria": [
                "every_prior_required_order_is_reconciled_or_explicitly_not_required",
                "unresolved_or_drifted_execution_evidence_count_is_zero",
            ],
        },
        "market_data": {
            "required_evidence": [
                "persisted_trusted_quote_with_source_price_and_aware_timestamp",
            ],
            "completion_criteria": [
                "quote_is_bound_to_plan_date_and_not_after_decision_time",
                "quote_age_at_decision_is_no_more_than_300_seconds",
            ],
        },
        "decision_plan": {
            "required_evidence": [
                "persisted_same_day_decision_and_trading_plan",
                "matching_account_market_strategy_fee_and_closure_bindings",
            ],
            "completion_criteria": [
                "decision_and_plan_are_rebuilt_inside_reviewed_window",
                "decision_plan_bindings_replay_without_drift",
            ],
        },
        "runtime_window": {
            "required_evidence": [
                "loaded_local_daily_candidate_service_and_live_monitor_task",
                "reviewed_exchange_calendar_and_current_decision_window",
            ],
            "completion_criteria": [
                "launch_agent_and_process_liveness_are_both_confirmed",
                "exactly_one_fail_closed_attempt_is_due_in_reviewed_window",
                "runtime_liveness_does_not_claim_financial_readiness",
            ],
        },
        "source_evidence": {
            "required_evidence": [
                "readable_persisted_decision_plan_fee_closure_and_runtime_sources",
            ],
            "completion_criteria": [
                "all_preflight_sources_are_readable_and_contract_valid",
                "source_restoration_does_not_mutate_financial_state",
            ],
        },
        "ready": {
            "required_evidence": ["persisted_current_preflight_facts"],
            "completion_criteria": [
                "start_only_one_canonical_risk_and_paper_shadow_attempt",
                "separate_post_shadow_gate_and_human_confirmation_remain_required",
            ],
        },
    }
    contract = contracts.get(
        gate,
        {
            "required_evidence": ["canonical_persisted_gate_evidence"],
            "completion_criteria": ["named_gate_blockers_are_resolved"],
        },
    )
    return {
        "evidence_contract_version": "karkinos.daily_candidate_operator_evidence.v1",
        "required_evidence": list(contract["required_evidence"]),
        "completion_criteria": list(contract["completion_criteria"]),
        "accepted_evidence_authority": "canonical_persisted_evidence_only",
        "owner_attestation_is_financial_fact": False,
        "private_xls_rows_required": False,
        "private_account_identifiers_required": False,
    }


def _preflight_gate(name: str, blockers: list[str]) -> dict[str, Any]:
    normalized = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    return {
        "gate": name,
        "status": "blocked" if normalized else "pass",
        "blockers": normalized,
    }


def _safe_preflight_blocker(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if not normalized:
        return ""
    if len(normalized) > 120 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_:-."
        for character in normalized
    ):
        return "unclassified_blocker"
    return normalized


def _evidence_fingerprint(
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> str:
    summary = _object_dict(decision_payload.get("summary"))
    portfolio = _object_dict(summary.get("portfolio"))
    account_truth = _object_dict(summary.get("account_truth"))
    market = _object_dict(summary.get("market_data"))
    payload = {
        "decision_date": decision_payload.get("decision_date"),
        "decision": decision_payload.get("decision"),
        "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
        "ledger_cutoff_id": portfolio.get("ledger_cutoff_id"),
        "account_truth": {
            "schema_version": account_truth.get("schema_version"),
            "promotion_status": account_truth.get("promotion_status"),
            "gate_status": account_truth.get("gate_status"),
            "data_freshness_status": account_truth.get("data_freshness_status"),
            "unresolved_mismatch_count": account_truth.get("unresolved_mismatch_count"),
            "import_run_id": account_truth.get("import_run_id"),
            "source_fingerprint": account_truth.get("source_fingerprint"),
            "captured_at": account_truth.get("captured_at"),
            "max_age_seconds": account_truth.get("max_age_seconds"),
            "reconciliation_status": account_truth.get("reconciliation_status"),
            "ledger_coverage": _object_dict(account_truth.get("ledger_coverage")),
        },
        "market_data": {
            "source_health": market.get("source_health"),
            "latest_quote_timestamp": market.get("latest_quote_timestamp"),
        },
        "candidates": [
            {
                "action_id": item.get("action_id"),
                "symbol": item.get("symbol"),
                "action": item.get("action"),
                "risk_gate_status": item.get("risk_gate_status"),
                "manual_confirmation_status": item.get("manual_confirmation_status"),
            }
            for item in _object_list(decision_payload.get("candidates"))
        ],
        "trading_plan": {
            "schema_version": trading_plan.get("schema_version"),
            "plan_date": trading_plan.get("plan_date"),
            "conclusion_status": trading_plan.get("conclusion_status"),
            "order_intents": _object_list(trading_plan.get("order_intents")),
            "blockers": _object_list(trading_plan.get("blockers")),
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def daily_candidate_input_fingerprint(payload: dict[str, Any]) -> str:
    """Bind every outcome-relevant source while ignoring wall-clock-only age drift."""

    input_snapshot = _object_dict(payload.get("input_snapshot"))
    production_gate = _object_dict(payload.get("production_gate"))
    paper_shadow = _object_dict(payload.get("paper_shadow"))
    execution_closure = _object_dict(payload.get("execution_closure"))
    risk = _object_dict(payload.get("risk"))
    identity = {
        "schema_version": DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
        "decision_plan_fingerprint": input_snapshot.get("decision_plan_fingerprint"),
        "production_gate": {
            "status": production_gate.get("status"),
            "blockers": list(production_gate.get("blockers") or []),
        },
        "decision_outcome": payload.get("decision_outcome"),
        "risk": {
            "status": risk.get("status"),
            "error_type": risk.get("error_type"),
            "error_fingerprint": risk.get("error_fingerprint"),
            "blockers": _object_list(risk.get("blockers")),
        },
        "strategy_gate_bindings": _object_list(
            input_snapshot.get("strategy_gate_bindings")
        ),
        "paper_shadow": {
            "run_id": paper_shadow.get("run_id"),
            "input_fingerprint": paper_shadow.get("input_fingerprint"),
            "status": paper_shadow.get("status"),
            "divergence_status": paper_shadow.get("divergence_status"),
            "simulated_order_count": paper_shadow.get("simulated_order_count"),
            "simulated_fill_count": paper_shadow.get("simulated_fill_count"),
        },
        "execution_closure": {
            "status": execution_closure.get("status"),
            "evidence_fingerprint": execution_closure.get("evidence_fingerprint"),
        },
    }
    return _fingerprint_json(identity)


def _production_outcome(
    *,
    cycle_status: str,
    plan_date: str,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
    paper_shadow: dict[str, Any],
    execution_closure: dict[str, Any],
    account_truth_replay: dict[str, Any],
    additional_blockers: list[str],
) -> dict[str, Any]:
    """Resolve one deterministic ticket-candidate or NO-ACTION conclusion."""

    base_gate = _daily_candidate_base_gate(
        decision_payload=decision_payload,
        trading_plan=trading_plan,
        plan_date=plan_date,
    )
    blockers = [*additional_blockers, *base_gate["blockers"]]
    decision_date = str(base_gate["decision_date"])
    plan_contract_date = str(base_gate["plan_contract_date"])
    valuation_snapshot_id = str(base_gate["valuation_snapshot_id"])
    ledger_cutoff_id = base_gate["ledger_cutoff_id"]
    account_truth = _object_dict(base_gate["account_truth"])
    account_truth_ref = str(base_gate["account_truth_ref"])
    account_truth_source_fingerprint = str(
        base_gate["account_truth_source_fingerprint"]
    )
    account_truth_captured_at = base_gate["account_truth_captured_at"]
    account_truth_max_age = base_gate["account_truth_max_age"]
    account_truth_age_at_decision = base_gate["account_truth_age_at_decision"]
    ledger_coverage = _object_dict(base_gate["ledger_coverage"])
    quote_timestamp = str(base_gate["quote_timestamp"])
    quote_at = base_gate["quote_at"]
    decision_generated_at = base_gate["decision_generated_at"]
    plan_generated_at = base_gate["plan_generated_at"]
    decision_in_window = bool(base_gate["decision_in_window"])
    plan_in_window = bool(base_gate["plan_in_window"])

    if not verify_account_truth_replay_evidence(account_truth_replay):
        blockers.append("account_truth_replay_evidence_invalid")
    elif account_truth_replay.get("status") != "pass":
        blockers.extend(
            f"account_truth_replay:{item}"
            for item in account_truth_replay.get("blockers") or []
            if str(item)
        )
        blockers.append("account_truth_replay_not_clear")
    expected_account_truth_ref = (
        f"account_truth:{account_truth_ref}" if account_truth_ref else None
    )
    if account_truth_replay.get("account_truth_ref") != expected_account_truth_ref:
        blockers.append("account_truth_replay_import_ref_mismatch")
    if account_truth_replay.get("source_fingerprint") != (
        account_truth_source_fingerprint or None
    ):
        blockers.append("account_truth_replay_source_fingerprint_mismatch")
    if account_truth_replay.get("valuation_snapshot_id") != (
        valuation_snapshot_id or None
    ):
        blockers.append("account_truth_replay_valuation_snapshot_mismatch")
    if account_truth_replay.get("ledger_cutoff_id") != ledger_cutoff_id:
        blockers.append("account_truth_replay_ledger_cutoff_mismatch")

    order_intents = _object_list(trading_plan.get("order_intents"))
    strategy_bindings: list[dict[str, Any]] = []
    strategy_gate_bindings: list[dict[str, Any]] = []
    market_quote_bindings: list[dict[str, Any]] = []
    decision_candidates: dict[str, list[dict[str, Any]]] = {}
    for candidate in _object_list(decision_payload.get("candidates")):
        candidate_key = str(candidate.get("action_id") or "")
        if candidate_key:
            decision_candidates.setdefault(candidate_key, []).append(candidate)
    candidate_count = 0
    for index, intent in enumerate(order_intents):
        prefix = f"order_intent_{index}"
        if str(intent.get("asset_class") or "").strip().lower() != "stock":
            blockers.append(f"{prefix}:asset_class_outside_daily_candidate_scope")
        evidence_refs = [
            str(item) for item in intent.get("evidence_refs") or [] if str(item)
        ]
        strategy_ref = _single_ref(evidence_refs, "strategy:")
        advancement_ref = _single_ref(evidence_refs, "strategy_advancement:")
        fee_review_ref = _single_ref(evidence_refs, "reviewed_fee_schedule:")
        risk_ref = _single_ref(evidence_refs, "risk:")
        intent_account_truth_ref = _single_ref(evidence_refs, "account_truth:")
        action_key = str(intent.get("action_id") or "")
        matching_candidates = decision_candidates.get(action_key, [])
        if len(matching_candidates) != 1:
            blockers.append(f"{prefix}:decision_candidate_binding_not_unique")
            candidate = {}
        else:
            candidate = matching_candidates[0]
        strategy_gate_binding, strategy_gate_blockers = _strategy_gate_binding(
            candidate=candidate,
            plan_date=plan_date,
            expected_strategy_ref=strategy_ref,
            expected_advancement_ref=advancement_ref,
            expected_fee_review_ref=fee_review_ref,
            action_id=intent.get("action_id"),
        )
        blockers.extend(f"{prefix}:{item}" for item in strategy_gate_blockers)
        if strategy_gate_binding:
            strategy_gate_bindings.append(strategy_gate_binding)
        if not strategy_ref:
            blockers.append(f"{prefix}:strategy_ref_missing_or_ambiguous")
        if not advancement_ref:
            blockers.append(f"{prefix}:strategy_advancement_ref_missing_or_ambiguous")
        if not fee_review_ref:
            blockers.append(f"{prefix}:reviewed_fee_schedule_ref_missing_or_ambiguous")
        if not risk_ref:
            blockers.append(f"{prefix}:risk_ref_missing_or_ambiguous")
        if intent_account_truth_ref != (
            f"account_truth:{account_truth_ref}" if account_truth_ref else None
        ):
            blockers.append(f"{prefix}:account_truth_ref_mismatch")
        if str(intent.get("risk_gate_status") or "").lower() != "passed":
            blockers.append(f"{prefix}:risk_gate_not_passed")
        if str(intent.get("submission_status") or "").lower() != (
            "manual_confirmation_required"
        ):
            blockers.append(f"{prefix}:manual_confirmation_not_ready")
        if not str(intent.get("fee_rule_id") or ""):
            blockers.append(f"{prefix}:fee_rule_id_missing")
        if _nonnegative_float(intent.get("estimated_total_fee")) is None:
            blockers.append(f"{prefix}:estimated_fee_invalid")
        if _positive_float(intent.get("estimated_quantity")) is None:
            blockers.append(f"{prefix}:estimated_quantity_invalid")
        if _positive_float(intent.get("estimated_gross_amount")) is None:
            blockers.append(f"{prefix}:estimated_gross_amount_invalid")
        if _finite_float(intent.get("estimated_net_cash_impact")) is None:
            blockers.append(f"{prefix}:estimated_net_cash_impact_invalid")
        constraint_checks = _object_list(intent.get("constraint_checks"))
        if not constraint_checks:
            blockers.append(f"{prefix}:constraint_checks_missing")
        elif any(
            str(check.get("status") or "").lower() != "pass"
            for check in constraint_checks
        ):
            blockers.append(f"{prefix}:constraint_check_not_passed")
        fee_breakdown = _object_dict(intent.get("fee_breakdown"))
        if not fee_breakdown:
            blockers.append(f"{prefix}:fee_breakdown_missing")
        intent_quote_at = _aware_datetime(intent.get("market_quote_timestamp"))
        intent_quote_price = _nonnegative_float(intent.get("market_quote_price"))
        intent_estimated_price = _nonnegative_float(intent.get("estimated_price"))
        intent_quote_source = str(intent.get("market_quote_source") or "").strip()
        if _shanghai_date(intent_quote_at) != plan_date:
            blockers.append(f"{prefix}:market_quote_not_bound_to_plan_date")
        if (
            intent_quote_at is not None
            and decision_generated_at is not None
            and intent_quote_at > decision_generated_at
        ):
            blockers.append(f"{prefix}:market_quote_after_decision_generation")
        elif (
            intent_quote_at is not None
            and decision_generated_at is not None
            and (decision_generated_at - intent_quote_at).total_seconds()
            > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS
        ):
            blockers.append(f"{prefix}:market_quote_too_old_for_decision")
        if not intent_quote_source:
            blockers.append(f"{prefix}:market_quote_source_missing")
        if intent_quote_price is None or intent_quote_price <= 0:
            blockers.append(f"{prefix}:market_quote_price_invalid")
        if (
            intent_estimated_price is None
            or intent_estimated_price <= 0
            or intent_estimated_price != intent_quote_price
        ):
            blockers.append(f"{prefix}:estimated_price_not_bound_to_market_quote")
        if intent.get("does_not_submit_broker_order") is not True:
            blockers.append(f"{prefix}:broker_boundary_invalid")
        if strategy_ref and advancement_ref:
            strategy_bindings.append(
                {
                    "strategy_ref": strategy_ref,
                    "strategy_advancement_ref": advancement_ref,
                    "reviewed_fee_schedule_ref": fee_review_ref,
                }
            )
        market_quote_bindings.append(
            {
                "intent_ref": str(
                    intent.get("intent_id") or intent.get("action_id") or index
                ),
                "timestamp": (
                    intent_quote_at.isoformat() if intent_quote_at is not None else None
                ),
                "source": intent_quote_source or None,
                "price": intent_quote_price,
            }
        )
        candidate_count += 1

    if order_intents:
        if paper_shadow.get("status") != "within_expectations":
            blockers.append("paper_shadow_status_not_within_expectations")
        if paper_shadow.get("divergence_status") != "within_expectations":
            blockers.append("paper_shadow_divergence_not_clear")
        if not paper_shadow.get("run_id") or not paper_shadow.get("input_fingerprint"):
            blockers.append("paper_shadow_identity_missing")
        if _count(paper_shadow.get("simulated_order_count")) != len(order_intents):
            blockers.append("paper_shadow_order_count_mismatch")
        if _count(paper_shadow.get("simulated_fill_count")) != len(order_intents):
            blockers.append("paper_shadow_fill_count_mismatch")
    elif paper_shadow.get("status") not in {"not_run", None}:
        blockers.append("paper_shadow_present_without_order_intent")

    if cycle_status not in _TERMINAL_EVIDENCE_STATUSES:
        blockers.append(f"daily_cycle_not_evidence_clear:{cycle_status}")

    if execution_closure.get("schema_version") != (
        "karkinos.daily_candidate_execution_closure.v1"
    ):
        blockers.append("execution_closure_contract_invalid")
    if execution_closure.get("status") not in {"pass", "not_required"}:
        closure_blockers = [
            str(item) for item in execution_closure.get("blockers") or [] if str(item)
        ]
        blockers.extend(f"execution_closure:{item}" for item in closure_blockers)
        blockers.append("prior_execution_not_reconciled")
    if not _is_sha256(execution_closure.get("evidence_fingerprint")):
        blockers.append("execution_closure_fingerprint_invalid")

    blockers = list(dict.fromkeys(blockers))
    gate_status = "pass" if not blockers else "blocked"
    decision_outcome = (
        "manual_order_ticket_candidate"
        if gate_status == "pass" and candidate_count > 0
        else "no_action"
    )
    no_action_reasons = (
        []
        if decision_outcome == "manual_order_ticket_candidate"
        else blockers or ["no_strategy_action"]
    )
    account_truth_binding = {
        "schema_version": "karkinos.daily_candidate_account_truth_binding.v2",
        "account_truth_ref": (
            f"account_truth:{account_truth_ref}" if account_truth_ref else None
        ),
        "source_fingerprint": account_truth_source_fingerprint or None,
        "captured_at": (
            account_truth_captured_at.isoformat()
            if account_truth_captured_at is not None
            else None
        ),
        "age_seconds_at_decision": account_truth_age_at_decision,
        "max_age_seconds": account_truth_max_age,
        "valuation_snapshot_id": valuation_snapshot_id or None,
        "ledger_cutoff_id": ledger_cutoff_id,
        "reconciliation_status": account_truth.get("reconciliation_status"),
        "ledger_coverage_status": ledger_coverage.get("status"),
        "replay_evidence": account_truth_replay,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    manual_order_ticket_candidates = (
        [
            _manual_order_ticket_candidate(
                plan_date=plan_date,
                intent=intent,
                paper_shadow=paper_shadow,
                execution_closure=execution_closure,
                decision_generated_at=decision_generated_at,
                strategy_gate_binding=next(
                    (
                        item
                        for item in strategy_gate_bindings
                        if str(item.get("action_id") or "")
                        == str(intent.get("action_id") or "")
                    ),
                    {},
                ),
                account_truth_binding=account_truth_binding,
            )
            for intent in order_intents
        ]
        if decision_outcome == "manual_order_ticket_candidate"
        else []
    )
    input_snapshot = {
        "decision_date": decision_date or None,
        "plan_date": plan_contract_date or None,
        "valuation_snapshot_id": valuation_snapshot_id or None,
        "ledger_cutoff_id": ledger_cutoff_id,
        "account_truth_ref": (
            f"account_truth:{account_truth_ref}" if account_truth_ref else None
        ),
        "account_truth_source_fingerprint": (account_truth_source_fingerprint or None),
        "account_truth_captured_at": (
            account_truth_captured_at.isoformat()
            if account_truth_captured_at is not None
            else None
        ),
        "account_truth_age_seconds_at_decision": account_truth_age_at_decision,
        "account_truth_max_age_seconds": account_truth_max_age,
        "account_truth_reconciliation_status": account_truth.get(
            "reconciliation_status"
        ),
        "account_truth_ledger_coverage_status": ledger_coverage.get("status"),
        "account_truth_replay_evidence": account_truth_replay,
        "account_truth_binding": account_truth_binding,
        "market_quote_timestamp": quote_timestamp or None,
        "market_quote_age_seconds_at_decision": (
            int((decision_generated_at - quote_at).total_seconds())
            if decision_generated_at is not None
            and quote_at is not None
            and quote_at <= decision_generated_at
            else None
        ),
        "market_quote_max_age_seconds": DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
        "decision_window": {
            "schema_version": DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION,
            "timezone": "Asia/Shanghai",
            "start": "09:35",
            "end_exclusive": "09:45",
            "decision_generated_at": (
                decision_generated_at.isoformat()
                if decision_generated_at is not None
                else None
            ),
            "plan_generated_at": (
                plan_generated_at.isoformat() if plan_generated_at is not None else None
            ),
            "status": ("pass" if decision_in_window and plan_in_window else "blocked"),
        },
        "paper_shadow_run_id": paper_shadow.get("run_id"),
        "paper_shadow_input_fingerprint": paper_shadow.get("input_fingerprint"),
        "execution_closure_fingerprint": execution_closure.get("evidence_fingerprint"),
        "prior_production_order_count": execution_closure.get("production_order_count"),
        "order_intent_count": len(order_intents),
        "strategy_advancement_refs": sorted(
            {
                item["strategy_advancement_ref"]
                for item in strategy_bindings
                if item.get("strategy_advancement_ref")
            }
        ),
        "reviewed_fee_schedule_refs": sorted(
            {
                item["reviewed_fee_schedule_ref"]
                for item in strategy_bindings
                if item.get("reviewed_fee_schedule_ref")
            }
        ),
        "strategy_gate_bindings": strategy_gate_bindings,
        "market_quote_bindings": market_quote_bindings,
    }
    return {
        "decision_outcome": decision_outcome,
        "manual_ticket_candidate_count": (len(manual_order_ticket_candidates)),
        "manual_order_ticket_candidates": manual_order_ticket_candidates,
        "no_action_reasons": no_action_reasons,
        "strategy_bindings": strategy_bindings,
        "input_snapshot": input_snapshot,
        "production_gate": {
            "schema_version": "karkinos.daily_candidate_production_gate.v1",
            "status": gate_status,
            "blockers": blockers,
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        },
    }


def _strategy_gate_binding(
    *,
    candidate: dict[str, Any],
    plan_date: str,
    expected_strategy_ref: str | None,
    expected_advancement_ref: str | None,
    expected_fee_review_ref: str | None,
    action_id: Any,
) -> tuple[dict[str, Any], list[str]]:
    return build_daily_candidate_strategy_gate_binding(
        candidate=candidate,
        plan_date=plan_date,
        expected_strategy_ref=expected_strategy_ref,
        expected_advancement_ref=expected_advancement_ref,
        expected_fee_review_ref=expected_fee_review_ref,
        action_id=action_id,
    )


def build_daily_candidate_strategy_gate_binding(
    *,
    candidate: dict[str, Any],
    plan_date: str,
    expected_strategy_ref: str | None,
    expected_advancement_ref: str | None,
    expected_fee_review_ref: str | None,
    action_id: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Build one replayable current-strategy binding for a daily ticket."""

    blockers: list[str] = []
    strategy = _object_dict(_object_dict(candidate.get("evidence")).get("strategy"))
    strategy_id = str(strategy.get("strategy_id") or "")
    if not strategy_id or expected_strategy_ref != f"strategy:{strategy_id}":
        blockers.append("strategy_identity_mismatch")
    gate = _object_dict(strategy.get("order_generation_gate"))
    if gate.get("schema_version") != "karkinos.strategy_order_generation_gate.v1":
        blockers.append("strategy_order_generation_contract_invalid")
    if gate.get("status") != "pass" or gate.get("blockers") not in ([], None):
        blockers.append("strategy_order_generation_gate_not_pass")
    if str(gate.get("as_of_date") or "") != plan_date:
        blockers.append("strategy_order_generation_date_mismatch")
    expected_gate_boundaries = {
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "paper_shadow_evaluation_only": True,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
        "broker_submission_enabled": False,
    }
    for field, expected in expected_gate_boundaries.items():
        if gate.get(field) is not expected:
            blockers.append(f"strategy_order_generation_{field}_invalid")

    promotion = _object_dict(gate.get("promotion"))
    if promotion.get("status") != "pass":
        blockers.append("strategy_promotion_not_pass")
    if promotion.get("stage") != "paper_shadow":
        blockers.append("strategy_promotion_stage_invalid")
    if promotion.get("gate_status") != "paper_shadow_enabled":
        blockers.append("strategy_paper_shadow_gate_not_enabled")
    if promotion.get("live_like_enabled") is not False:
        blockers.append("strategy_live_like_boundary_invalid")
    if not str(promotion.get("human_reviewer") or "").strip():
        blockers.append("strategy_human_reviewer_missing")
    if promotion.get("human_review_note_recorded") is not True:
        blockers.append("strategy_human_review_note_missing")
    comparison_fingerprint = str(promotion.get("comparison_fingerprint") or "")
    if not _is_sha256(comparison_fingerprint):
        blockers.append("strategy_comparison_fingerprint_invalid")
    human_approval_id = str(promotion.get("human_approval_id") or "")
    if not human_approval_id:
        blockers.append("strategy_human_approval_missing")
    daily_strategy_artifact_binding = _object_dict(
        promotion.get("daily_strategy_artifact_binding")
    )
    strategy_operating_constraints: dict[str, Any] = {}
    if strategy_id.startswith("ai_formula_shadow:"):
        if daily_strategy_artifact_binding.get("schema_version") != (
            DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA_VERSION
        ):
            blockers.append("strategy_daily_artifact_binding_contract_invalid")
        for field in (
            "run_id",
            "market_date",
            "winner_candidate_id",
            "selection_id",
            "backup_id",
        ):
            if not str(daily_strategy_artifact_binding.get(field) or "").strip():
                blockers.append(f"strategy_daily_artifact_{field}_missing")
        for field in (
            "selection_fingerprint",
            "backup_artifact_fingerprint",
        ):
            if not _is_sha256(daily_strategy_artifact_binding.get(field)):
                blockers.append(f"strategy_daily_artifact_{field}_invalid")
        if daily_strategy_artifact_binding.get("winner_candidate_id") != (
            strategy_id.removeprefix("ai_formula_shadow:")
        ):
            blockers.append("strategy_daily_artifact_candidate_mismatch")
        if (
            daily_strategy_artifact_binding.get("contains_private_account_identifiers")
            is not False
            or daily_strategy_artifact_binding.get("contains_broker_export_rows")
            is not False
            or daily_strategy_artifact_binding.get("does_not_change_capital_authority")
            is not True
            or daily_strategy_artifact_binding.get("authority_effect")
            != "research_only"
        ):
            blockers.append("strategy_daily_artifact_authority_boundary_invalid")
        strategy_operating_constraints = _object_dict(
            daily_strategy_artifact_binding.get("operating_constraints")
        )
        blockers.extend(
            daily_candidate_strategy_operating_constraints_blockers(
                strategy_operating_constraints,
                expected_candidate_id=strategy_id.removeprefix("ai_formula_shadow:"),
                expected_backup_fingerprint=str(
                    daily_strategy_artifact_binding.get("backup_artifact_fingerprint")
                    or ""
                ),
            )
        )

    advancement_fingerprint = str(
        promotion.get("strategy_advancement_gate_fingerprint") or ""
    )
    if not _is_sha256(advancement_fingerprint):
        blockers.append("strategy_advancement_fingerprint_invalid")
    if expected_advancement_ref != f"strategy_advancement:{advancement_fingerprint}":
        blockers.append("strategy_advancement_ref_mismatch")
    fee_binding = _object_dict(promotion.get("fee_schedule_binding"))
    fee_review_fingerprint = str(
        fee_binding.get("fee_schedule_review_fingerprint") or ""
    )
    if not _is_sha256(fee_review_fingerprint):
        blockers.append("reviewed_fee_schedule_fingerprint_invalid")
    if expected_fee_review_ref != (f"reviewed_fee_schedule:{fee_review_fingerprint}"):
        blockers.append("reviewed_fee_schedule_ref_mismatch")

    dataset_replay = _object_dict(promotion.get("dataset_replay"))
    dataset_replay_fingerprint = str(dataset_replay.get("evidence_fingerprint") or "")
    if dataset_replay.get("status") != "pass" or dataset_replay.get("blockers") not in (
        [],
        None,
    ):
        blockers.append("strategy_frozen_dataset_replay_not_pass")
    if not _is_sha256(dataset_replay_fingerprint):
        blockers.append("strategy_frozen_dataset_replay_fingerprint_invalid")
    if dataset_replay.get("persisted_market_bars_only") is not True:
        blockers.append("strategy_frozen_dataset_not_persisted_only")
    if dataset_replay.get("provider_contacted") is not False:
        blockers.append("strategy_frozen_dataset_provider_boundary_invalid")
    if dataset_replay.get("baseline_manifest_matches_candidate") is not True:
        blockers.append("strategy_frozen_dataset_baseline_mismatch")
    baseline_snapshot_id = str(dataset_replay.get("baseline_snapshot_id") or "")
    candidate_snapshot_id = str(dataset_replay.get("candidate_snapshot_id") or "")
    if not baseline_snapshot_id or not candidate_snapshot_id:
        blockers.append("strategy_frozen_dataset_snapshot_identity_missing")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        return {}, blockers
    binding = {
        "schema_version": DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION,
        "action_id": action_id,
        "strategy_ref": expected_strategy_ref,
        "strategy_advancement_ref": expected_advancement_ref,
        "reviewed_fee_schedule_ref": expected_fee_review_ref,
        "comparison_fingerprint": comparison_fingerprint,
        "human_approval_id": human_approval_id,
        "dataset_replay_fingerprint": dataset_replay_fingerprint,
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "paper_shadow_evaluation_only": True,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    if daily_strategy_artifact_binding:
        binding["daily_strategy_artifact_binding"] = daily_strategy_artifact_binding
    if strategy_operating_constraints:
        binding["strategy_operating_constraints"] = strategy_operating_constraints
    return binding, []


def daily_candidate_strategy_operating_constraints_blockers(
    value: dict[str, Any],
    *,
    expected_candidate_id: str,
    expected_backup_fingerprint: str,
) -> list[str]:
    blockers: list[str] = []
    if value.get("schema_version") != (
        DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA_VERSION
    ):
        blockers.append("strategy_operating_constraints_contract_invalid")
    if value.get("candidate_id") != expected_candidate_id:
        blockers.append("strategy_operating_constraints_candidate_mismatch")
    if value.get("source_backup_artifact_fingerprint") != (expected_backup_fingerprint):
        blockers.append("strategy_operating_constraints_backup_mismatch")
    for field in (
        "strategy_artifact_fingerprint",
        "source_backup_artifact_fingerprint",
        "evidence_fingerprint",
    ):
        if not _is_sha256(value.get(field)):
            blockers.append(f"strategy_operating_constraints_{field}_invalid")
    for field in ("economic_hypothesis", "risk_impact"):
        if not str(value.get(field) or "").strip():
            blockers.append(f"strategy_operating_constraints_{field}_missing")
    for field in (
        "failure_conditions",
        "limitations",
        "anti_lookahead_assumptions",
    ):
        items = value.get(field)
        if (
            not isinstance(items, list)
            or not items
            or any(not str(item).strip() for item in items)
        ):
            blockers.append(f"strategy_operating_constraints_{field}_invalid")
    expected_boundaries = {
        "automatic_enforcement_enabled": False,
        "human_review_required": True,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_boundaries.items():
        if value.get(field) is not expected:
            blockers.append(f"strategy_operating_constraints_{field}_invalid")
    stable = {key: item for key, item in value.items() if key != "evidence_fingerprint"}
    if value.get("evidence_fingerprint") != _fingerprint_json(stable):
        blockers.append("strategy_operating_constraints_fingerprint_mismatch")
    return list(dict.fromkeys(blockers))


def _manual_order_ticket_candidate(
    *,
    plan_date: str,
    intent: dict[str, Any],
    paper_shadow: dict[str, Any],
    execution_closure: dict[str, Any],
    decision_generated_at: datetime | None,
    strategy_gate_binding: dict[str, Any],
    account_truth_binding: dict[str, Any],
) -> dict[str, Any]:
    evidence_refs = sorted(
        {str(item) for item in intent.get("evidence_refs") or [] if str(item)}
    )
    quote_at = _aware_datetime(intent.get("market_quote_timestamp"))
    quote_age_seconds = (
        int((decision_generated_at - quote_at).total_seconds())
        if decision_generated_at is not None
        and quote_at is not None
        and quote_at <= decision_generated_at
        else None
    )
    core = {
        "schema_version": DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION,
        "plan_date": plan_date,
        "intent_id": intent.get("intent_id"),
        "action_id": intent.get("action_id"),
        "symbol": intent.get("symbol"),
        "side": intent.get("side"),
        "asset_class": intent.get("asset_class"),
        "order_type": "limit",
        "quantity": intent.get("estimated_quantity"),
        "limit_price": intent.get("estimated_price"),
        "estimated_gross_amount": intent.get("estimated_gross_amount"),
        "estimated_total_fee": intent.get("estimated_total_fee"),
        "estimated_net_cash_impact": intent.get("estimated_net_cash_impact"),
        "available_cash_before": intent.get("available_cash_before"),
        "available_cash_after": intent.get("available_cash_after"),
        "cash_status": intent.get("cash_status"),
        "fee_rule_id": intent.get("fee_rule_id"),
        "fee_rule_version": intent.get("fee_rule_version"),
        "fee_breakdown": _object_dict(intent.get("fee_breakdown")),
        "risk_gate_status": intent.get("risk_gate_status"),
        "constraint_checks": _object_list(intent.get("constraint_checks")),
        "market_quote": {
            "price": intent.get("market_quote_price"),
            "timestamp": intent.get("market_quote_timestamp"),
            "source": intent.get("market_quote_source"),
            "age_seconds_at_decision": quote_age_seconds,
            "max_age_seconds": DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
        },
        "paper_shadow": {
            "run_id": paper_shadow.get("run_id"),
            "input_fingerprint": paper_shadow.get("input_fingerprint"),
            "status": paper_shadow.get("status"),
            "divergence_status": paper_shadow.get("divergence_status"),
        },
        "strategy_gate_binding": strategy_gate_binding,
        "strategy_operating_constraints": _object_dict(
            strategy_gate_binding.get("strategy_operating_constraints")
        ),
        "account_truth_binding": account_truth_binding,
        "prior_execution_closure_fingerprint": execution_closure.get(
            "evidence_fingerprint"
        ),
        "evidence_refs": evidence_refs,
        "invalidation_conditions": [
            "plan_date_is_no_longer_current_market_date",
            "decision_or_plan_generated_outside_reviewed_window",
            "account_truth_source_or_ledger_coverage_changes",
            "market_quote_price_timestamp_or_source_changes",
            "risk_strategy_fee_or_paper_shadow_binding_changes",
            "prior_execution_closure_changes",
            "kill_switch_is_enabled",
        ],
        "manual_confirmation_required": True,
        "creates_oms_order": False,
        "authorizes_execution": False,
        "broker_submission_enabled": False,
        "does_not_change_capital_authority": True,
    }
    return {
        **core,
        "ticket_candidate_fingerprint": manual_ticket_candidate_fingerprint(core),
    }


def manual_ticket_candidate_fingerprint(payload: dict[str, Any]) -> str:
    """Hash a read-only ticket candidate without trusting its stored digest."""

    core = {
        key: value
        for key, value in payload.items()
        if key != "ticket_candidate_fingerprint"
    }
    return _fingerprint_json(core)


def _fingerprint_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_float(value: Any) -> float | None:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _positive_float(value: Any) -> float | None:
    normalized = _finite_float(value)
    return normalized if normalized is not None and normalized > 0 else None


def daily_candidate_record_fingerprint(payload: dict[str, Any]) -> str:
    """Hash the complete safe production decision record for replay checks."""

    stable = {key: payload.get(key) for key in _PRODUCTION_RECORD_FIELDS}
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _single_ref(refs: list[str], prefix: str) -> str | None:
    matches = [ref for ref in refs if ref.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _aware_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _shanghai_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_SHANGHAI_TZ).date().isoformat()


def _in_daily_candidate_decision_window(
    value: datetime | None,
    *,
    plan_date: str,
) -> bool:
    if value is None:
        return False
    shanghai_value = value.astimezone(_SHANGHAI_TZ)
    minute_of_day = shanghai_value.hour * 60 + shanghai_value.minute
    return bool(
        shanghai_value.date().isoformat() == plan_date
        and DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE
        <= minute_of_day
        < DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE
    )


def _positive_int(value: Any) -> int | None:
    parsed = _nonnegative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _nonnegative_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _risk_summary(
    result: dict[str, Any] | None,
    decision_payload: dict[str, Any],
) -> dict[str, Any]:
    payload = _object_dict(result)
    decision_summary = _object_dict(decision_payload.get("summary"))
    audit = _object_dict(decision_summary.get("audit"))
    candidates = _object_list(decision_payload.get("candidates"))
    current_passed_count = sum(
        1
        for candidate in candidates
        if str(candidate.get("risk_gate_status") or "").lower() == "passed"
    )
    current_blocked_count = sum(
        1
        for candidate in candidates
        if str(candidate.get("risk_gate_status") or "").lower() == "blocked"
    )
    current_checked_count = _count(audit.get("risk_checked_count"))
    if not current_checked_count:
        current_checked_count = current_passed_count + current_blocked_count
    error = str(payload.get("error") or "").strip()
    return {
        "status": payload.get("status") or "not_run",
        "candidate_count": _count(
            decision_summary.get("candidate_count"),
            payload.get("candidate_count"),
        ),
        "checked_count": current_checked_count,
        "passed_count": current_passed_count,
        "blocked_count": current_blocked_count,
        "newly_processed_count": _count(payload.get("processed_count")),
        "newly_passed_count": _count(payload.get("passed_count")),
        "newly_blocked_count": _count(payload.get("blocked_count")),
        "skipped_count": _count(payload.get("skipped_count")),
        "risk_decision_writes_performed": bool(
            payload.get("risk_decision_writes_performed", False)
        ),
        "blockers": _object_list(payload.get("blockers")),
        "error_type": str(payload.get("error_type") or "").strip() or None,
        "error_fingerprint": (
            hashlib.sha256(error.encode("utf-8")).hexdigest() if error else None
        ),
    }


def _paper_shadow_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = _object_dict(result)
    return {
        "status": payload.get("status") or "not_run",
        "run_id": payload.get("run_id"),
        "input_fingerprint": payload.get("input_fingerprint"),
        "order_intent_count": _count(payload.get("order_intent_count")),
        "simulated_order_count": _count(payload.get("simulated_order_count")),
        "simulated_fill_count": _count(payload.get("simulated_fill_count")),
        "divergence_status": payload.get("divergence_status"),
        "next_manual_review_step": payload.get("next_manual_review_step"),
    }


def _latest_paper_shadow_run(db: Any, *, plan_date: str) -> dict[str, Any] | None:
    reader = getattr(db, "latest_paper_shadow_run_sync", None)
    if not callable(reader):
        return None
    return reader(plan_date=plan_date)


def _is_new_paper_shadow_evidence(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> bool:
    if previous is None:
        return True
    return str(previous.get("input_fingerprint") or "") != str(
        current.get("input_fingerprint") or ""
    )


def _object_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return _object_list(value)


def _count(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            continue
    return 0
