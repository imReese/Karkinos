"""One persisted daily evidence cycle and privacy-minimized notifications."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from server.services.daily_candidate_execution_closure import (
    build_daily_candidate_execution_closure,
)
from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
    AccountTruthReplayResolver,
)
from server.services.daily_decision_evidence_identity import (
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
    evidence_fingerprint,
)
from server.services.daily_decision_evidence_values import (
    nonnegative_int,
    object_dict,
)
from server.services.daily_decision_evidence_values import (
    paper_shadow_summary as build_paper_shadow_summary,
)
from server.services.daily_decision_evidence_values import (
    risk_summary as build_risk_summary,
)
from server.services.daily_decision_production_outcome import project_production_outcome

logger = logging.getLogger(__name__)


def record_cycle(
    *,
    db: Any,
    account_truth_replay_resolver: AccountTruthReplayResolver,
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
    decision_plan_fingerprint = evidence_fingerprint(
        decision_payload,
        trading_plan,
    )
    risk_summary = build_risk_summary(risk_result, decision_payload)
    paper_shadow_summary = build_paper_shadow_summary(paper_shadow_run)
    execution_closure = build_daily_candidate_execution_closure(db)
    summary = object_dict(decision_payload.get("summary"))
    portfolio = object_dict(summary.get("portfolio"))
    account_truth = object_dict(summary.get("account_truth"))
    try:
        account_truth_replay = account_truth_replay_resolver(
            db,
            account_truth_ref=str(account_truth.get("import_run_id") or ""),
            source_fingerprint=str(account_truth.get("source_fingerprint") or ""),
            valuation_snapshot_id=str(portfolio.get("valuation_snapshot_id") or ""),
            ledger_cutoff_id=nonnegative_int(portfolio.get("ledger_cutoff_id")),
        )
    except Exception:
        account_truth_replay = {}
    production = project_production_outcome(
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
        "manual_ticket_candidate_count": production["manual_ticket_candidate_count"],
        "manual_order_ticket_candidates": production["manual_order_ticket_candidates"],
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
    row = db.upsert_automation_run_sync(
        {
            "run_id": (
                f"automation:daily-decision-evidence:{plan_date}:" f"{fingerprint[:12]}"
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
        "manual_ticket_candidate_count": production["manual_ticket_candidate_count"],
        "manual_order_ticket_candidates": production["manual_order_ticket_candidates"],
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


async def send_evidence_notification(
    *,
    notifier: Any,
    timeout_seconds: float,
    plan_date: str,
    risk_summary: dict[str, Any],
    paper_shadow_run: dict[str, Any],
) -> dict[str, Any]:
    sender = getattr(notifier, "send", None)
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
            timeout=timeout_seconds,
        )
    except Exception as exc:
        logger.warning("Automatic evidence notification failed", exc_info=True)
        return {
            "status": "failed",
            "sent": False,
            "error_type": type(exc).__name__,
        }
    return {"status": "sent", "sent": True}


async def send_no_action_notification(
    *,
    notifier: Any,
    timeout_seconds: float,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Notify a background NO-ACTION without exposing financial values."""

    sender = getattr(notifier, "send", None)
    if not callable(sender):
        return {"status": "notifier_unavailable", "sent": False}
    plan_date = str(result.get("plan_date") or "unknown")
    reasons = [str(item) for item in result.get("no_action_reasons") or [] if str(item)]
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
            timeout=timeout_seconds,
        )
    except Exception as exc:
        logger.warning("Daily candidate NO-ACTION notification failed", exc_info=True)
        return {
            "status": "failed",
            "sent": False,
            "error_type": type(exc).__name__,
        }
    return {"status": "sent", "sent": True}
