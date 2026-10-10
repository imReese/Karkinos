"""Plan daily-market collection and explicit verification jobs from local facts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.source_policy import (
    source_policy_for_config,
    verification_source_policy_for_config,
)
from server.contracts.jobs import JobRun, JobStore
from server.persistence.jobs import SQLiteJobStore, job_id_for
from server.services.daily_market_collection import (
    DAILY_MARKET_COLLECTION_JOB,
    DailyMarketCollectionJobRequest,
    collection_capture_completed_at,
)
from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
    resolve_verified_closed_trading_dates,
    resolve_verified_closed_trading_dates_in_range,
)
from server.services.market_hours import get_shanghai_now
from server.services.verified_daily_market_data import VerifiedDailyMarketJobRequest

VERIFIED_DAILY_MARKET_JOB = "market_daily_verified"
MAX_VERIFIED_DATASET_INSTRUMENTS: int = 40
logger = logging.getLogger(__name__)


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
    base_jobs = {
        (resolved.trade_date, instrument): store.enqueue(
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
    }
    jobs = list(base_jobs.values())
    db_path = getattr(store, "path", None)
    if db_path is not None:
        research_root = Path(db_path).resolve().parent / "research"
        local_tz = get_shanghai_now(now).tzinfo
        for current, following in zip(resolved_dates, resolved_dates[1:]):
            next_date = date.fromisoformat(following.trade_date)
            next_close = datetime.combine(next_date, time(16), local_tz)
            for instrument in instruments:
                base = base_jobs[(current.trade_date, instrument)]
                if base.status != "succeeded" or not base.result_ref:
                    continue
                request = DailyMarketCollectionJobRequest.from_payload(base.payload)
                revision_payload = DailyMarketCollectionJobRequest(
                    trade_date=request.trade_date,
                    instrument=instrument,
                    source_policy_id=policy.policy_id,
                    calendar_evidence_refs=request.calendar_evidence_refs,
                    observation_round=(
                        f"post_close.next_session.{following.trade_date}"
                    ),
                ).to_payload()
                if isinstance(store, SQLiteJobStore):
                    existing = store.get(
                        job_id_for(DAILY_MARKET_COLLECTION_JOB, revision_payload)
                    )
                    if existing is not None:
                        jobs.append(existing)
                        continue
                try:
                    captured_at = collection_capture_completed_at(
                        research_root, request=request, result_ref=base.result_ref
                    )
                except Exception:
                    logger.warning(
                        "Skipping automatic revision without readable base evidence job=%s",
                        base.job_id,
                    )
                    continue
                if captured_at >= next_close:
                    continue
                jobs.append(
                    store.enqueue(
                        DAILY_MARKET_COLLECTION_JOB,
                        revision_payload,
                        now=now,
                    )
                )
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
    instrument: InstrumentKey | None = None,
    instruments: tuple[InstrumentKey, ...] | None = None,
    start_date: date,
    end_date: date,
    now: datetime,
    reobserve: bool = False,
) -> tuple[JobRun, ...]:
    """Explicitly enqueue one verified-source job for each closed SSE session."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("verified_daily_market_job_plan_now_must_be_timezone_aware")
    if instrument is not None and instruments is not None:
        raise ValueError("verified_daily_market_universe_fields_conflict")
    if instruments is None:
        if instrument is None:
            raise ValueError("verified_daily_market_instruments_required")
        instruments = (instrument,)
    instruments = DailyBarRequest(instruments, start_date, end_date).instruments
    if (
        not 1 <= len(instruments) <= MAX_VERIFIED_DATASET_INSTRUMENTS
        or any(
            item.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}
            for item in instruments
        )
        or len({item.symbol for item in instruments}) != len(instruments)
    ):
        raise ValueError("verified_daily_market_universe_invalid")
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
            instruments=instruments,
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
