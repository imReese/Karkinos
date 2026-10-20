"""Full-market history uses the existing durable verification worker and catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import read_daily_bar_dataset
from data.storage.objects import ContentAddressedObjectStore
from data.store import DataStore
from server.contracts.jobs import JobRun
from server.persistence.jobs import SQLiteJobStore
from server.services.market.calendar import (
    resolve_verified_closed_trading_dates_in_range,
)
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    require_complete_market_universe_snapshot,
)
from server.services.market.verified_daily_market_data import (
    VerifiedDailyMarketJobRequest,
    verified_daily_resolver_policy_id,
)
from server.services.market.verified_daily_market_jobs import (
    enqueue_verified_daily_market_jobs_for_range,
)


def history_session_symbols(
    symbols: Sequence[str], metadata: Sequence[Mapping[str, Any]], session: str
) -> set[str]:
    """Apply observed listing dates; unknown dates never silently remove a stock.

    Current stock-master membership remains a current-survivor research scope,
    not evidence of historical point-in-time membership or suspension status.
    """
    facts = {str(row["symbol"]): row for row in metadata}
    return {
        symbol
        for symbol in symbols
        if not (
            facts.get(symbol, {}).get("list_date", "")
            and str(facts[symbol]["list_date"]) > session
        )
        and not (
            facts.get(symbol, {}).get("delist_date", "")
            and str(facts[symbol]["delist_date"]) <= session
        )
    }


def enqueue_full_market_history(
    *,
    db: Any,
    config: object,
    data_store: DataStore,
    exchanges: tuple[str, ...],
    snapshot_id: str | None,
    start_date: date,
    end_date: date,
    now: datetime,
    reobserve: bool,
) -> tuple[tuple[JobRun, ...], dict[str, Any]]:
    """Plan explicit dated coverage without mutating legacy ingestion receipts."""
    if not exchanges or not set(exchanges) <= {"SSE", "SZSE", "BSE"}:
        raise ValueError("market_history_exchanges_invalid")
    snapshot = data_store.get_market_universe_snapshot(
        snapshot_id=snapshot_id,
        as_of=None if snapshot_id else now,
    )
    snapshot = require_complete_market_universe_snapshot(
        snapshot, policy=MarketUniversePolicy(), available_as_of=now
    )
    members = [
        str(row["symbol"])
        for row in snapshot["members"]
        if row["exchange"] in exchanges
    ]
    metadata = snapshot.get("member_metadata") or []
    listed = {row["symbol"]: row.get("list_date") for row in metadata}
    if not members or any(not listed.get(symbol) for symbol in members):
        raise ValueError("market_history_listing_dates_unavailable")
    dates = resolve_verified_closed_trading_dates_in_range(
        db, now, start_date=start_date, end_date=end_date, maximum_calendar_days=3653
    )
    if not dates:
        raise ValueError("market_history_verified_calendar_unavailable")
    memberships = {
        date.fromisoformat(row.trade_date): tuple(
            InstrumentKey(symbol=symbol, instrument_type=InstrumentType.STOCK)
            for symbol in sorted(
                history_session_symbols(members, metadata, row.trade_date)
            )
        )
        for row in dates
    }
    instruments = tuple(
        sorted(
            {key for keys in memberships.values() for key in keys},
            key=lambda key: key.symbol,
        )
    )
    jobs = enqueue_verified_daily_market_jobs_for_range(
        db,
        config,
        SQLiteJobStore(db.path),
        instruments=instruments,
        start_date=start_date,
        end_date=end_date,
        now=now,
        historical_range=True,
        reobserve=reobserve,
        session_instruments=memberships,
    )
    return jobs, {
        "market_universe_snapshot_id": snapshot["snapshot_id"],
        "exchanges": sorted(set(exchanges)),
        "requested_member_count": len(members),
        "interval_member_count": len(instruments),
        "outside_listing_interval_count": len(members) - len(instruments),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "trading_date_count": len(dates),
        "membership_basis": "current_active_stock_master_with_observed_listing_dates",
        "historical_membership_verified": False,
        "storage_authority": "verified_dataset_catalog",
    }


def history_job_result(root: Path, job: JobRun) -> dict[str, Any]:
    """Only a readable, registered Dataset covering the exact job is complete."""
    result: dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status,
        "symbols": [row["symbol"] for row in job.payload["instruments"]],
        "dataset_id": None,
        "error": job.error,
    }
    if job.status != "succeeded":
        return result
    try:
        if not job.result_ref or not job.result_ref.startswith("dataset:"):
            raise ValueError("market_history_dataset_result_missing")
        dataset_id = job.result_ref.removeprefix("dataset:")
        entry = DatasetCatalog(root).get(dataset_id)
        verified = read_daily_bar_dataset(
            ContentAddressedObjectStore(root / "objects"), entry.ref
        )
        snapshot = verified.snapshot
        request = VerifiedDailyMarketJobRequest.from_payload(job.payload)
        expected_memberships = {
            day: members
            for day, members, _refs in request.session_memberships
            if members
        }
        if (
            not snapshot.verification_bound
            or snapshot.instruments != request.instruments
            or {
                item.partition_date: item.instruments
                for item in snapshot.session_memberships
            }
            != expected_memberships
            or snapshot.resolver_policy_id
            != verified_daily_resolver_policy_id(request.source_policy_id)
        ):
            raise ValueError("market_history_dataset_scope_mismatch")
        result["dataset_id"] = dataset_id
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
    return result
