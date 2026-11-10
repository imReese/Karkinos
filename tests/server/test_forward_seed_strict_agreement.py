"""Seed consumers retain strict research agreement over a permissive primary Reader.

Verification records and their captures/quality/reconciliation are real local CAS
fixtures. Only the outer Dataset Reader result is substituted, modelling MAIN's
primary-authority read contract without changing its global policy.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
)
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.source_policy import verification_source_policy_for_config
from data.storage.objects import ContentAddressedObjectStore
from server.config import ServerConfig
from server.services.market.verified_daily_market_data import (
    verified_daily_resolver_policy_id,
)
from server.services.research import datasets
from tests.data.market.test_verification_evidence import (
    CHECKED_AT,
    DAY,
    INSTRUMENT,
    _verification,
)

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


def supply(monkeypatch, tmp_path, mode):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    verification, _, _ = _verification(
        objects, comparison_close="10.49" if mode == "conflict" else "10.48"
    )
    config = ServerConfig()
    policy = verification_source_policy_for_config(config).policy_id
    proof_id = None if mode == "missing" else verification.verification_id
    now = CHECKED_AT + timedelta(minutes=1)
    scope = {"deployment_scope_fingerprint": "frozen-scope"}
    member = DailyBarDatasetMembership(
        DAY,
        (INSTRUMENT,),
        CHECKED_AT,
        source_observation_ids=(verification.verification_id,),
        decision_at=CHECKED_AT,
    )
    snapshot = DailyBarDatasetSnapshot(
        start_date=DAY,
        end_date=DAY,
        cutoff=now,
        instruments=(INSTRUMENT,),
        resolver_policy_id=verified_daily_resolver_policy_id(policy),
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=(
            DailyBarDatasetPartition(
                DAY,
                verification.report.primary_provider,
                verification.report.primary_revision_id,
                verification.primary_materialization_id,
                proof_id,
                instruments=(INSTRUMENT,),
            ),
        ),
        session_memberships=(member,),
        universe_policy_id=scope["deployment_scope_fingerprint"],
    )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    restored = SimpleNamespace(snapshot=snapshot)
    reads = []

    def admitted_primary(_objects, selected):
        reads.append(selected.dataset_id)
        return restored

    monkeypatch.setattr(datasets, "read_daily_bar_dataset", admitted_primary)
    if mode == "unreadable":
        path = objects._path_for(verification.verification_id)
        path.chmod(0o644)
        path.write_bytes(b"corrupt synthetic verification")
    return (
        objects,
        config,
        policy,
        now,
        scope,
        snapshot,
        ref,
        restored,
        reads,
        verification,
    )


@pytest.mark.parametrize("mode", ["matched", "conflict", "missing", "unreadable"])
def test_existing_seed_cannot_become_ready_from_primary_only_reader(
    monkeypatch, tmp_path, mode
):
    objects, config, _policy, now, scope, snapshot, ref, restored, reads, _ = supply(
        monkeypatch, tmp_path, mode
    )
    catalog = SimpleNamespace(
        path=tmp_path,
        list_daily_bar_datasets=lambda **_: (
            SimpleNamespace(start_date=DAY, end_date=DAY, ref=ref),
        ),
    )

    def run():
        return datasets._existing_forward_seed(
            None,
            config,
            objects,
            catalog,
            dates=(SimpleNamespace(trade_date=DAY.isoformat()),),
            through=DAY,
            latest_through=DAY,
            expected={DAY: (INSTRUMENT,)},
            scope=scope,
            now=now,
            forward_sessions=False,
        )

    if mode == "matched":
        assert run() == {
            "status": "ready",
            "dataset_id": ref.dataset_id,
            "job_ids": [],
            "last_blocker": None,
        }
    elif mode == "missing":
        with pytest.raises(
            datasets.ResearchDatasetError,
            match="dataset_provider_or_policy_unsupported",
        ):
            run()
    else:
        # A sibling that cannot prove agreement is skipped, never promoted to
        # a ready seed and never allowed to abort the caller's workflow.
        assert run() is None
    assert reads == ([] if mode == "missing" else [ref.dataset_id])
    assert not tuple(tmp_path.rglob("*.db"))


@pytest.mark.parametrize("mode", ["matched", "conflict", "missing", "unreadable"])
def test_source_prefix_supply_cannot_reuse_conflict_or_missing_proof(
    monkeypatch, tmp_path, mode
):
    (
        objects,
        _config,
        policy,
        _now,
        _scope,
        snapshot,
        ref,
        restored,
        reads,
        verification,
    ) = supply(monkeypatch, tmp_path, mode)

    def run():
        return datasets._read_forward_seed_supply_prefix(
            objects,
            snapshot,
            ref.dataset_id,
            verification_policy=policy,
            through=DAY,
            current=(INSTRUMENT,),
            identity=verification.verification_id,
        )

    if mode == "matched":
        assert run() is restored
    else:
        expected = (
            "forward_seed_source_prefix_policy_unsupported"
            if mode == "missing"
            else "forward_seed_source_prefix_unreadable"
        )
        with pytest.raises(datasets.ResearchDatasetError, match=expected):
            run()
    assert reads == ([] if mode == "missing" else [ref.dataset_id])
    assert not tuple(tmp_path.rglob("*.db"))


@pytest.mark.parametrize("mode", ["matched", "conflict", "missing", "unreadable"])
def test_completed_job_seed_inputs_reject_conflict_without_publishing(
    monkeypatch, tmp_path, mode
):
    objects, _config, policy, _now, _scope, _snapshot, ref, _restored, reads, _ = (
        supply(monkeypatch, tmp_path, mode)
    )
    planned = SimpleNamespace(
        source_policy_id=policy,
        instruments=(INSTRUMENT,),
        expected_sessions=lambda: (DAY,),
        instruments_for_session=lambda day: (INSTRUMENT,),
    )
    job = SimpleNamespace(result_ref=f"dataset:{ref.dataset_id}")
    if mode == "matched":
        assert set(datasets._verified_job_daily_snapshots(objects, job, planned)) == {
            DAY
        }
    else:
        with pytest.raises(datasets.ResearchDatasetError):
            datasets._verified_job_daily_snapshots(objects, job, planned)
    assert reads == [ref.dataset_id]
    assert not tuple(tmp_path.rglob("*.db"))


@pytest.mark.parametrize("mode", ["matched", "conflict", "strict_reader_conflict"])
def test_fresh_seed_cold_read_precedes_completed_origin(monkeypatch, tmp_path, mode):
    """The public preparation caller cannot complete a freshly conflicted seed."""
    from dataclasses import replace
    from datetime import date

    from data.dataset.model import DatasetRef
    from data.dataset.reader import read_daily_bar_dataset
    from data.market.reconciliation import (
        STRICT_DAILY_RECONCILIATION,
        reconcile_daily_bar_revisions,
    )
    from data.market.verification_evidence import publish_market_verification_evidence
    from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
    from data.providers.tushare import TUSHARE_DAILY_BAR_DESCRIPTOR
    from server.persistence.automation_runs import AutomationRunRepository
    from server.persistence.jobs import SQLiteJobStore
    from server.services.market.verified_daily_market_jobs import (
        VERIFIED_DAILY_MARKET_JOB,
    )
    from tests.server.test_forward_verified_union import union_seed
    from tests.server.test_verified_interval_dataset import NOW, _side, _verified_day

    db, market, config, source, objects, _prefix, current = union_seed(tmp_path)
    pending = datasets.ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market
    )
    assert pending["status"] == "waiting" and len(pending["job_ids"]) == 1
    jobs = SQLiteJobStore(db.path)
    job = jobs.get(pending["job_ids"][0])
    day = date.fromisoformat(job.payload["trade_date"])
    suffix = _verified_day(tmp_path / "research", day, instruments=current)
    claimed = jobs.claim(
        VERIFIED_DAILY_MARKET_JOB, "fixture", now=NOW, job_id=job.job_id
    )
    jobs.finish(claimed.lease, now=NOW, result_ref=f"dataset:{suffix.dataset_id}")
    origins = AutomationRunRepository(db.path)
    before = origins.list_automation_runs_sync(
        run_type="forward_seed_preparation", limit=20
    )
    publisher = datasets._publish_forward_seed
    substituted = {}
    fresh_reads = []

    def publish(*args, **kwargs):
        summary = publisher(*args, **kwargs)
        restored = read_daily_bar_dataset(
            objects, DatasetRef(objects.resolve_ref(summary["dataset_id"]))
        )
        if mode != "matched":
            primary = _side(objects, day, TDX_PROVIDER_DESCRIPTOR, instruments=current)
            comparison = _side(
                objects,
                day,
                TUSHARE_DAILY_BAR_DESCRIPTOR,
                instruments=current,
                close="10.49",
            )
            proof = publish_market_verification_evidence(
                objects,
                report=reconcile_daily_bar_revisions(
                    objects,
                    primary_revision=primary[0],
                    primary_materialization=primary[1],
                    comparison_revision=comparison[0],
                    comparison_materialization=comparison[1],
                    policy=STRICT_DAILY_RECONCILIATION,
                ),
                primary_quality=primary[2],
                comparison_quality=comparison[2],
                primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
                comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
                policy=STRICT_DAILY_RECONCILIATION,
                checked_at=NOW,
            )
            part = restored.snapshot.partitions[-1]
            assert (part.revision_id, part.materialization_id) == (
                proof.report.primary_revision_id,
                proof.primary_materialization_id,
            )
            snapshot = replace(
                restored.snapshot,
                partitions=(
                    *restored.snapshot.partitions[:-1],
                    replace(part, verification_id=proof.verification_id),
                ),
            )
            conflict_ref = publish_daily_bar_dataset_manifest(objects, snapshot)
            substituted[conflict_ref.dataset_id] = SimpleNamespace(snapshot=snapshot)
            summary = {**summary, "dataset_id": conflict_ref.dataset_id}
        substituted["fresh_id"] = summary["dataset_id"]
        return summary

    def reader(store, ref, **kwargs):
        if ref.dataset_id == substituted.get("fresh_id"):
            fresh_reads.append(ref.dataset_id)
        if mode == "conflict" and ref.dataset_id in substituted:
            return substituted[ref.dataset_id]
        return read_daily_bar_dataset(store, ref, **kwargs)

    monkeypatch.setattr(datasets, "_publish_forward_seed", publish)
    monkeypatch.setattr(datasets, "read_daily_bar_dataset", reader)
    result = datasets.ensure_forward_seed_for_source(
        db, config, source=source, now=NOW, data_store=market
    )
    after = origins.list_automation_runs_sync(
        run_type="forward_seed_preparation", limit=20
    )
    assert fresh_reads == [substituted["fresh_id"]]
    if mode == "strict_reader_conflict":
        assert result["status"] == "blocked"
        assert (
            result["last_blocker"]["code"] == "dataset_reader_verification_not_matched"
        )
        assert after == before
    elif mode == "conflict":
        assert result["status"] != "ready"
        assert result["last_blocker"]["code"] == "observation_verification_not_matched"
        assert after == before  # In particular, no completed origin write.
    else:
        assert result["status"] == "ready", result
        assert any(
            row["status"] == "completed" and row["source_ref"] == result["dataset_id"]
            for row in after
        )
