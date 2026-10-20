"""The forward consumer admits dated shards, never late reconstructed decisions."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.store import DataStore
from server.services.market.market_universe_truth import normalize_a_share_members
from server.services.research.research_observation_inputs import (
    read_research_observation_dataset,
)
from tests.server.test_deployment_scope_datasets import _composed
from tests.server.test_verified_interval_dataset import DAYS, STOCK, _calendar

pytestmark = pytest.mark.product_smoke


def forward_dataset(tmp_path, *, late=False):
    objects, original = _composed(tmp_path)
    market = DataStore(tmp_path / "master")
    memberships = []
    for membership in original.snapshot.session_memberships:
        available = datetime.combine(
            membership.partition_date, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=8, minutes=5)
        master = market.save_market_universe_snapshot(
            trade_date=membership.partition_date.isoformat(),
            provider_name="fixture",
            members=normalize_a_share_members(
                [key.symbol for key in membership.instruments]
            ),
            capture_started_at=available - timedelta(seconds=1),
            capture_completed_at=available,
        )
        memberships.append(
            replace(
                membership,
                available_at=available,
                source_observation_ids=(
                    bind_stock_master_observation(objects, master),
                ),
                decision_at=(
                    datetime(2026, 9, 21, 1, 30, tzinfo=timezone.utc)
                    if late and membership.partition_date == DAYS[-1]
                    else available
                ),
            )
        )
    now = (
        datetime(2026, 9, 21, 2, tzinfo=timezone.utc)
        if late
        else datetime(2026, 9, 18, 8, 10, tzinfo=timezone.utc)
    )
    snapshot = replace(
        original.snapshot, cutoff=now, session_memberships=tuple(memberships)
    )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    calendar = _calendar(trading_days=(*DAYS, date(2026, 9, 21), date(2026, 9, 22)))
    calendar["official_verified_at"] = "2026-09-01T00:00:00Z"
    calendar["fetched_at"] = "2026-09-01T00:00:00Z"
    return objects, ref, now, calendar


def test_dynamic_forward_reads_all_shards_and_expanding_membership(tmp_path):
    objects, ref, now, calendar = forward_dataset(tmp_path)
    args = dict(
        instruments=(STOCK,),
        start_date=DAYS[0],
        now=now,
        calendar_rows=[calendar],
        minimum_bars=2,
    )
    result = read_research_observation_dataset(
        objects,
        ref.dataset_id,
        deployment_scope={"deployment_scope_fingerprint": "fixture.dynamic.v1"},
        **args,
    )
    assert len(result.bars) == 3
    assert len(result.snapshot.instruments_for_session(DAYS[-1])) == 2
    with pytest.raises(ValueError, match="observation_dataset_universe_mismatch"):
        read_research_observation_dataset(objects, ref.dataset_id, **args)


def test_late_reconstructed_membership_is_not_a_forward_decision(tmp_path):
    objects, ref, now, calendar = forward_dataset(tmp_path, late=True)
    with pytest.raises(ValueError, match="observation_membership_not_available"):
        read_research_observation_dataset(
            objects,
            ref.dataset_id,
            instruments=(STOCK,),
            start_date=DAYS[0],
            now=now,
            calendar_rows=[calendar],
            minimum_bars=2,
            deployment_scope={"deployment_scope_fingerprint": "fixture.dynamic.v1"},
            membership_after=DAYS[0],
        )
