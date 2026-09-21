"""Plan durable verified daily-market jobs from persisted application facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.source_policy import source_policy_for_config
from server.contracts.jobs import JobRun, JobStore
from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
)
from server.services.verified_daily_market_data import VerifiedDailyMarketJobRequest

VERIFIED_DAILY_MARKET_JOB = "market_daily_verified"


class VerifiedDailyMarketJobPlanningError(RuntimeError):
    """Persisted planning facts are invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class VerifiedDailyMarketJobPlan:
    """One deterministic planner pass over the latest closed market session."""

    trade_date: date | None
    calendar_evidence_refs: tuple[str, ...]
    instruments: tuple[InstrumentKey, ...]
    jobs: tuple[JobRun, ...]

    @property
    def planned_count(self) -> int:
        return len(self.jobs)


def enqueue_latest_verified_daily_market_jobs(
    db: Any,
    config: object,
    store: JobStore,
    *,
    now: datetime,
) -> VerifiedDailyMarketJobPlan:
    """Enqueue one idempotent job per supported watchlist instrument."""
    if not isinstance(now, datetime):
        raise TypeError("verified_daily_market_job_plan_now_must_be_datetime")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("verified_daily_market_job_plan_now_must_be_timezone_aware")

    resolved = resolve_latest_verified_closed_trading_date(db, now)
    if resolved is None:
        return VerifiedDailyMarketJobPlan(
            trade_date=None,
            calendar_evidence_refs=(),
            instruments=(),
            jobs=(),
        )

    read_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if not callable(read_watchlist):
        raise VerifiedDailyMarketJobPlanningError(
            "verified_daily_market_watchlist_reader_missing"
        )
    try:
        rows = read_watchlist() or []
    except Exception as exc:
        raise VerifiedDailyMarketJobPlanningError(
            "verified_daily_market_watchlist_unreadable"
        ) from exc

    instruments = _supported_watchlist_instruments(rows)
    policy = source_policy_for_config(config)

    jobs: list[JobRun] = []
    trade_date = date.fromisoformat(resolved.trade_date)
    for instrument in instruments:
        request = VerifiedDailyMarketJobRequest(
            trade_date=trade_date,
            instruments=(instrument,),
            source_policy_id=policy.policy_id,
            calendar_evidence_refs=resolved.calendar_evidence_refs,
        )
        jobs.append(
            store.enqueue(
                VERIFIED_DAILY_MARKET_JOB,
                request.to_payload(),
                now=now,
            )
        )

    return VerifiedDailyMarketJobPlan(
        trade_date=trade_date,
        calendar_evidence_refs=resolved.calendar_evidence_refs,
        instruments=instruments,
        jobs=tuple(jobs),
    )


def _supported_watchlist_instruments(
    rows: list[dict[str, Any]],
) -> tuple[InstrumentKey, ...]:
    result: list[InstrumentKey] = []
    seen: set[InstrumentKey] = set()

    for row in rows:
        if not isinstance(row, dict):
            raise VerifiedDailyMarketJobPlanningError(
                "verified_daily_market_watchlist_row_invalid"
            )
        symbol = str(row.get("symbol") or "").strip()
        raw_type = str(
            row.get("instrument_type") or row.get("asset_class") or ""
        ).strip()
        if not symbol:
            raise VerifiedDailyMarketJobPlanningError(
                "verified_daily_market_watchlist_symbol_missing"
            )
        try:
            instrument_type = InstrumentType.from_persisted(raw_type)
        except ValueError as exc:
            raise VerifiedDailyMarketJobPlanningError(
                "verified_daily_market_watchlist_identity_invalid"
            ) from exc

        if instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
            continue

        instrument = InstrumentKey(symbol, instrument_type)
        if instrument in seen:
            continue
        seen.add(instrument)
        result.append(instrument)

    result.sort(key=lambda item: (item.instrument_type.value, item.symbol))
    return tuple(result)


__all__ = [
    "VERIFIED_DAILY_MARKET_JOB",
    "VerifiedDailyMarketJobPlan",
    "VerifiedDailyMarketJobPlanningError",
    "enqueue_latest_verified_daily_market_jobs",
]
