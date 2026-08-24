"""Read-only scheduling projections for daily candidate automation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION,
    DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE,
    DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE,
    DAILY_CANDIDATE_NEXT_REVIEWED_WINDOW_SCHEMA_VERSION,
    DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
    DAILY_CANDIDATE_PREPARATION_WINDOW_START_MINUTE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    SHANGHAI_TZ,
    VERIFIED_CALENDAR_STATUSES,
)
from server.services.daily_decision_evidence_values import json_object_list


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
        return build_background_schedule_result(
            status="blocked_clock_not_timezone_aware",
            evaluated_at=None,
            run_date=None,
            due=False,
            blockers=["background_schedule_clock_not_timezone_aware"],
        )

    shanghai_now = evaluated_at.astimezone(SHANGHAI_TZ)
    run_date = shanghai_now.date().isoformat()
    evaluated_at_text = evaluated_at.isoformat()
    calendar_reader = getattr(db, "get_market_calendar_snapshot_sync", None)
    calendar = (
        calendar_reader(exchange="SSE", year=shanghai_now.year)
        if callable(calendar_reader)
        else None
    )
    if not isinstance(calendar, dict):
        return build_background_schedule_result(
            status="blocked_market_calendar_missing",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=["market_calendar_snapshot_missing"],
        )
    if str(calendar.get("official_verification_status") or "").lower() not in (
        VERIFIED_CALENDAR_STATUSES
    ):
        return build_background_schedule_result(
            status="blocked_market_calendar_not_verified",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=["market_calendar_not_officially_verified"],
        )
    days = json_object_list(calendar.get("days_json"))
    calendar_day = next(
        (item for item in days if str(item.get("date") or "") == run_date),
        None,
    )
    if calendar_day is None:
        return build_background_schedule_result(
            status="blocked_market_calendar_day_missing",
            evaluated_at=evaluated_at_text,
            run_date=run_date,
            due=False,
            blockers=["market_calendar_day_missing"],
        )
    if calendar_day.get("is_trading_day") is not True:
        next_reviewed_window = build_next_verified_trading_window(
            calendar_reader=calendar_reader,
            shanghai_now=shanghai_now,
            current_days=days,
            include_current_date=False,
        )
        return build_background_schedule_result(
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
        next_reviewed_window = build_next_verified_trading_window(
            calendar_reader=calendar_reader,
            shanghai_now=shanghai_now,
            current_days=days,
            include_current_date=False,
        )
        return build_background_schedule_result(
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
        next_reviewed_window = build_next_verified_trading_window(
            calendar_reader=calendar_reader,
            shanghai_now=shanghai_now,
            current_days=days,
            include_current_date=False,
        )
        return build_background_schedule_result(
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
    next_reviewed_window = build_next_verified_trading_window(
        calendar_reader=calendar_reader,
        shanghai_now=shanghai_now,
        current_days=days,
        include_current_date=status != "missed_decision_window",
    )
    return build_background_schedule_result(
        status=status,
        evaluated_at=evaluated_at_text,
        run_date=run_date,
        due=status == "due",
        blockers=blockers,
        next_reviewed_window=next_reviewed_window,
        preparation_check_due=preparation_check_due,
        preparation_check_existing_run_id=preparation_check_existing_run_id,
    )


def build_background_schedule_result(
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
            else unavailable_next_reviewed_window(
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


def build_next_verified_trading_window(
    *,
    calendar_reader: Any,
    shanghai_now: datetime,
    current_days: list[dict[str, Any]],
    include_current_date: bool,
) -> dict[str, Any]:
    run_date = shanghai_now.date().isoformat()
    candidate = next_trading_day(
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
            in VERIFIED_CALENDAR_STATUSES
        ):
            candidate = next_trading_day(
                days=json_object_list(next_calendar.get("days_json")),
                run_date=run_date,
                include_current_date=False,
            )
    if candidate is None:
        return unavailable_next_reviewed_window(
            "next_verified_trading_day_not_available"
        )

    market_date = datetime.strptime(candidate, "%Y-%m-%d").date()
    window_start = datetime(
        market_date.year,
        market_date.month,
        market_date.day,
        DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE // 60,
        DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE % 60,
        tzinfo=SHANGHAI_TZ,
    )
    window_end = datetime(
        market_date.year,
        market_date.month,
        market_date.day,
        DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE // 60,
        DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE % 60,
        tzinfo=SHANGHAI_TZ,
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


def next_trading_day(
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


def unavailable_next_reviewed_window(blocker: str) -> dict[str, Any]:
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
