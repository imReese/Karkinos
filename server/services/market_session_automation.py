"""Controlled market-session automation runner."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from server.services.automation_control import AutomationControlService
from server.services.market_hours import get_shanghai_now, is_cn_trading_session
from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan

MARKET_SESSION_AUTOMATION_SCHEMA_VERSION = "karkinos.market_session_automation.v1"
MARKET_SESSION_LIMITATION = (
    "Market session check uses weekday and A-share intraday hours; official "
    "holiday calendar verification is not yet enforced here."
)


class MarketSessionAutomationService:
    """Run one auditable market-session automation step."""

    def __init__(self, *, db: Any, trading_controls: Any | None) -> None:
        self._db = db
        self._trading_controls = trading_controls
        self._automation = AutomationControlService(
            db=db,
            trading_controls=trading_controls,
        )

    def run_session(
        self,
        *,
        trading_plan: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = get_shanghai_now(now)
        run_date = str(trading_plan.get("plan_date") or current.date().isoformat())
        base_payload = self._base_payload(
            trading_plan=trading_plan,
            run_date=run_date,
            now=current,
        )
        kill_switch = self._kill_switch_snapshot()
        kill_switch_enabled = bool(
            getattr(kill_switch, "kill_switch_enabled", False)
            if kill_switch is not None
            else False
        )
        if kill_switch_enabled:
            return self._record_result(
                run_date=run_date,
                status="blocked_by_kill_switch",
                now=current,
                payload={
                    **base_payload,
                    "kill_switch_reason": getattr(kill_switch, "reason", ""),
                },
            )

        if not is_cn_trading_session(current):
            return self._record_result(
                run_date=run_date,
                status="skipped_non_trading_session",
                now=current,
                payload={
                    **base_payload,
                    "session_time": current.isoformat(),
                },
            )

        try:
            paper_shadow_run = run_paper_shadow_from_trading_plan(
                db=self._db,
                trading_plan=trading_plan,
                generated_at=trading_plan.get("generated_at") or current.isoformat(),
            )
        except Exception as exc:
            return self._record_result(
                run_date=run_date,
                status="paper_shadow_failed",
                now=current,
                payload={
                    **base_payload,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "retry_state": _retry_state(retryable=True),
                    "limitations": [
                        "Paper/shadow run failed; no broker order was submitted.",
                    ],
                },
            )

        self._automation.record_paper_shadow_run(
            run_date=run_date,
            source_ref=paper_shadow_run.get("run_id"),
            paper_shadow_run=paper_shadow_run,
        )
        return self._record_result(
            run_date=run_date,
            status="paper_shadow_completed",
            now=current,
            payload={
                **base_payload,
                "paper_shadow_run_id": paper_shadow_run.get("run_id"),
                "paper_shadow_status": paper_shadow_run.get("status"),
            },
            paper_shadow_run=paper_shadow_run,
        )

    def _record_result(
        self,
        *,
        run_date: str,
        status: str,
        now: datetime,
        payload: dict[str, Any],
        paper_shadow_run: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = str(
            payload.get("idempotency_key")
            or f"market_session:{run_date}:{now.strftime('%H%M%S')}"
        )
        payload_body = dict(payload)
        payload_body["retry_state"] = self._retry_state_for_run(
            run_id=run_id,
            retry_state=payload_body.get("retry_state"),
        )
        limitations = _limitations(payload_body.pop("limitations", []))
        run = self._db.upsert_automation_run_sync(
            {
                "run_id": run_id,
                "run_type": "market_session",
                "run_date": run_date,
                "status": status,
                "execution_mode": "paper_shadow",
                "started_at": now.isoformat(),
                "finished_at": now.isoformat(),
                "source_ref": payload.get("paper_shadow_run_id"),
                "payload": {
                    "schema_version": MARKET_SESSION_AUTOMATION_SCHEMA_VERSION,
                    **payload_body,
                    "broker_submission_enabled": False,
                    "does_not_submit_broker_order": True,
                    "limitations": limitations,
                },
            }
        )
        return {
            "schema_version": MARKET_SESSION_AUTOMATION_SCHEMA_VERSION,
            "run": run,
            "run_id": run["run_id"],
            "status": status,
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "kill_switch_enabled": status == "blocked_by_kill_switch",
            "paper_shadow_run": paper_shadow_run,
            "limitations": limitations,
        }

    def _retry_state_for_run(
        self,
        *,
        run_id: str,
        retry_state: Any,
    ) -> dict[str, Any]:
        current = _dict(retry_state)
        if not current:
            current = _retry_state(retryable=False)
        if not bool(current.get("retryable")):
            return current

        previous = _existing_retry_state(self._db, run_id)
        previous_attempt = _count_value(previous.get("attempt")) if previous else 0
        attempt = max(_count_value(current.get("attempt")), previous_attempt + 1)
        merged = {
            **current,
            "attempt": attempt,
            "max_attempts": max(_count_value(current.get("max_attempts")), attempt),
        }
        if previous_attempt:
            merged["previous_attempts"] = previous_attempt
        return merged

    def _kill_switch_snapshot(self) -> Any | None:
        if self._trading_controls is None:
            return None
        snapshot = getattr(self._trading_controls, "snapshot", None)
        return snapshot() if callable(snapshot) else None

    def _base_payload(
        self,
        *,
        trading_plan: dict[str, Any],
        run_date: str,
        now: datetime,
    ) -> dict[str, Any]:
        input_fingerprint = _input_fingerprint(trading_plan)
        return {
            "trigger": "market_session",
            "session_time": now.isoformat(),
            "trading_plan_schema_version": trading_plan.get("schema_version"),
            "input_snapshot": _input_snapshot(
                trading_plan=trading_plan,
                run_date=run_date,
            ),
            "input_fingerprint": input_fingerprint,
            "idempotency_key": f"market_session:{run_date}:{input_fingerprint[:12]}",
            "retry_state": _retry_state(retryable=False),
        }


def _input_snapshot(
    *,
    trading_plan: dict[str, Any],
    run_date: str,
) -> dict[str, Any]:
    order_intents = trading_plan.get("order_intents")
    order_intent_count = len(order_intents) if isinstance(order_intents, list) else 0
    return {
        "schema_version": trading_plan.get("schema_version"),
        "plan_date": str(trading_plan.get("plan_date") or run_date),
        "generated_at": trading_plan.get("generated_at"),
        "order_intent_count": order_intent_count,
        "manual_ready_count": _count_value(trading_plan.get("manual_ready_count")),
        "blocked_count": _count_value(trading_plan.get("blocked_count")),
    }


def _input_fingerprint(trading_plan: dict[str, Any]) -> str:
    encoded = json.dumps(
        trading_plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _retry_state(*, retryable: bool) -> dict[str, Any]:
    return {
        "attempt": 1,
        "max_attempts": 1,
        "retryable": retryable,
    }


def _existing_retry_state(db: Any, run_id: str) -> dict[str, Any]:
    getter = getattr(db, "get_automation_run_sync", None)
    if not callable(getter):
        return {}
    existing = getter(run_id)
    if not existing:
        return {}
    try:
        payload = json.loads(str(existing.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return {}
    return _dict(payload.get("retry_state"))


def _limitations(additional: Any) -> list[str]:
    limitations = [MARKET_SESSION_LIMITATION]
    if isinstance(additional, list):
        limitations.extend(str(item) for item in additional if item)
    elif additional:
        limitations.append(str(additional))
    return limitations


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _count_value(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
