"""Durable admission for managed daily-bar Provider attempts."""

from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from data.market.contracts import MarketDataProviderDescriptor
from server.contracts.jobs import JobLease, job_time
from server.persistence.connection import connect_sqlite
from server.persistence.jobs import require_job_lease

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_REVIEWED_UPSTREAM_GROUPS = frozenset({"baostock", "tencent", "eastmoney", "tushare"})
DEFAULT_DAILY_PROVIDER_ATTEMPT_LIMIT = 100
BUDGET_DEFERRED_CODE = "market_daily_provider_call_budget_exhausted"


class MarketDailyProviderBudgetDeferred(RuntimeError):
    """The job was atomically returned to the queue for the next budget day."""

    def __init__(self, upstream_group: str, available_at: datetime) -> None:
        self.upstream_group = upstream_group
        self.available_at = available_at
        super().__init__(BUDGET_DEFERRED_CODE)


def reserve_market_daily_provider_call(
    db_path: str | Path,
    lease: JobLease,
    descriptor: MarketDataProviderDescriptor,
    *,
    now: datetime,
    daily_limit: int = DEFAULT_DAILY_PROVIDER_ATTEMPT_LIMIT,
) -> None:
    """Count one canonical fetch attempt before I/O, or defer under the same lock.

    A reservation remains spent when Provider I/O fails, times out, or the process
    exits. The limit is on calls to ``fetch_daily_bars``, not hidden SDK requests.
    """
    if not isinstance(lease, JobLease):
        raise TypeError("market_daily_provider_budget_lease_invalid")
    if not isinstance(descriptor, MarketDataProviderDescriptor):
        raise TypeError("market_daily_provider_budget_descriptor_invalid")
    group = descriptor.upstream_group.strip().lower()
    if group not in _REVIEWED_UPSTREAM_GROUPS:
        raise ValueError("market_daily_provider_budget_upstream_unreviewed")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market_daily_provider_budget_clock_invalid")
    if (
        isinstance(daily_limit, bool)
        or not isinstance(daily_limit, int)
        or daily_limit < 1
    ):
        raise ValueError("market_daily_provider_budget_limit_invalid")

    local_now = now.astimezone(_SHANGHAI)
    local_day = local_now.date().isoformat()
    next_day = local_now.date() + timedelta(days=1)
    available_at = datetime.combine(next_day, time.min, _SHANGHAI).astimezone(
        timezone.utc
    )
    deferred = False
    conn = connect_sqlite(Path(db_path), timeout=2)
    try:
        conn.execute("BEGIN IMMEDIATE")
        require_job_lease(conn, lease, now=now)
        used = conn.execute(
            "SELECT COUNT(*) FROM market_daily_provider_call_reservations "
            "WHERE shanghai_date=? AND upstream_group=?",
            (local_day, group),
        ).fetchone()[0]
        if used >= daily_limit:
            # Keep attempt monotonic for lease fencing. One budget deferral adds
            # one claim slot, preserving the existing finite failure allowance.
            conn.execute(
                "UPDATE job_runs SET status='queued', max_attempts=max_attempts+1, "
                "available_at=?, error=?, lease_owner=NULL, lease_expires_at=NULL, "
                "updated_at=? WHERE job_id=?",
                (
                    job_time(available_at),
                    BUDGET_DEFERRED_CODE,
                    job_time(now),
                    lease.job_id,
                ),
            )
            deferred = True
        else:
            conn.execute(
                "INSERT INTO market_daily_provider_call_reservations "
                "(shanghai_date, upstream_group, job_id, job_attempt, reserved_at) "
                "VALUES (?,?,?,?,?)",
                (local_day, group, lease.job_id, lease.attempt, job_time(now)),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    if deferred:
        raise MarketDailyProviderBudgetDeferred(group, available_at)


def market_daily_provider_call_budget_status(
    db_path: str | Path,
    *,
    now: datetime,
    daily_limit: int = DEFAULT_DAILY_PROVIDER_ATTEMPT_LIMIT,
) -> dict[str, object]:
    """Read today's durable usage without creating a database or reservations."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market_daily_provider_budget_clock_invalid")
    if (
        isinstance(daily_limit, bool)
        or not isinstance(daily_limit, int)
        or daily_limit < 1
    ):
        raise ValueError("market_daily_provider_budget_limit_invalid")
    local_day = now.astimezone(_SHANGHAI).date().isoformat()
    try:
        conn = connect_sqlite(Path(db_path), readonly=True)
        try:
            rows = conn.execute(
                "SELECT upstream_group, COUNT(*) FROM "
                "market_daily_provider_call_reservations WHERE shanghai_date=? "
                "GROUP BY upstream_group",
                (local_day,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise OSError("market_daily_provider_budget_unreadable") from exc
    used_by_group = {str(group): int(used) for group, used in rows}
    if set(used_by_group) - _REVIEWED_UPSTREAM_GROUPS:
        raise ValueError("market_daily_provider_budget_upstream_unreviewed")
    return {
        "scope": "managed_daily_market_jobs",
        "shanghai_date": local_day,
        "groups": {
            group: {
                "used": used_by_group.get(group, 0),
                "limit": daily_limit,
                "remaining": max(0, daily_limit - used_by_group.get(group, 0)),
            }
            for group in sorted(_REVIEWED_UPSTREAM_GROUPS)
        },
    }


__all__ = [
    "BUDGET_DEFERRED_CODE",
    "DEFAULT_DAILY_PROVIDER_ATTEMPT_LIMIT",
    "MarketDailyProviderBudgetDeferred",
    "market_daily_provider_call_budget_status",
    "reserve_market_daily_provider_call",
]
