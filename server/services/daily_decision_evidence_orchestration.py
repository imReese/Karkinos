"""Persistence orchestration for claimed daily automation attempts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
    DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION,
)
from server.services.daily_decision_evidence_values import count, object_dict

logger = logging.getLogger(__name__)


async def run_claimed_daily_candidate_preparation_check(
    *,
    state: Any,
    schedule: dict[str, Any],
    build_preparation_check: Callable[..., dict[str, Any]],
    verify_preparation_check: Callable[..., bool],
    notification_timeout_seconds: float,
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
    run = object_dict(claim.get("run"))
    try:
        preparation = build_preparation_check(
            state,
            run_date=run_date,
        )
        if not verify_preparation_check(
            preparation,
            run_date=run_date,
        ):
            raise ValueError("daily candidate preparation contract invalid")
        notification = await send_daily_candidate_preparation_notification(
            notifier=getattr(state, "notifier", None),
            preparation=preparation,
            timeout_seconds=notification_timeout_seconds,
        )
        operator_alert = record_daily_candidate_preparation_alert(
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
        operator_alert = record_daily_candidate_preparation_alert(
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
        operator_alert = record_daily_candidate_preparation_alert(
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


async def send_daily_candidate_preparation_notification(
    *,
    notifier: Any,
    preparation: dict[str, Any],
    timeout_seconds: float,
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
            timeout=timeout_seconds,
        )
    except Exception as exc:
        logger.warning("Daily candidate preparation notification failed", exc_info=True)
        return {
            "status": "failed",
            "sent": False,
            "error_type": type(exc).__name__,
        }
    return {"status": "sent", "sent": True}


def record_daily_candidate_preparation_alert(
    *,
    db: Any,
    run_date: str,
    preparation: dict[str, Any] | None,
    error_type: str | None,
) -> dict[str, Any]:
    writer = getattr(db, "upsert_automation_alert_sync", None)
    if not callable(writer):
        return {"status": "alert_store_unavailable", "recorded": False}
    value = object_dict(preparation)
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


async def run_claimed_background_attempt(
    *,
    db: Any,
    service: Any,
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
        operator_alert = record_daily_candidate_background_alert(
            db=db,
            run_date=run_date,
            outcome="interrupted_fail_closed",
            result=None,
            error_type="CancelledError",
        )
        finish_background_attempt(
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
        operator_alert = record_daily_candidate_background_alert(
            db=db,
            run_date=run_date,
            outcome="failed_closed",
            result=None,
            error_type=type(exc).__name__,
        )
        finish_background_attempt(
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
        operator_alert = record_daily_candidate_background_alert(
            db=db,
            run_date=run_date,
            outcome="failed_closed",
            result=None,
            error_type=error_type,
        )
        finish_background_attempt(
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
        notification = object_dict(result.get("notification")) or {
            "status": "notifier_unavailable",
            "sent": False,
        }
    operator_alert = record_daily_candidate_background_alert(
        db=db,
        run_date=run_date,
        outcome=decision_outcome,
        result=result,
        error_type=None,
    )
    finish_background_attempt(
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
            "manual_ticket_candidate_count": count(
                result.get("manual_ticket_candidate_count")
            ),
            "notification": notification,
            "operator_alert": operator_alert,
        },
        status="completed",
        source_ref=str(result.get("run_id") or "") or None,
    )


def record_daily_candidate_background_alert(
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
    payload = object_dict(result)
    no_action_reasons = [
        str(item) for item in payload.get("no_action_reasons") or [] if str(item)
    ]
    normalized_outcome = str(outcome or "failed_closed")
    manual_ticket_count = count(payload.get("manual_ticket_candidate_count"))
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


def finish_background_attempt(
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
