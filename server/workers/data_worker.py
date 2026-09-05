"""Isolated data/operations worker; calendar is the first migrated provider loop."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from server.contracts.jobs import JobRun, JobStore
from server.db import AppDatabase
from server.persistence.jobs import SQLiteJobStore
from server.persistence.runtime_controls import RuntimeControlRepository
from server.release_activation import (
    is_release_activation_guarded,
    wait_for_release_activation,
)
from server.services.market_calendar_automation import MarketCalendarAutomationService
from server.workers.presence import run_with_presence

logger = logging.getLogger(__name__)
CALENDAR_JOB = "market_calendar_sync"


class WorkerExecutionAborted(RuntimeError):
    """The process must exit because an outstanding provider thread was fenced."""


async def execute_calendar_job(
    store: JobStore,
    job: JobRun,
    service,
    *,
    timeout: float = 120,
    heartbeat_interval: float = 15,
) -> None:
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
                service.run_due(
                    now=datetime.fromisoformat(job.payload["scheduled_at"])
                ),
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
            raise RuntimeError("calendar_evidence_not_verified")
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


async def run_data_worker(config) -> None:
    db = AppDatabase()
    db.init_sync()
    store = SQLiteJobStore(db.path)
    controls = RuntimeControlRepository(db.path)
    owner = f"data-worker:{os.getpid()}:{uuid.uuid4().hex}"

    async def consume():
        while True:
            await wait_for_release_activation()
            now = datetime.now(timezone.utc)
            if config.market_calendar_auto_sync:
                scheduled = now.replace(minute=0, second=0, microsecond=0)
                store.enqueue(
                    CALENDAR_JOB, {"scheduled_at": scheduled.isoformat()}, now=now
                )
                job = store.claim(CALENDAR_JOB, owner, now=now)
                if job:
                    service = MarketCalendarAutomationService(
                        db=db, config=config, job_lease=job.lease
                    )
                    try:
                        await execute_calendar_job(store, job, service)
                    except WorkerExecutionAborted:
                        raise
                    except Exception:
                        logger.exception("Calendar job lease or completion failed")
            await asyncio.sleep(5)

    await run_with_presence(controls, "data_worker_heartbeat", owner, consume())
