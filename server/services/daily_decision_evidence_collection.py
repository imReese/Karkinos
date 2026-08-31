"""Provider-free daily risk and paper/shadow evidence collection workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from server.services.daily_decision_evidence_contracts import PlanReader, RiskRunner
from server.services.daily_decision_evidence_values import (
    candidate_count as count_candidates,
)
from server.services.daily_decision_evidence_values import (
    daily_candidate_asset_scope_blockers,
    is_new_paper_shadow_evidence,
    latest_paper_shadow_run,
    object_list,
)
from server.services.daily_decision_evidence_values import (
    plan_date as resolve_plan_date,
)
from server.services.daily_decision_evidence_values import (
    policy_allows_paper_shadow,
)


async def collect_daily_decision_evidence(
    *,
    db: Any,
    automation: Any,
    plan_reader: PlanReader,
    risk_runner: RiskRunner,
    record_cycle: Callable[..., dict[str, Any]],
    send_notification: Callable[..., Awaitable[dict[str, Any]]],
    run_paper_shadow: Callable[..., dict[str, Any]],
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
    decision_before, plan_before = await plan_reader()
    plan_date = resolve_plan_date(decision_before, plan_before)
    candidate_count = count_candidates(decision_before, plan_before)
    policy_status = automation.get_status()

    if expected_plan_date is not None and (
        str(decision_before.get("decision_date") or "") != expected_plan_date
        or str(plan_before.get("plan_date") or "") != expected_plan_date
    ):
        return record_cycle(
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

    if not policy_allows_paper_shadow(policy_status):
        return record_cycle(
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

    asset_scope_blockers = daily_candidate_asset_scope_blockers(
        decision_payload=decision_before,
        trading_plan=plan_before,
    )
    if asset_scope_blockers:
        return record_cycle(
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
        return record_cycle(
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
        risk_result = await risk_runner()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return record_cycle(
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

    decision_after, plan_after = await plan_reader()
    plan_date = resolve_plan_date(decision_after, plan_after)
    candidate_count = count_candidates(decision_after, plan_after)
    if expected_plan_date is not None and (
        str(decision_after.get("decision_date") or "") != expected_plan_date
        or str(plan_after.get("plan_date") or "") != expected_plan_date
    ):
        return record_cycle(
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
    asset_scope_blockers = daily_candidate_asset_scope_blockers(
        decision_payload=decision_after,
        trading_plan=plan_after,
    )
    if asset_scope_blockers:
        return record_cycle(
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
        return record_cycle(
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

    order_intents = object_list(plan_after.get("order_intents"))
    if not order_intents:
        return record_cycle(
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

    previous_run = latest_paper_shadow_run(db, plan_date=plan_date)
    try:
        paper_shadow_run = await asyncio.to_thread(
            run_paper_shadow,
            db=db,
            trading_plan=plan_after,
            generated_at=(
                plan_after.get("generated_at") or decision_after.get("generated_at")
            ),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return record_cycle(
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

    automation.record_paper_shadow_run(
        run_date=plan_date,
        source_ref=paper_shadow_run.get("run_id"),
        paper_shadow_run=paper_shadow_run,
    )
    try:
        decision_final, plan_final = await plan_reader()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return record_cycle(
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
            additional_blockers=[f"post_shadow_plan_read_failed:{type(exc).__name__}"],
        )

    final_plan_date = resolve_plan_date(decision_final, plan_final)
    if expected_plan_date is not None and (
        str(decision_final.get("decision_date") or "") != expected_plan_date
        or str(plan_final.get("plan_date") or "") != expected_plan_date
    ):
        return record_cycle(
            status="blocked_by_plan_date_mismatch",
            plan_date=expected_plan_date,
            decision_payload=decision_final,
            trading_plan=plan_final,
            started_at=started_at,
            risk_result=risk_result,
            paper_shadow_run=paper_shadow_run,
            candidate_count=count_candidates(decision_final, plan_final),
            limitations=[
                "The claimed trading date drifted after paper/shadow evidence was "
                "persisted; notification and ticket candidacy remained closed."
            ],
            additional_blockers=["daily_candidate_claimed_plan_date_mismatch"],
        )
    result = record_cycle(
        status="paper_shadow_completed",
        plan_date=final_plan_date,
        decision_payload=decision_final,
        trading_plan=plan_final,
        started_at=started_at,
        risk_result=risk_result,
        paper_shadow_run=paper_shadow_run,
        candidate_count=count_candidates(decision_final, plan_final),
        limitations=[],
    )
    if is_new_paper_shadow_evidence(previous_run, paper_shadow_run):
        result["notification"] = await send_notification(
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
