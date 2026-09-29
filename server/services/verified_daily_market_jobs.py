"""Plan daily-market collection and explicit verification jobs from local facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.source_policy import (
    source_policy_for_config,
    verification_source_policy_for_config,
)
from server.contracts.jobs import JobRun, JobStore
from server.services.daily_market_collection import (
    DAILY_MARKET_COLLECTION_JOB,
    DailyMarketCollectionJobRequest,
)
from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
    resolve_verified_closed_trading_dates,
    resolve_verified_closed_trading_dates_in_range,
)
from server.services.market_hours import get_shanghai_now
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


def enqueue_latest_daily_market_collection_jobs(
    db: Any,
    config: object,
    store: JobStore,
    *,
    now: datetime,
    lookback_days: int = 30,
) -> VerifiedDailyMarketJobPlan:
    """Collect one source per watched instrument and closed session by default."""
    resolved_dates, instruments = _planning_facts(db, now, lookback_days)
    policy = source_policy_for_config(config)
    jobs = [
        store.enqueue(
            DAILY_MARKET_COLLECTION_JOB,
            DailyMarketCollectionJobRequest(
                trade_date=date.fromisoformat(resolved.trade_date),
                instrument=instrument,
                source_policy_id=policy.policy_id,
                calendar_evidence_refs=resolved.calendar_evidence_refs,
            ).to_payload(),
            now=now,
        )
        for resolved in resolved_dates
        for instrument in instruments
    ]
    return _job_plan(resolved_dates, instruments, jobs)


def enqueue_latest_verified_daily_market_jobs(
    db: Any,
    config: object,
    store: JobStore,
    *,
    now: datetime,
    lookback_days: int = 30,
) -> VerifiedDailyMarketJobPlan:
    """Explicitly enqueue idempotent cross-source verification jobs."""
    resolved_dates, instruments = _planning_facts(db, now, lookback_days)
    policy = verification_source_policy_for_config(config)
    jobs = [
        store.enqueue(
            VERIFIED_DAILY_MARKET_JOB,
            VerifiedDailyMarketJobRequest(
                trade_date=date.fromisoformat(resolved.trade_date),
                instruments=(instrument,),
                source_policy_id=policy.policy_id,
                calendar_evidence_refs=resolved.calendar_evidence_refs,
            ).to_payload(),
            now=now,
        )
        for resolved in resolved_dates
        for instrument in instruments
    ]
    return _job_plan(resolved_dates, instruments, jobs)


def enqueue_verified_daily_market_jobs_for_range(
    db: Any,
    config: object,
    store: JobStore,
    *,
    instrument: InstrumentKey,
    start_date: date,
    end_date: date,
    now: datetime,
    reobserve: bool = False,
) -> tuple[JobRun, ...]:
    """Explicitly enqueue one verified-source job for each closed SSE session."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("verified_daily_market_job_plan_now_must_be_timezone_aware")
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise ValueError("verified_daily_market_instrument_type_unsupported")
    if not isinstance(reobserve, bool):
        raise ValueError("verified_daily_market_reobserve_invalid")
    resolved_dates = resolve_verified_closed_trading_dates_in_range(
        db, now, start_date=start_date, end_date=end_date
    )
    if not resolved_dates:
        raise VerifiedDailyMarketJobPlanningError(
            "verified_daily_market_trading_dates_unavailable"
        )
    policy = verification_source_policy_for_config(config)
    observation_round = (
        f"post_close.reobserve.{get_shanghai_now(now).date().isoformat()}"
        if reobserve
        else "post_close.v1"
    )
    payloads = tuple(
        VerifiedDailyMarketJobRequest(
            trade_date=date.fromisoformat(resolved.trade_date),
            instruments=(instrument,),
            source_policy_id=policy.policy_id,
            calendar_evidence_refs=resolved.calendar_evidence_refs,
            observation_round=observation_round,
        ).to_payload()
        for resolved in resolved_dates
    )
    return store.enqueue_many(VERIFIED_DAILY_MARKET_JOB, payloads, now=now)


def _planning_facts(db: Any, now: datetime, lookback_days: int):
    if not isinstance(now, datetime):
        raise TypeError("verified_daily_market_job_plan_now_must_be_datetime")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("verified_daily_market_job_plan_now_must_be_timezone_aware")

    resolved_dates = resolve_verified_closed_trading_dates(
        db,
        now,
        lookback_days=lookback_days,
    )
    if not resolved_dates:
        latest = resolve_latest_verified_closed_trading_date(db, now)
        resolved_dates = () if latest is None else (latest,)
    if not resolved_dates:
        return (), ()

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

    return resolved_dates, supported_watchlist_instruments(rows)


def _job_plan(resolved_dates, instruments, jobs: list[JobRun]):
    all_refs: list[str] = []
    for resolved in resolved_dates:
        for ref in resolved.calendar_evidence_refs:
            if ref not in all_refs:
                all_refs.append(ref)
    return VerifiedDailyMarketJobPlan(
        trade_date=(
            date.fromisoformat(resolved_dates[-1].trade_date)
            if resolved_dates
            else None
        ),
        calendar_evidence_refs=tuple(all_refs),
        instruments=instruments,
        jobs=tuple(jobs),
    )


def supported_watchlist_instruments(
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
    "enqueue_latest_daily_market_collection_jobs",
    "supported_watchlist_instruments",
    "VERIFIED_DAILY_MARKET_JOB",
    "VerifiedDailyMarketJobPlan",
    "VerifiedDailyMarketJobPlanningError",
    "enqueue_latest_verified_daily_market_jobs",
    "enqueue_verified_daily_market_jobs_for_range",
]
