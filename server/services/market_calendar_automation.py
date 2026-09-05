"""Audited automatic ingestion and official verification of market calendars."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from data.market_calendar import (
    SseOfficialHolidayNoticeProvider,
    build_market_calendar_provider,
    verify_official_market_calendar,
)
from server.contracts.jobs import JobLease
from server.contracts.market_calendar import (
    MarketCalendarAutomationPublication,
    MarketCalendarVerificationCommand,
)
from server.release_activation import wait_for_release_activation
from server.services.market_hours import get_shanghai_now

logger = logging.getLogger(__name__)

MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION = "karkinos.market_calendar_automation.v1"
MARKET_CALENDAR_AUTOMATION_RUN_TYPE = "market_calendar_sync"
MARKET_CALENDAR_AUTOMATION_INTERVAL_SECONDS = 60 * 60
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

    def _run_year(self, *, year: int, now: datetime) -> dict[str, Any]:
        run_date = now.date().isoformat()
        run_id = f"market_calendar_sync:SSE:{year}:{run_date}"
        existing_run = self._db.get_automation_run_sync(run_id)
        if existing_run and str(existing_run.get("status")) in _TERMINAL_STATUSES:
            return existing_run

        attempt = _next_attempt(existing_run)
        base_payload = {
            "schema_version": MARKET_CALENDAR_AUTOMATION_SCHEMA_VERSION,
            "trigger": "server_background_task",
            "exchange": "SSE",
            "year": year,
            "provider": str(getattr(self._config, "data_source", "akshare")),
            "attempt": attempt,
            "read_endpoints_contact_providers": False,
            "changes_account_truth": False,
            "changes_execution_authority": False,
        }
        try:
            provider = self._provider_factory(
                base_payload["provider"],
                tushare_token=getattr(self._config, "tushare_token", ""),
            )
            snapshot = provider.fetch_snapshot(exchange="SSE", year=year)
            notice = self._official_notice_provider.fetch_notice(year=year)
            verification = verify_official_market_calendar(snapshot, notice)

            if verification.verified:
                snapshot_payload = snapshot.to_payload()
                verification_command = MarketCalendarVerificationCommand(
                    exchange="SSE",
                    year=year,
                    source_fingerprint=snapshot.source_fingerprint,
                    verification_status="verified",
                    official_source_url=notice.source_url,
                    official_source_fingerprint=notice.source_fingerprint,
                    verified_by="automatic-sse-cross-check",
                    day_labels=dict(notice.day_labels),
                )
                status = "completed"
                persisted = True
            else:
                # Do not replace a previously usable snapshot with evidence that
                # failed the official cross-check. A first-time mismatch is kept
                # explicitly non-authoritative so operators can inspect it.
                existing_snapshot = self._db.get_market_calendar_snapshot_sync(
                    exchange="SSE", year=year
                )
                if existing_snapshot is None:
                    snapshot_payload = snapshot.to_payload()
                    verification_command = MarketCalendarVerificationCommand(
                        exchange="SSE",
                        year=year,
                        source_fingerprint=snapshot.source_fingerprint,
                        verification_status="needs_review",
                        official_source_url=notice.source_url,
                        official_source_fingerprint=notice.source_fingerprint,
                        review_notes="; ".join(verification.issues) or None,
                    )
                else:
                    snapshot_payload = None
                    verification_command = None
                status = "needs_review"
                persisted = existing_snapshot is None

            run = self._run_record(
                run_id=run_id,
                run_date=run_date,
                status=status,
                now=now,
                source_ref=notice.source_url,
                payload={
                    **base_payload,
                    "provider_source_fingerprint": snapshot.source_fingerprint,
                    "official_source_fingerprint": notice.source_fingerprint,
                    "official_verification_status": verification.status,
                    "verification_issues": list(verification.issues),
                    "persisted": persisted,
                },
            )
            publication = self._db.publish_market_calendar_automation_sync(
                MarketCalendarAutomationPublication(
                    run=run,
                    snapshot=snapshot_payload,
                    verification=verification_command,
                    job_lease=self._job_lease,
                )
            )
            return publication["run"]
        except Exception as exc:
            logger.warning(
                "Automatic market calendar sync failed for SSE %d", year, exc_info=True
            )
            return self._record_run(
                run_id=run_id,
                run_date=run_date,
                status="failed",
                now=now,
                source_ref=None,
                payload={
                    **base_payload,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "retryable": True,
                    "persisted": False,
                },
            )

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


async def run_market_calendar_automation_loop(
    *,
    db: Any,
    config: Any,
    interval_seconds: float = MARKET_CALENDAR_AUTOMATION_INTERVAL_SECONDS,
) -> None:
    """Run the idempotent ingestion check now and periodically thereafter."""
    service = MarketCalendarAutomationService(db=db, config=config)
    while True:
        await wait_for_release_activation()
        try:
            await asyncio.to_thread(service.run_due)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected market calendar automation failure")
        await asyncio.sleep(interval_seconds)


def _next_attempt(existing_run: dict[str, Any] | None) -> int:
    if not existing_run:
        return 1
    try:
        payload = json.loads(str(existing_run.get("payload_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 1
    try:
        return max(int(payload.get("attempt") or 0) + 1, 1)
    except (TypeError, ValueError):
        return 1
