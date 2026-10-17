"""Sanitized, offline CAS/SQLite inputs for the deployment product journey."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetMembership, DailyBarDatasetSnapshot
from data.dataset.reader import read_daily_bar_dataset
from data.providers.tushare_corporate_actions import (
    collect_tushare_dividend_observation,
)
from data.storage.objects import ContentAddressedObjectStore
from data.store import DataStore
from server.db import AppDatabase
from server.persistence.market_calendar import MarketCalendarRepository
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
    normalize_a_share_members,
)
from tests.server.test_verified_interval_dataset import _verified_day


def build_real_scope_datasets(
    tmp_path: Path,
    *,
    development_periods: int = 140,
    future_periods: int = 20,
) -> dict:
    """Build exploratory sessions and actually observed future sessions.

    Provider adapters consume explicit synthetic responses, never network data.
    Dates are a declared synthetic calendar, not a claim about exchange holidays.
    All other captures, reconciliation, manifests, catalog and replay are real.
    """
    tmp_path = tmp_path.resolve()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    calendar_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    db._market_calendar = MarketCalendarRepository(
        db.path, now=lambda _tz=None: calendar_at
    )
    total_periods = development_periods + future_periods
    dates = tuple(
        day.date() for day in pd.bdate_range(end="2026-08-31", periods=total_periods)
    )
    for year in (2025, 2026):
        first = date(year, 1, 1)
        days = []
        current = first
        while current.year == year:
            days.append(
                {"date": current.isoformat(), "is_trading_day": current.weekday() < 5}
            )
            current += timedelta(days=1)
        source = str(year % 10) * 64
        db.upsert_market_calendar_snapshot_sync(
            {
                "exchange": "SSE",
                "year": year,
                "provider": "synthetic_fixture",
                "status": "available",
                "trading_day_count": sum(row["is_trading_day"] for row in days),
                "closed_day_count": sum(not row["is_trading_day"] for row in days),
                "source_fingerprint": source,
                "days": days,
                "limitations": [],
                "fetched_at": calendar_at.isoformat(),
            }
        )
        row = db.update_market_calendar_verification_sync(
            exchange="SSE",
            year=year,
            source_fingerprint=source,
            verification_status="verified",
            official_source_url="https://example.test/synthetic-calendar",
            official_source_fingerprint="e" * 64,
            verified_by="synthetic-fixture",
        )
        assert validate_verified_market_calendar(row).verified
    market = DataStore(tmp_path / "market")
    root = tmp_path / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    instruments = tuple(
        InstrumentKey(str(600000 + index), InstrumentType.STOCK) for index in range(4)
    )
    policy = MarketUniversePolicy(
        minimum_master_member_count=4, minimum_history_rows=120
    )
    scope = market_deployment_scope(policy)
    partitions, memberships, prices = [], [], {}
    resolver_policy_id = market_schema_version = None
    for index, day in enumerate(dates):
        phase = index % 20
        close = Decimal("10") + Decimal(min(phase, 20 - phase)) / Decimal("10")
        prices[day] = close
        ref = _verified_day(root, day, instruments=instruments, close=str(close))
        result = read_daily_bar_dataset(objects, ref)
        resolver_policy_id = result.snapshot.resolver_policy_id
        market_schema_version = result.snapshot.market_schema_version
        partitions.append(
            replace(result.snapshot.partitions[0], instruments=instruments)
        )
        at = datetime.combine(day, time(8, 5), tzinfo=timezone.utc)
        refs = ()
        if index >= development_periods - 1:
            master = market.save_market_universe_snapshot(
                trade_date=day.isoformat(),
                provider_name="synthetic_fixture",
                members=normalize_a_share_members([key.symbol for key in instruments]),
                capture_started_at=at - timedelta(seconds=1),
                capture_completed_at=at,
                source_metadata=[
                    {
                        "symbol": key.symbol,
                        "display_name": f"合成普通股{key.symbol}",
                        "list_date": "20200101",
                        "list_status": "L",
                    }
                    for key in instruments
                ],
            )
            refs = (bind_stock_master_observation(objects, master),)
        memberships.append(
            DailyBarDatasetMembership(
                day,
                instruments,
                at,
                refs,
                at + timedelta(minutes=5) if refs else None,
            )
        )
    assert resolver_policy_id is not None and market_schema_version is not None

    def publish(through: int):
        cutoff = datetime.combine(dates[through - 1], time(8, 10), tzinfo=timezone.utc)
        empty_response = SimpleNamespace(dividend=lambda **_kwargs: pd.DataFrame())
        actions = tuple(
            collect_tushare_dividend_observation(
                objects,
                instrument=key,
                client=empty_response,
                clock=lambda: cutoff - timedelta(minutes=1),
            ).object_id
            for key in instruments
        )
        snapshot = DailyBarDatasetSnapshot(
            start_date=dates[0],
            end_date=dates[through - 1],
            cutoff=cutoff,
            instruments=instruments,
            resolver_policy_id=resolver_policy_id,
            market_schema_version=market_schema_version,
            partitions=tuple(partitions[:through]),
            session_memberships=tuple(memberships[:through]),
            universe_policy_id=scope["deployment_scope_fingerprint"],
            corporate_action_observation_ids=actions,
        )
        ref = publish_daily_bar_dataset_manifest(objects, snapshot)
        assert read_daily_bar_dataset(objects, ref).snapshot == snapshot
        DatasetCatalog(root).register(objects, ref)
        return ref, snapshot

    development_ref, development_snapshot = publish(development_periods)
    forward_ref, forward_snapshot = publish(total_periods)
    return {
        "db": db,
        "data_store": market,
        "root": root,
        "objects": objects,
        "policy": policy,
        "scope": scope,
        "instruments": instruments,
        "dates": dates,
        "development_dates": dates[:development_periods],
        "future_dates": dates[development_periods:],
        "prices": prices,
        "development_ref": development_ref,
        "forward_ref": forward_ref,
        "development_snapshot": development_snapshot,
        "forward_snapshot": forward_snapshot,
        "cutoff": forward_snapshot.cutoff,
    }
