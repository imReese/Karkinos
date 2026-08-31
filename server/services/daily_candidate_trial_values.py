"""Canonical value normalization for daily-candidate trial evidence."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE,
    DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE,
)

SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


def trial_binding(
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


def latest_complete_trial_binding(
    evaluated_days: list[dict[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    for day in reversed(evaluated_days):
        binding = trial_binding(day)
        if binding is not None:
            return binding
    return None


def current_trial_epoch_days(
    *,
    evaluated_days: list[dict[str, Any]],
    active_binding: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None,
) -> list[dict[str, Any]]:
    if active_binding is None:
        return []
    boundary_index = -1
    for index, day in enumerate(evaluated_days):
        binding = trial_binding(day)
        if binding is not None and binding != active_binding:
            boundary_index = index
    return evaluated_days[boundary_index + 1 :]


def excluded_day_result(*, run_date: str, blockers: list[str]) -> dict[str, Any]:
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


def event_payload(row: dict[str, Any]) -> dict[str, Any]:
    return object_value(row.get("payload_json"))


def object_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def review_event_response(
    row: dict[str, Any],
    *,
    reused: bool,
) -> dict[str, Any]:
    payload = event_payload(row)
    return {
        **payload,
        "recorded_at": row.get("timestamp"),
        "event_id": row.get("id"),
        "reused": reused,
    }


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def shanghai_date(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(SHANGHAI_TIMEZONE).date().isoformat()


def aware_iso(value: Any) -> str | None:
    parsed = aware_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def aware_datetime(value: Any) -> datetime | None:
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


def in_daily_candidate_decision_window(value: Any, *, run_date: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    shanghai_value = parsed.astimezone(SHANGHAI_TIMEZONE)
    minute_of_day = shanghai_value.hour * 60 + shanghai_value.minute
    return bool(
        shanghai_value.date().isoformat() == run_date
        and DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE
        <= minute_of_day
        < DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE
    )


def elapsed_seconds(*, later: Any, earlier: Any) -> int | None:
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


def nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    normalized = str(value or "").strip()
    if not normalized.isdigit():
        return None
    parsed = int(normalized)
    return parsed if parsed >= 0 else None


def is_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def positive_float(value: Any) -> float | None:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) and normalized > 0 else None
