"""Audited automatic ingestion and official verification of market calendars."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from data.market_calendar import (
    MarketCalendarSnapshot,
    OfficialMarketCalendarVerification,
    OfficialMarketHolidayNotice,
    SseOfficialHolidayNoticeProvider,
    build_market_calendar_provider,
    verify_official_market_calendar,
)
from data.source_policy import MarketDataUseCase
from data.source_routing import configured_legacy_provider_names
from server.contracts.jobs import JobLease
from server.contracts.market_calendar import (
    MarketCalendarAutomationPublication,
    MarketCalendarVerificationCommand,
)
from server.services.market_hours import get_shanghai_now

logger = logging.getLogger(__name__)

MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION = "karkinos.market_calendar_automation.v1"
MARKET_CALENDAR_AUTOMATION_RUN_TYPE = "market_calendar_sync"
_TERMINAL_STATUSES = frozenset({"completed", "needs_review"})


def market_calendar_automation_years(now: datetime) -> tuple[int, ...]:
    """Return the current year, plus next year once December begins."""
    current = get_shanghai_now(now)
    if current.month == 12:
        return (current.year, current.year + 1)
    return (current.year,)


class MarketCalendarAutomationService:
    """Refresh provider dates, verify them against SSE, then persist atomically."""

    def __init__(
        self,
        *,
        db: Any,
        config: Any,
        provider_factory: Callable[..., Any] = build_market_calendar_provider,
        official_notice_provider: Any | None = None,
        job_lease: JobLease | None = None,
    ) -> None:
        self._db = db
        self._job_lease = job_lease
        self._config = config
        self._provider_factory = provider_factory
        self._official_notice_provider = (
            official_notice_provider or SseOfficialHolidayNoticeProvider()
        )

    def run_due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = get_shanghai_now(now)
        return [
            self._run_year(year=year, now=current)
            for year in market_calendar_automation_years(current)
        ]

    def sync_year(self, year: int, *, now: datetime | None = None) -> dict[str, Any]:
        """为明确的数据准备请求补齐指定年份，复用同一核验和发布流程。"""
        current = get_shanghai_now(now)
        if isinstance(year, bool) or not 1990 <= year <= current.year + 1:
            raise ValueError("market_calendar_year_out_of_range")
        return self._run_year(year=year, now=current)

    def _run_year(self, *, year: int, now: datetime) -> dict[str, Any]:
        run_date = now.date().isoformat()
        run_id = f"market_calendar_sync:SSE:{year}:{run_date}"
        existing_run = self._db.get_automation_run_sync(run_id)
        if existing_run and str(existing_run.get("status")) in _TERMINAL_STATUSES:
            return existing_run

        candidates = configured_legacy_provider_names(
            self._config, MarketDataUseCase.MARKET_CALENDAR
        )
        failures = self._source_failures(existing_run, run_date=run_date, now=now)
        available_candidates = [
            name for name in candidates if not _cooling_down(failures.get(name), now)
        ]
        base_payload = {
            "schema_version": MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION,
            "trigger": "server_background_task",
            "exchange": "SSE",
            "year": year,
            "provider": candidates[0] if candidates else None,
            "attempt": _next_attempt(existing_run),
            "read_endpoints_contact_providers": False,
            "changes_account_truth": False,
            "changes_execution_authority": False,
        }
        if not available_candidates or _cooling_down(
            failures.get("sse_official_notice"), now
        ):
            if existing_run:
                previous_payload = _run_payload(existing_run)
                if previous_payload.get("source_failures") == list(failures.values()):
                    return existing_run
                base_payload["attempt"] = previous_payload.get("attempt") or 1
            return self._record_failure(
                run_id, run_date, now, base_payload, failures, candidates
            )
        try:
            notice = self._official_notice_provider.fetch_notice(year=year)
        except Exception as exc:
            failures["sse_official_notice"] = _source_failure(
                "sse_official_notice",
                exc,
                now=now,
                previous=failures.get("sse_official_notice"),
            )
            logger.warning("Official SSE calendar notice failed: %s", exc)
            return self._record_failure(
                run_id, run_date, now, base_payload, failures, candidates
            )
        first_mismatch = None
        for provider_name in available_candidates:
            try:
                provider = self._provider_factory(
                    provider_name,
                    tushare_token=getattr(self._config, "tushare_token", ""),
                )
                snapshot = provider.fetch_snapshot(exchange="SSE", year=year)
                verification = verify_official_market_calendar(snapshot, notice)
            except Exception as exc:
                failures[provider_name] = _source_failure(
                    provider_name, exc, now=now, previous=failures.get(provider_name)
                )
                logger.warning(
                    "Market calendar source %s failed for SSE %d: %s",
                    provider_name,
                    year,
                    exc,
                )
                # Save the cooldown before trying another source, so a restart
                # during fallback cannot immediately repeat a rejected request.
                self._record_failure(
                    run_id, run_date, now, base_payload, failures, candidates
                )
                continue
            if verification.verified:
                return self._publish_snapshot(
                    run_id=run_id,
                    run_date=run_date,
                    now=now,
                    snapshot=snapshot,
                    notice=notice,
                    verification=verification,
                    payload={
                        **base_payload,
                        "provider": provider_name,
                        "source_failures": list(failures.values()),
                    },
                )
            failures[provider_name] = {
                "provider": provider_name,
                "kind": "verification_mismatch",
                "attempts": 1,
                "retry_after": _next_day(now).isoformat(),
                "error": {
                    "type": "OfficialCalendarMismatch",
                    "message": "; ".join(verification.issues),
                },
            }
            if first_mismatch is None:
                first_mismatch = (provider_name, snapshot, verification)
            self._record_failure(
                run_id, run_date, now, base_payload, failures, candidates
            )

        failed_run = self._record_failure(
            run_id, run_date, now, base_payload, failures, candidates
        )
        if first_mismatch is not None and not _run_payload(failed_run)["retryable"]:
            provider_name, snapshot, verification = first_mismatch
            return self._publish_snapshot(
                run_id=run_id,
                run_date=run_date,
                now=now,
                snapshot=snapshot,
                notice=notice,
                verification=verification,
                payload={
                    **base_payload,
                    "provider": provider_name,
                    "source_failures": list(failures.values()),
                },
            )
        return failed_run

    def _source_failures(
        self, existing_run: dict[str, Any] | None, *, run_date: str, now: datetime
    ) -> dict[str, dict[str, Any]]:
        failures = {
            row["provider"]: row for row in _run_source_failures(existing_run, now)
        }
        # Quotas and authentication apply to a source, not a calendar year.
        # A same-day next-year or explicit historical request shares that limit.
        for run in self._db.list_automation_runs_sync(
            run_type=MARKET_CALENDAR_AUTOMATION_RUN_TYPE,
            run_date=run_date,
            limit=now.year - 1988,
        ):
            for failure in _run_source_failures(run, now):
                if failure.get("kind") in {
                    "rate_limited",
                    "access_denied",
                } and _cooling_down(failure, now):
                    failures[failure["provider"]] = failure
        return failures

    def _record_failure(
        self,
        run_id: str,
        run_date: str,
        now: datetime,
        payload: dict[str, Any],
        failures: dict[str, dict[str, Any]],
        candidates: tuple[str, ...],
    ) -> dict[str, Any]:
        official_failure = failures.get("sse_official_notice")
        relevant = (
            [official_failure]
            if _cooling_down(official_failure, now)
            else [failures[name] for name in candidates if name in failures]
        )
        retry_after = min(
            (str(row["retry_after"]) for row in relevant),
            default=_next_day(now).isoformat(),
        )
        return self._record_run(
            run_id=run_id,
            run_date=run_date,
            status="failed",
            now=now,
            source_ref=None,
            payload={
                **payload,
                "source_failures": list(failures.values()),
                "error": relevant[-1]["error"]
                if relevant
                else {
                    "type": "MarketSourceRoutingError",
                    "message": "market_calendar_source_unavailable",
                },
                "retry_after": retry_after,
                "retryable": datetime.fromisoformat(retry_after).date() == now.date(),
                "persisted": False,
            },
        )

    def _publish_snapshot(
        self,
        *,
        run_id: str,
        run_date: str,
        now: datetime,
        snapshot: MarketCalendarSnapshot,
        notice: OfficialMarketHolidayNotice,
        verification: OfficialMarketCalendarVerification,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        year = int(payload["year"])
        existing_snapshot = self._db.get_market_calendar_snapshot_sync(
            exchange="SSE", year=year
        )
        persisted = verification.verified or (
            existing_snapshot is None
            and snapshot.exchange == "SSE"
            and snapshot.year == year
        )
        command = None
        if persisted:
            command = MarketCalendarVerificationCommand(
                exchange="SSE",
                year=year,
                source_fingerprint=snapshot.source_fingerprint,
                verification_status=verification.status,
                official_source_url=notice.source_url,
                official_source_fingerprint=notice.source_fingerprint,
                verified_by="automatic-sse-cross-check"
                if verification.verified
                else None,
                day_labels=dict(notice.day_labels) if verification.verified else {},
                review_notes="; ".join(verification.issues) or None,
            )
        run = self._run_record(
            run_id=run_id,
            run_date=run_date,
            status="completed" if verification.verified else "needs_review",
            now=now,
            source_ref=notice.source_url,
            payload={
                **payload,
                "provider_source_fingerprint": snapshot.source_fingerprint,
                "official_source_fingerprint": notice.source_fingerprint,
                "official_verification_status": verification.status,
                "verification_issues": list(verification.issues),
                "retryable": False,
                "persisted": persisted,
            },
        )
        return self._db.publish_market_calendar_automation_sync(
            MarketCalendarAutomationPublication(
                run=run,
                snapshot=snapshot.to_payload() if persisted else None,
                verification=command,
                job_lease=self._job_lease,
            )
        )["run"]

    def _record_run(
        self,
        *,
        run_id: str,
        run_date: str,
        status: str,
        now: datetime,
        source_ref: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        run = self._run_record(
            run_id=run_id,
            run_date=run_date,
            status=status,
            now=now,
            source_ref=source_ref,
            payload=payload,
        )
        if self._job_lease is not None:
            return self._db.publish_market_calendar_automation_sync(
                MarketCalendarAutomationPublication(run=run, job_lease=self._job_lease)
            )["run"]
        return self._db.upsert_automation_run_sync(run)

    @staticmethod
    def _run_record(
        *,
        run_id: str,
        run_date: str,
        status: str,
        now: datetime,
        source_ref: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "run_type": MARKET_CALENDAR_AUTOMATION_RUN_TYPE,
            "run_date": run_date,
            "status": status,
            "execution_mode": "market_data_ingestion",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "source_ref": source_ref,
            "payload": payload,
        }


def _next_attempt(existing_run: dict[str, Any] | None) -> int:
    payload = _run_payload(existing_run)
    try:
        return max(int(payload.get("attempt") or 0) + 1, 1)
    except (TypeError, ValueError):
        return 1


def _run_payload(run: dict[str, Any] | None) -> dict[str, Any]:
    try:
        payload = json.loads(str((run or {}).get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _next_day(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _run_source_failures(
    run: dict[str, Any] | None, now: datetime
) -> list[dict[str, Any]]:
    payload = _run_payload(run)
    recorded = payload.get("source_failures")
    if isinstance(recorded, list):
        return [
            row
            for row in recorded
            if isinstance(row, dict) and isinstance(row.get("provider"), str)
        ]
    # Upgrade today's old audit shape without spending another request on a
    # source that has already explicitly rejected it for quota or credentials.
    error = payload.get("error")
    provider = payload.get("provider")
    if (
        (run or {}).get("status") == "failed"
        and isinstance(error, dict)
        and isinstance(provider, str)
    ):
        failure = _source_failure(
            provider,
            RuntimeError(str(error.get("message") or "")),
            now=now,
            previous=None,
        )
        if failure["kind"] in {"rate_limited", "access_denied"}:
            failure["error"] = error
            return [failure]
    return []


def _cooling_down(failure: dict[str, Any] | None, now: datetime) -> bool:
    if failure is None:
        return False
    try:
        deadline = datetime.fromisoformat(str(failure["retry_after"]))
        return deadline.tzinfo is not None and now < deadline
    except (KeyError, TypeError, ValueError):
        return False


def _source_failure(
    provider: str,
    exc: Exception,
    *,
    now: datetime,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    message = str(exc).lower()
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "status_code", None)
    if status_code == 429 or any(
        marker in message
        for marker in (
            "rate limit",
            "too many requests",
            "quota",
            "每分钟最多",
            "每小时最多",
            "每天最多",
            "每周最多",
            "每月最多",
            "访问频率",
            "限频",
            "限流",
        )
    ):
        kind = "rate_limited"
    elif status_code in {401, 403} or any(
        marker in message
        for marker in (
            "访问权限",
            "没有权限",
            "无权限",
            "该接口的权限",
            "permission denied",
            "access denied",
            "invalid token",
            "token不对",
            "token错误",
        )
    ):
        kind = "access_denied"
    elif isinstance(exc, ValueError):
        kind = "invalid_data"
    else:
        kind = "transient"
    attempts = int((previous or {}).get("attempts") or 0) + 1
    retry_after = (
        min(now + timedelta(hours=1), _next_day(now))
        if kind == "transient" and attempts < 3
        else _next_day(now)
    )
    return {
        "provider": provider,
        "kind": kind,
        "attempts": attempts,
        "retry_after": retry_after.isoformat(),
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }
