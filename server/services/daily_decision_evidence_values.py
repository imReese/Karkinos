"""Shared value normalization for daily decision evidence."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE,
    DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE,
    SHANGHAI_TZ,
)


def policy_allows_paper_shadow(status: dict[str, Any]) -> bool:
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


def plan_date(
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> str:
    return str(
        trading_plan.get("plan_date")
        or decision_payload.get("decision_date")
        or datetime.now().date().isoformat()
    )


def candidate_count(
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> int:
    summary = object_dict(decision_payload.get("summary"))
    return count(
        summary.get("candidate_count"),
        trading_plan.get("candidate_pool_count"),
    )


def daily_candidate_asset_scope_blockers(
    *,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for index, candidate in enumerate(object_list(decision_payload.get("candidates"))):
        if str(candidate.get("asset_class") or "").strip().lower() != "stock":
            blockers.append(
                f"candidate_{index}:daily_candidate_asset_class_outside_strategy_scope"
            )
    for index, intent in enumerate(object_list(trading_plan.get("order_intents"))):
        if str(intent.get("asset_class") or "").strip().lower() != "stock":
            blockers.append(
                f"order_intent_{index}:asset_class_outside_daily_candidate_scope"
            )
    return list(dict.fromkeys(blockers))


def finite_float(value: Any) -> float | None:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def positive_float(value: Any) -> float | None:
    normalized = finite_float(value)
    return normalized if normalized is not None and normalized > 0 else None


def single_ref(refs: list[str], prefix: str) -> str | None:
    matches = [ref for ref in refs if ref.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def is_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def aware_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def shanghai_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(SHANGHAI_TZ).date().isoformat()


def in_daily_candidate_decision_window(
    value: datetime | None,
    *,
    plan_date: str,
) -> bool:
    if value is None:
        return False
    shanghai_value = value.astimezone(SHANGHAI_TZ)
    minute_of_day = shanghai_value.hour * 60 + shanghai_value.minute
    return bool(
        shanghai_value.date().isoformat() == plan_date
        and DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE
        <= minute_of_day
        < DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE
    )


def positive_int(value: Any) -> int | None:
    parsed = nonnegative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def nonnegative_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def risk_summary(
    result: dict[str, Any] | None,
    decision_payload: dict[str, Any],
) -> dict[str, Any]:
    payload = object_dict(result)
    decision_summary = object_dict(decision_payload.get("summary"))
    audit = object_dict(decision_summary.get("audit"))
    candidates = object_list(decision_payload.get("candidates"))
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
    current_checked_count = count(audit.get("risk_checked_count"))
    if not current_checked_count:
        current_checked_count = current_passed_count + current_blocked_count
    error = str(payload.get("error") or "").strip()
    return {
        "status": payload.get("status") or "not_run",
        "candidate_count": count(
            decision_summary.get("candidate_count"),
            payload.get("candidate_count"),
        ),
        "checked_count": current_checked_count,
        "passed_count": current_passed_count,
        "blocked_count": current_blocked_count,
        "newly_processed_count": count(payload.get("processed_count")),
        "newly_passed_count": count(payload.get("passed_count")),
        "newly_blocked_count": count(payload.get("blocked_count")),
        "skipped_count": count(payload.get("skipped_count")),
        "risk_decision_writes_performed": bool(
            payload.get("risk_decision_writes_performed", False)
        ),
        "blockers": object_list(payload.get("blockers")),
        "error_type": str(payload.get("error_type") or "").strip() or None,
        "error_fingerprint": (
            hashlib.sha256(error.encode("utf-8")).hexdigest() if error else None
        ),
    }


def paper_shadow_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = object_dict(result)
    return {
        "status": payload.get("status") or "not_run",
        "run_id": payload.get("run_id"),
        "input_fingerprint": payload.get("input_fingerprint"),
        "order_intent_count": count(payload.get("order_intent_count")),
        "simulated_order_count": count(payload.get("simulated_order_count")),
        "simulated_fill_count": count(payload.get("simulated_fill_count")),
        "divergence_status": payload.get("divergence_status"),
        "next_manual_review_step": payload.get("next_manual_review_step"),
    }


def latest_paper_shadow_run(db: Any, *, plan_date: str) -> dict[str, Any] | None:
    reader = getattr(db, "latest_paper_shadow_run_sync", None)
    if not callable(reader):
        return None
    return reader(plan_date=plan_date)


def is_new_paper_shadow_evidence(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> bool:
    if previous is None:
        return True
    return str(previous.get("input_fingerprint") or "") != str(
        current.get("input_fingerprint") or ""
    )


def object_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def json_object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return object_list(value)


def count(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            continue
    return 0
