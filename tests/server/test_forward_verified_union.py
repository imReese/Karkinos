"""Real local proof composition with sanitized data, never future observations."""

import json
from dataclasses import replace
from datetime import date

import pytest

from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.jobs import SQLiteJobStore
from server.services.market.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB
from server.services.research.datasets import (
    ensure_forward_seed_for_source,
    forward_seed_origin_id,
)
from tests.server.test_deployment_scope_datasets import _source_prefix_seed
from tests.server.test_verified_interval_dataset import NOW, _verified_day


def union_seed(tmp_path, *, suffix_receipts=True):
    db, market, config, source, objects, snapshot, current = _source_prefix_seed(
        tmp_path, suffix_receipts=suffix_receipts
    )
    master = market.get_market_universe_snapshot(trade_date="2026-09-21", as_of=NOW)
    identity = bind_stock_master_observation(objects, master)
    snapshot = replace(
        snapshot,
        cutoff=NOW,
        resolver_policy_id="karkinos.dataset.explicit_verified_source_union.v1",
        universe_policy_id="frozen-historical-membership-definition",
        session_memberships=tuple(
            replace(m, available_at=NOW, source_observation_ids=(identity,))
            for m in snapshot.session_memberships
        ),
    )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    source.update(
        immutable_dataset_id=ref.dataset_id, end_date=snapshot.end_date.isoformat()
    )
    read_daily_bar_dataset(objects, ref)
    return db, market, config, source, objects, snapshot, current


def test_verified_union_reuses_all_historical_proof_and_only_queues_suffix(tmp_path):
    db, market, config, source, objects, prefix, current = union_seed(tmp_path)
    scope = source["source_selection"]["deployment_scope"]
    origins = AutomationRunRepository(db.path)
    old_id = forward_seed_origin_id(
        scope,
        2,
        config.market_data_verification_source_policy,
        start_date=source["start_date"],
    )
    prior = origins.claim_automation_run_once_sync(
        run_id=old_id,
        run_type="forward_seed_preparation",
        run_date=NOW.date().isoformat(),
        claimed_at=NOW.isoformat(),
        execution_mode="paper_shadow",
        payload={"old_failed_recipe_retained": True},
    )["run"]
    jobs = SQLiteJobStore(db.path)
    before = jobs.list_recent(VERIFIED_DAILY_MARKET_JOB)
    pending = ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market
    )
    assert pending["status"] == "waiting", pending
    assert len(pending["job_ids"]) == 1
    job = jobs.get(pending["job_ids"][0])
    assert job.payload["trade_date"] == "2026-09-21"
    assert len(jobs.list_recent(VERIFIED_DAILY_MARKET_JOB)) == len(before) + 1
    assert origins.get_automation_run_sync(old_id) == prior
    ref = _verified_day(
        tmp_path / "research",
        date.fromisoformat(job.payload["trade_date"]),
        instruments=current,
    )
    claimed = jobs.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=NOW, job_id=job.job_id
    )
    jobs.finish(claimed.lease, now=NOW, result_ref=f"dataset:{ref.dataset_id}")
    ready = ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market
    )
    assert ready["status"] == "ready", ready
    result = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(ready["dataset_id"]))
    )
    assert result.snapshot.partitions[: len(prefix.partitions)] == prefix.partitions
    assert (
        result.snapshot.session_memberships[: len(prefix.session_memberships)]
        == prefix.session_memberships
    )
    assert result.snapshot.resolver_policy_id == prefix.resolver_policy_id
    assert result.snapshot.universe_policy_id == scope["deployment_scope_fingerprint"]
    assert result.snapshot.session_memberships[-1].decision_at == NOW
    assert result.snapshot.session_memberships[-1].instruments == current
    assert origins.get_automation_run_sync(old_id) == prior
    assert (
        ensure_forward_seed_for_source(
            db, config, source=source, now=NOW, data_store=market
        )["dataset_id"]
        == ready["dataset_id"]
    )
    assert len(jobs.list_recent(VERIFIED_DAILY_MARKET_JOB)) == len(before) + 1
    # Original immutable manifest, availability and declared historical scope survive.
    original = read_daily_bar_dataset(
        objects, DatasetRef(objects.resolve_ref(source["immutable_dataset_id"]))
    )
    assert original.snapshot == prefix


@pytest.mark.parametrize("failure", ["start", "end", "instruments", "proof"])
def test_union_prefix_mismatch_or_corrupt_proof_never_queues_suffix(tmp_path, failure):
    db, market, config, source, objects, prefix, _ = union_seed(tmp_path)
    if failure == "start":
        source["start_date"] = "2026-09-16"
    elif failure == "end":
        source["end_date"] = "2026-09-17"
    elif failure == "instruments":
        source["instruments"] = source["instruments"][:1]
    else:
        path = objects._path_for(prefix.partitions[0].materialization_id)
        path.chmod(0o644)
        path.write_bytes(b"corrupt fixture")
    jobs = SQLiteJobStore(db.path)
    before = jobs.list_recent(VERIFIED_DAILY_MARKET_JOB)
    result = ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market
    )
    assert result["status"] == "blocked", result
    assert result["last_blocker"]["code"] in {
        "forward_seed_source_prefix_mismatch",
        "forward_seed_source_prefix_unreadable",
    }
    assert jobs.list_recent(VERIFIED_DAILY_MARKET_JOB) == before
