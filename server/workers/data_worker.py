"""Isolated data/operations worker; calendar is the first migrated provider loop."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import date, datetime, time, timezone

from data.market.contracts import MarketDataProviderDescriptor
from data.source_policy import (
    source_policy_for_config,
    verification_source_policy_for_config,
)
from server.contracts.jobs import JobRun, JobStore
from server.db import AppDatabase
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.jobs import SQLiteJobStore, job_id_for
from server.persistence.market_daily_call_budget import (
    MarketDailyProviderBudgetDeferred,
    reserve_market_daily_provider_call,
)
from server.persistence.runtime_controls import RuntimeControlRepository
from server.release_activation import (
    is_release_activation_guarded,
    wait_for_release_activation,
)
from server.services.daily_market_collection import (
    DAILY_MARKET_COLLECTION_JOB,
    DailyMarketCollectionFailure,
    DailyMarketCollectionJobRequest,
    DailyMarketCollectionService,
    collection_capture_completed_at,
)
from server.services.market_calendar_automation import MarketCalendarAutomationService
from server.services.market_calendar_dates import (
    resolve_verified_closed_trading_dates,
    resolve_verified_closed_trading_dates_in_range,
)
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.market_hours import get_shanghai_now
from server.services.research_observation_data_preparation import (
    guard_observation_data_preparation,
    observation_daily_job_grant,
    require_observation_preparation_job,
    run_research_observation_data_preparation_once,
)
from server.services.verified_daily_market_data import (
    VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
    VerifiedDailyMarketDataService,
    VerifiedDailyMarketJobRequest,
    VerifiedDailySourceResolution,
)
from server.services.verified_daily_market_jobs import (
    VERIFIED_DAILY_MARKET_JOB,
    enqueue_latest_daily_market_collection_jobs,
    supported_watchlist_instruments,
)
from server.workers.presence import run_with_presence

logger = logging.getLogger(__name__)
CALENDAR_JOB = "market_calendar_sync"


def enqueue_daily_market_calendar_job(store: JobStore, *, now: datetime) -> JobRun:
    scheduled = get_shanghai_now(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return store.enqueue(
        CALENDAR_JOB,
        {"scheduled_at": scheduled.isoformat(), "cadence": "daily"},
        now=now,
    )


def _calendar_failure_retry(results, *, now: datetime, attempt: int):
    payloads = []
    for row in results or []:
        if row.get("status") == "completed":
            continue
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            payload = {}
        payloads.append(payload if isinstance(payload, dict) else {})
    default_delay = min(60 * 2 ** (attempt - 1), 3600)
    retry_delays = []
    for payload in payloads:
        if payload.get("retryable") is False:
            continue
        delay = default_delay
        try:
            after = datetime.fromisoformat(payload.get("retry_after") or "")
            if after.tzinfo is not None and after > now:
                delay = math.ceil((after - now).total_seconds())
        except (TypeError, ValueError):
            pass
        retry_delays.append(delay)
    if retry_delays:
        return min(retry_delays), True
    return default_delay, not payloads


class WorkerExecutionAborted(RuntimeError):
    """The process must exit because an outstanding provider thread was fenced."""


class VerifiedDailyMarketJobNotCurrent(RuntimeError):
    """A queued verification no longer has current policy or calendar authority."""


def _require_current_daily_market_collection_job(
    db: AppDatabase,
    config: object,
    job: JobRun,
) -> None:
    """Recheck automatic collection scope before provider I/O and quality publication."""
    try:
        request = DailyMarketCollectionJobRequest.from_payload(job.payload)
    except (TypeError, ValueError) as exc:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_payload_invalid"
        ) from exc
    try:
        current_policy_id = source_policy_for_config(config).policy_id
    except (TypeError, ValueError) as exc:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_source_policy_stale"
        ) from exc
    if request.source_policy_id != current_policy_id:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_source_policy_stale"
        )

    read_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if not callable(read_watchlist):
        raise DailyMarketCollectionFailure(
            "daily_market_collection_watchlist_unreadable"
        )
    try:
        instruments = supported_watchlist_instruments(read_watchlist() or [])
    except Exception as exc:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_watchlist_unreadable"
        ) from exc
    if request.instrument not in instruments:
        raise DailyMarketCollectionFailure("daily_market_collection_watchlist_stale")

    blocker = _current_daily_market_calendar_blocker(
        db, request.trade_date, request.calendar_evidence_refs
    )
    if blocker is not None:
        raise DailyMarketCollectionFailure(f"daily_market_collection_{blocker}")
    if request.observation_round is not None:
        _require_current_collection_revision(db, request)


def _require_current_collection_revision(
    db: AppDatabase,
    request: DailyMarketCollectionJobRequest,
) -> None:
    """A queued second observation must retain its baseline and due session."""
    now = datetime.now(timezone.utc)
    round_value = request.observation_round
    if round_value is None:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_revision_round_missing"
        )
    next_date = date.fromisoformat(round_value.rsplit(".", 1)[-1])
    try:
        closed = resolve_verified_closed_trading_dates(db, now, lookback_days=30)
    except Exception as exc:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_revision_calendar_unreadable"
        ) from exc
    following_session = next(
        (
            following
            for current, following in zip(closed, closed[1:])
            if date.fromisoformat(current.trade_date) == request.trade_date
            and date.fromisoformat(following.trade_date) == next_date
        ),
        None,
    )
    if following_session is None:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_revision_session_stale"
        )
    base_payload = DailyMarketCollectionJobRequest(
        trade_date=request.trade_date,
        instrument=request.instrument,
        source_policy_id=request.source_policy_id,
        calendar_evidence_refs=request.calendar_evidence_refs,
    ).to_payload()
    try:
        base = SQLiteJobStore(db.path).get(
            job_id_for(DAILY_MARKET_COLLECTION_JOB, base_payload)
        )
        if base is None or base.status != "succeeded" or not base.result_ref:
            raise ValueError("base_job_not_succeeded")
        completed_at = collection_capture_completed_at(
            db.path.resolve().parent / "research",
            request=DailyMarketCollectionJobRequest.from_payload(base_payload),
            result_ref=base.result_ref,
        )
    except Exception as exc:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_revision_base_unreadable"
        ) from exc
    next_close = datetime.combine(next_date, time(16), get_shanghai_now(now).tzinfo)
    if completed_at >= next_close:
        raise DailyMarketCollectionFailure(
            "daily_market_collection_revision_base_too_late"
        )


def _require_current_verified_daily_market_job(
    db: AppDatabase,
    config: object,
    job: JobRun,
) -> None:
    """Recheck a durable request at provider entry and visible publication."""
    request = VerifiedDailyMarketJobRequest.from_payload(job.payload)
    require_observation_preparation_job(db, config, job)
    if (
        request.source_policy_id
        != verification_source_policy_for_config(config).policy_id
    ):
        raise VerifiedDailyMarketJobNotCurrent(
            "verified_daily_market_source_policy_stale"
        )
    blocker = _current_daily_market_calendar_blocker(
        db, request.trade_date, request.calendar_evidence_refs
    )
    if blocker is not None:
        raise VerifiedDailyMarketJobNotCurrent(f"verified_daily_market_{blocker}")


def _current_daily_market_calendar_blocker(
    db: AppDatabase, trade_date: date, calendar_evidence_refs: tuple[str, ...]
) -> str | None:
    """Use the same closed-session evidence check for both durable daily jobs."""
    try:
        dates = resolve_verified_closed_trading_dates_in_range(
            db,
            datetime.now(timezone.utc),
            start_date=trade_date,
            end_date=trade_date,
        )
    except ValueError:
        return "session_not_closed"
    except Exception:
        return "calendar_evidence_stale"
    if len(dates) != 1 or dates[0].trade_date != trade_date.isoformat():
        return "calendar_evidence_stale"
    current_refs = dates[0].calendar_evidence_refs
    if len(current_refs) != 1:
        return "calendar_evidence_stale"
    accepted_refs = {current_refs[0]}
    # The legacy latest-day planner included the following year's calendar when
    # it fell back to the previous year's last session at the year boundary.
    if len(calendar_evidence_refs) == 2:
        try:
            year_days = resolve_verified_closed_trading_dates_in_range(
                db,
                datetime.now(timezone.utc),
                start_date=date(trade_date.year, 1, 1),
                end_date=date(trade_date.year, 12, 31),
            )
            if not year_days or year_days[-1].trade_date != trade_date.isoformat():
                return "calendar_evidence_stale"
            following = validate_verified_market_calendar(
                db.get_market_calendar_snapshot_sync(
                    exchange="SSE", year=trade_date.year + 1
                )
            )
        except Exception:
            return "calendar_evidence_stale"
        if following.verified and following.evidence_ref is not None:
            accepted_refs.add(following.evidence_ref)
    if set(calendar_evidence_refs) != accepted_refs:
        return "calendar_evidence_stale"
    return None


async def execute_calendar_job(
    store: JobStore,
    job: JobRun,
    service,
    *,
    timeout: float = 120,
    heartbeat_interval: float = 15,
) -> None:
    execution_time = datetime.now(timezone.utc)
    scheduled = datetime.fromisoformat(job.payload["scheduled_at"])
    if job.payload.get("cadence") == "daily":
        if (
            scheduled.tzinfo is None
            or get_shanghai_now(scheduled).date()
            != get_shanghai_now(execution_time).date()
        ):
            store.fail(
                job.lease,
                now=execution_time,
                error="calendar_job_day_expired",
                retryable=False,
            )
            return
    else:
        # The normal worker never claims legacy hourly jobs. Keep direct replay
        # of their already-published receipts compatible with their original day.
        execution_time = scheduled

    async def renew():
        while True:
            await asyncio.sleep(heartbeat_interval)
            if is_release_activation_guarded():
                raise WorkerExecutionAborted("release_activation_started")
            store.heartbeat(job.lease, now=datetime.now(timezone.utc))

    loop = asyncio.get_running_loop()
    work = loop.create_future()

    def deliver(result, error):
        if not work.done():
            if error is None:
                work.set_result(result)
            else:
                work.set_exception(error)

    def run():
        try:
            result, error = (
                service.run_due(now=execution_time),
                None,
            )
        except Exception as exc:
            result, error = None, exc
        try:
            loop.call_soon_threadsafe(deliver, result, error)
        except RuntimeError:
            pass  # The owning worker has already exited.

    threading.Thread(target=run, name="calendar-job", daemon=True).start()
    heartbeat = asyncio.create_task(renew())
    try:
        done, _ = await asyncio.wait(
            {work, heartbeat}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat in done or not done:
            raise WorkerExecutionAborted("calendar_execution_deadline_or_lease_lost")
        results = work.result()
        if not results or any(row["status"] != "completed" for row in results):
            now = datetime.now(timezone.utc)
            retry_seconds, retryable = _calendar_failure_retry(
                results, now=now, attempt=job.attempt
            )
            store.fail(
                job.lease,
                now=now,
                error="calendar_evidence_not_verified",
                retry_seconds=retry_seconds,
                retryable=retryable,
            )
            return
        store.finish(
            job.lease,
            now=datetime.now(timezone.utc),
            result_ref="automation_runs:" + ",".join(row["run_id"] for row in results),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            store.fail(
                job.lease,
                now=datetime.now(timezone.utc),
                error=type(exc).__name__,
                retry_seconds=min(60 * 2 ** (job.attempt - 1), 3600),
            )
        except Exception:
            if not isinstance(exc, WorkerExecutionAborted):
                raise
        if isinstance(exc, WorkerExecutionAborted):
            raise
    finally:
        work.cancel()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat


async def execute_verified_daily_market_job(
    store: JobStore,
    job: JobRun,
    service,
    *,
    timeout: float = 180,
    heartbeat_interval: float = 15,
    source_resolution_recorder: Callable[[dict[str, object]], None] | None = None,
    request_validator: Callable[[], None] | None = None,
    before_provider_fetch: Callable[[MarketDataProviderDescriptor], None] | None = None,
    publication_guard: Callable[[Callable[[], None]], None] | None = None,
    finish_guard: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    """Run one durable verified-market job behind lease fencing."""
    await _execute_daily_market_job(
        store,
        job,
        service,
        timeout=timeout,
        heartbeat_interval=heartbeat_interval,
        result_prefix="dataset:sha256:",
        label="verified_market",
        source_resolution_recorder=source_resolution_recorder,
        request_validator=request_validator,
        before_provider_fetch=before_provider_fetch,
        publication_guard=publication_guard,
        finish_guard=finish_guard,
    )


async def execute_daily_market_collection_job(
    store: JobStore,
    job: JobRun,
    service,
    *,
    timeout: float = 180,
    heartbeat_interval: float = 15,
    request_validator: Callable[[], None] | None = None,
    before_provider_fetch: Callable[[MarketDataProviderDescriptor], None] | None = None,
) -> None:
    """Persist capture and quality without granting Dataset publication."""
    await _execute_daily_market_job(
        store,
        job,
        service,
        timeout=timeout,
        heartbeat_interval=heartbeat_interval,
        result_prefix="quality:sha256:",
        label="daily_collection",
        request_validator=request_validator,
        before_provider_fetch=before_provider_fetch,
    )


async def _execute_daily_market_job(
    store: JobStore,
    job: JobRun,
    service,
    *,
    timeout: float,
    heartbeat_interval: float,
    result_prefix: str,
    label: str,
    source_resolution_recorder: Callable[[dict[str, object]], None] | None = None,
    request_validator: Callable[[], None] | None = None,
    before_provider_fetch: Callable[[MarketDataProviderDescriptor], None] | None = None,
    publication_guard: Callable[[Callable[[], None]], None] | None = None,
    finish_guard: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    aborted = threading.Event()

    def require_running() -> None:
        if is_release_activation_guarded():
            raise WorkerExecutionAborted("release_activation_started")
        if aborted.is_set():
            raise WorkerExecutionAborted(f"{label}_execution_stopped")

    def before_fetch(descriptor: MarketDataProviderDescriptor) -> None:
        require_running()
        if before_provider_fetch is not None:
            before_provider_fetch(descriptor)

    def publish(action: Callable[[], None]) -> None:
        def checked_action():
            require_running()
            action()

        if publication_guard is not None:
            publication_guard(checked_action)
        else:
            checked_action()

    async def renew():
        while True:
            await asyncio.sleep(heartbeat_interval)
            if is_release_activation_guarded():
                raise WorkerExecutionAborted("release_activation_started")
            try:
                store.heartbeat(job.lease, now=datetime.now(timezone.utc))
            except Exception as exc:
                raise WorkerExecutionAborted(f"{label}_job_lease_lost") from exc

    loop = asyncio.get_running_loop()
    work = loop.create_future()

    def deliver(result, error):
        if not work.done():
            if error is None:
                work.set_result(result)
            else:
                work.set_exception(error)

    def before_publish() -> None:
        require_running()
        try:
            store.heartbeat(job.lease, now=datetime.now(timezone.utc))
        except Exception as exc:
            raise WorkerExecutionAborted(f"{label}_job_lease_lost") from exc
        if request_validator is not None:
            request_validator()

    def run():
        try:
            if request_validator is not None:
                request_validator()
            kwargs: dict[str, object] = {"before_publish": before_publish}
            if before_provider_fetch is not None:
                kwargs["before_provider_fetch"] = before_fetch
            if publication_guard is not None:
                kwargs["publication_guard"] = publish
            result, error = (
                service.run(job.payload, **kwargs),
                None,
            )
        except Exception as exc:
            result, error = None, exc
        try:
            loop.call_soon_threadsafe(deliver, result, error)
        except RuntimeError:
            pass

    threading.Thread(
        target=run,
        name=f"{label}-job",
        daemon=True,
    ).start()
    heartbeat = asyncio.create_task(renew())
    try:
        done, _ = await asyncio.wait(
            {work, heartbeat},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat in done or not done:
            if work in done:
                simultaneous_error = work.exception()
                if isinstance(simultaneous_error, MarketDailyProviderBudgetDeferred):
                    raise simultaneous_error
            raise WorkerExecutionAborted(f"{label}_execution_deadline_or_lease_lost")
        publication = work.result()
        result_ref = str(
            publication
            if isinstance(publication, str)
            else getattr(publication, "result_ref", "") or ""
        ).strip()
        if not result_ref.startswith(result_prefix):
            raise RuntimeError(f"{label}_result_ref_invalid")
        _record_source_resolution(
            source_resolution_recorder,
            job,
            getattr(publication, "source_resolution", None),
            result_ref=result_ref,
        )
        require_running()
        if finish_guard is None:
            store.finish(
                job.lease, now=datetime.now(timezone.utc), result_ref=result_ref
            )
        else:
            if not isinstance(store, SQLiteJobStore):
                raise ValueError("observation_data_preparation_requires_sqlite")
            store.finish(
                job.lease,
                now=datetime.now(timezone.utc),
                result_ref=result_ref,
                guard=finish_guard,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if isinstance(exc, MarketDailyProviderBudgetDeferred):
            # The reservation transaction already requeued this leased job.
            return
        _record_source_resolution(
            source_resolution_recorder,
            job,
            getattr(exc, "source_resolution", None),
            error_type=type(exc).__name__,
        )
        try:
            now = datetime.now(timezone.utc)
            retry_seconds = min(60 * 2 ** (job.attempt - 1), 3600)
            if isinstance(exc, DailyMarketCollectionFailure):
                store.fail(
                    job.lease,
                    now=now,
                    error=str(exc),
                    retry_seconds=retry_seconds,
                    failure_evidence_ref=exc.failure_evidence_ref,
                )
            else:
                store.fail(
                    job.lease,
                    now=now,
                    error=type(exc).__name__,
                    retry_seconds=retry_seconds,
                )
        except Exception:
            if not isinstance(exc, WorkerExecutionAborted):
                raise
        if isinstance(exc, WorkerExecutionAborted):
            raise
    finally:
        aborted.set()
        work.cancel()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat


def _record_source_resolution(
    recorder: Callable[[dict[str, object]], None] | None,
    job: JobRun,
    resolution: object,
    *,
    result_ref: str | None = None,
    error_type: str | None = None,
) -> None:
    """Best-effort operational telemetry; it never grants or revokes publication."""
    if recorder is None or not isinstance(resolution, VerifiedDailySourceResolution):
        return
    payload = {
        **resolution.to_payload(),
        "job_id": job.job_id,
        "attempt": job.attempt,
        "result_ref": result_ref,
        "error_type": error_type,
    }
    try:
        recorder(payload)
    except Exception:
        logger.exception("Failed to record verified daily source resolution")


async def run_data_worker(config) -> None:
    db = AppDatabase()
    await db.init()
    store = SQLiteJobStore(db.path)
    controls = RuntimeControlRepository(db.path)
    owner = f"data-worker:{os.getpid()}:{uuid.uuid4().hex}"
    preparation_stop = threading.Event()

    async def consume():
        while True:
            await wait_for_release_activation()
            now = datetime.now(timezone.utc)
            if config.market_calendar_auto_sync:
                scheduled_job = enqueue_daily_market_calendar_job(store, now=now)
                job = store.claim(
                    CALENDAR_JOB, owner, now=now, job_id=scheduled_job.job_id
                )
                if job:
                    calendar_service = MarketCalendarAutomationService(
                        db=db, config=config, job_lease=job.lease
                    )
                    try:
                        await execute_calendar_job(store, job, calendar_service)
                    except WorkerExecutionAborted:
                        raise
                    except Exception:
                        logger.exception("Calendar job lease or completion failed")

            try:
                preparation_reports = await asyncio.to_thread(
                    run_research_observation_data_preparation_once,
                    db,
                    config,
                    now=now,
                    stop_requested=preparation_stop,
                )
            except Exception:
                logger.exception("Research observation input preparation failed")
                preparation_reports = []

            try:
                plan = enqueue_latest_daily_market_collection_jobs(
                    db,
                    config,
                    store,
                    now=now,
                )
                if plan.planned_count:
                    logger.info(
                        "Planned daily market collection jobs date=%s count=%d",
                        plan.trade_date.isoformat() if plan.trade_date else "none",
                        plan.planned_count,
                    )
            except Exception:
                logger.exception("Daily market collection job planning failed")

            collection_job = store.claim(DAILY_MARKET_COLLECTION_JOB, owner, now=now)
            if collection_job:
                collection_service = DailyMarketCollectionService(
                    db.path.resolve().parent / "research", config
                )

                def before_collection_fetch(
                    descriptor: MarketDataProviderDescriptor,
                ) -> None:
                    _require_current_daily_market_collection_job(
                        db, config, collection_job
                    )
                    reserve_market_daily_provider_call(
                        db.path,
                        collection_job.lease,
                        descriptor,
                        now=datetime.now(timezone.utc),
                    )

                try:
                    await execute_daily_market_collection_job(
                        store,
                        collection_job,
                        collection_service,
                        request_validator=lambda: (
                            _require_current_daily_market_collection_job(
                                db, config, collection_job
                            )
                        ),
                        before_provider_fetch=before_collection_fetch,
                    )
                except WorkerExecutionAborted:
                    raise
                except Exception:
                    logger.exception("Daily market collection job failed")

            market_job = None
            # Complete the opted-in current input basket before unrelated older
            # verification backfills. Lease selection and retries stay canonical.
            for report in preparation_reports:
                for job_id in reversed(report.get("pending_job_ids", [])):
                    market_job = store.claim(
                        VERIFIED_DAILY_MARKET_JOB, owner, now=now, job_id=job_id
                    )
                    if market_job is not None:
                        break
                if market_job is not None:
                    break
            if market_job is None:
                market_job = store.claim(VERIFIED_DAILY_MARKET_JOB, owner, now=now)
            if market_job:
                verified_service = VerifiedDailyMarketDataService(
                    db.path.resolve().parent / "research",
                    config,
                )
                try:
                    grant = observation_daily_job_grant(market_job.payload)
                except ValueError:
                    # The validator rejects a malformed grant before fetching;
                    # keep that rejection within the ordinary job failure path.
                    grant = None

                def publication_guard(action):
                    assert grant is not None
                    return AutomationRunRepository(db.path).publish_observation_dataset(
                        observation_id=grant["observation_id"],
                        generation=grant["generation"],
                        stop_requested=preparation_stop.is_set,
                        publish=action,
                    )

                def finish_guard(conn):
                    assert grant is not None
                    guard_observation_data_preparation(
                        conn, grant, preparation_stop.is_set
                    )

                def before_verified_fetch(
                    descriptor: MarketDataProviderDescriptor,
                ) -> None:
                    _require_current_verified_daily_market_job(db, config, market_job)
                    reserve_market_daily_provider_call(
                        db.path,
                        market_job.lease,
                        descriptor,
                        now=datetime.now(timezone.utc),
                    )

                def record_source_resolution(payload: dict[str, object]) -> None:
                    db.append_event_sync(
                        event_type=VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        entity_type="market_daily_job",
                        entity_id=market_job.job_id,
                        source="data_worker",
                        source_ref=market_job.job_id,
                        payload=payload,
                    )

                try:
                    await execute_verified_daily_market_job(
                        store,
                        market_job,
                        verified_service,
                        request_validator=lambda: (
                            _require_current_verified_daily_market_job(
                                db, config, market_job
                            )
                        ),
                        before_provider_fetch=before_verified_fetch,
                        publication_guard=publication_guard
                        if grant is not None
                        else None,
                        finish_guard=finish_guard if grant is not None else None,
                        source_resolution_recorder=record_source_resolution,
                    )
                except WorkerExecutionAborted:
                    raise
                except Exception:
                    logger.exception(
                        "Verified daily market job lease or completion failed"
                    )
            await asyncio.sleep(5)

    try:
        await run_with_presence(controls, "data_worker_heartbeat", owner, consume())
    finally:
        preparation_stop.set()
