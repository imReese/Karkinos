"""Automatic risk-to-paper/shadow evidence chain for daily decisions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from server.services.automation_control import AutomationControlService
from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan

DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION = (
    "karkinos.daily_decision_evidence_automation.v1"
)
DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE = "daily_decision_evidence"

logger = logging.getLogger(__name__)

PlanReader = Callable[[], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]
RiskRunner = Callable[[], Awaitable[dict[str, Any]]]


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
    ) -> None:
        self._db = db
        self._trading_controls = trading_controls
        self._notifier = notifier
        self._plan_reader = plan_reader
        self._risk_runner = risk_runner
        self._automation = AutomationControlService(
            db=db,
            trading_controls=trading_controls,
        )

    async def run_once(self) -> dict[str, Any]:
        """Advance one fail-closed, idempotent evidence cycle."""
        started_at = datetime.now().isoformat()
        decision_before, plan_before = await self._plan_reader()
        plan_date = _plan_date(decision_before, plan_before)
        candidate_count = _candidate_count(decision_before, plan_before)
        policy_status = self._automation.get_status()

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
        risk_status = str(risk_result.get("status") or "unknown")
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
        result = self._record_cycle(
            status="paper_shadow_completed",
            plan_date=plan_date,
            decision_payload=decision_after,
            trading_plan=plan_after,
            started_at=started_at,
            risk_result=risk_result,
            paper_shadow_run=paper_shadow_run,
            candidate_count=candidate_count,
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
    ) -> dict[str, Any]:
        finished_at = datetime.now().isoformat()
        fingerprint = _evidence_fingerprint(decision_payload, trading_plan)
        risk_summary = _risk_summary(risk_result, decision_payload)
        paper_shadow_summary = _paper_shadow_summary(paper_shadow_run)
        payload = {
            "schema_version": DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
            "input_fingerprint": fingerprint,
            "candidate_count": candidate_count,
            "risk": risk_summary,
            "paper_shadow": paper_shadow_summary,
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
            "limitations": list(limitations),
        }
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
            "status": status,
            "run_id": row["run_id"],
            "plan_date": plan_date,
            "input_fingerprint": fingerprint,
            "candidate_count": candidate_count,
            "risk": risk_summary,
            "paper_shadow": paper_shadow_summary,
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
            await asyncio.to_thread(sender, title=title, message=message)
        except Exception as exc:
            logger.warning("Automatic evidence notification failed", exc_info=True)
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
) -> None:
    """Run the safe evidence chain now and on each live polling interval."""
    service = build_daily_decision_evidence_automation_service(state)
    interval = max(float(interval_seconds), 1.0)
    while True:
        try:
            await service.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected daily decision evidence automation failure")
        await asyncio.sleep(interval)


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


def _evidence_fingerprint(
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> str:
    summary = _object_dict(decision_payload.get("summary"))
    portfolio = _object_dict(summary.get("portfolio"))
    payload = {
        "decision_date": decision_payload.get("decision_date"),
        "decision": decision_payload.get("decision"),
        "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
        "ledger_cutoff_id": portfolio.get("ledger_cutoff_id"),
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


def _count(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            continue
    return 0
