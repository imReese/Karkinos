"""Exact verified source unions enter research through the normal strict loader."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pandas as pd
import pytest

from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.reader import read_daily_bar_dataset
from data.market.verification_evidence import read_market_verification_evidence
from data.store import DataStore
from server.services.market.market_universe_truth import normalize_a_share_members
from server.services.research import dataset_inputs as inputs
from server.services.research.datasets import ResearchDatasetError
from tests.server.test_backtest_dataset_inputs import _mixed, _request
from tests.server.test_deployment_scope_datasets import _composed
from tests.server.test_verified_interval_dataset import NOW


def _verified_union(tmp_path):
    store, original = _composed(tmp_path)
    master = DataStore(tmp_path / "master").save_market_universe_snapshot(
        trade_date=original.snapshot.end_date.isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members(
            [key.symbol for key in original.snapshot.instruments]
        ),
        capture_started_at=NOW - timedelta(seconds=1),
        capture_completed_at=NOW,
    )
    master_id = bind_stock_master_observation(store, master)
    last = original.snapshot.partitions[-1]
    verification = read_market_verification_evidence(
        store, store.resolve_ref(last.verification_id)
    )
    comparison = replace(
        last,
        provider=verification.report.comparison_provider,
        revision_id=verification.report.comparison_revision_id,
        materialization_id=verification.comparison_materialization_id,
    )
    ref = publish_daily_bar_dataset_manifest(
        store,
        replace(
            original.snapshot,
            cutoff=NOW,
            resolver_policy_id="karkinos.dataset.explicit_verified_source_union.v1",
            partitions=(*original.snapshot.partitions[:-1], comparison),
            session_memberships=tuple(
                replace(item, available_at=NOW, source_observation_ids=(master_id,))
                for item in original.snapshot.session_memberships
            ),
        ),
    )
    return store, read_daily_bar_dataset(store, ref)


def test_explicit_verified_union_loader_preserves_source_values_and_provenance(
    tmp_path,
):
    store, result = _verified_union(tmp_path)
    identities = {
        identity
        for part in result.snapshot.partitions
        for identity in (
            part.revision_id,
            part.materialization_id,
            part.verification_id,
        )
    }
    before = {
        identity: store.read_bytes(store.resolve_ref(identity))
        for identity in identities
    }

    instruments, handlers, binding = inputs.load_dataset_backtest_inputs(
        store.root.parent, _request(result)
    )

    assert (
        list(instruments)
        == list(handlers)
        == [key.symbol for key in result.snapshot.instruments]
    )
    columns = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "available_at",
        "captured_at",
    ]
    for key in result.snapshot.instruments:
        expected = pd.DataFrame(
            [
                [getattr(bar, field) for field in ["event_time", *columns[1:]]]
                for bar in result.bars
                if bar.instrument == key
            ],
            columns=columns,
        )
        expected.attrs.update(
            provider_name=None,
            data_source=None,
            adjustment_mode="none",
            dataset_id=result.ref.dataset_id,
        )
        pd.testing.assert_frame_equal(
            handlers[key.symbol]._df, expected, check_exact=True
        )
        assert all(
            isinstance(value, Decimal)
            for column in columns[1:7]
            for value in handlers[key.symbol]._df[column]
        )
    assert before == {
        identity: store.read_bytes(store.resolve_ref(identity))
        for identity in identities
    }
    assert read_daily_bar_dataset(store, result.ref) == result
    assert binding["dataset_id"] == result.ref.dataset_id
    assert binding["cutoff"] == result.snapshot.cutoff.isoformat()
    assert binding["source_names"] == ["tdx", "tushare"]
    assert binding["cross_source_verified"] is True
    assert binding["offline_replay"] is True
    assert binding["point_in_time_verified"] is False
    assert binding["decision_availability"]["status"] == "blocked"


@pytest.mark.parametrize(
    "failure",
    [
        "unknown_policy",
        "policy_suffix",
        "no_verification",
        "no_dated",
        "missing_membership_evidence",
    ],
)
def test_explicit_union_loader_rejects_unsupported_or_incomplete_inputs(
    tmp_path, failure
):
    store, result = _verified_union(tmp_path)
    snapshot = result.snapshot
    if failure in {"unknown_policy", "policy_suffix"}:
        snapshot = replace(
            snapshot,
            resolver_policy_id=(
                "karkinos.dataset.explicit_verified_source_union.v2"
                if failure == "unknown_policy"
                else "karkinos.dataset.explicit_verified_source_union.v1:other_policy"
            ),
        )
    elif failure == "no_verification":
        snapshot = replace(
            snapshot,
            partitions=tuple(
                replace(part, verification_id=None) for part in snapshot.partitions
            ),
        )
    elif failure == "missing_membership_evidence":
        snapshot = replace(
            snapshot,
            session_memberships=(
                replace(snapshot.session_memberships[0], source_observation_ids=()),
                *snapshot.session_memberships[1:],
            ),
        )
    else:
        # A valid unsharded manifest reaches the product admission check.
        # Malformed dated shards are already rejected by the Dataset model.
        original = _mixed(store.root.parent)
        snapshot = replace(
            original.snapshot,
            resolver_policy_id="karkinos.dataset.explicit_verified_source_union.v1",
        )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    unsupported = replace(result, ref=ref, snapshot=snapshot)
    with pytest.raises(
        ResearchDatasetError, match="^dataset_provider_or_policy_unsupported$"
    ):
        inputs.load_dataset_backtest_inputs(store.root.parent, _request(unsupported))


@pytest.mark.parametrize("damage", ["foreign_verification", "corrupt_verification"])
def test_explicit_union_loader_replays_verification_before_admission(tmp_path, damage):
    store, result = _verified_union(tmp_path)
    if damage == "foreign_verification":
        first, *rest = result.snapshot.partitions
        ref = publish_daily_bar_dataset_manifest(
            store,
            replace(
                result.snapshot,
                partitions=(
                    replace(first, verification_id=rest[-1].verification_id),
                    *rest,
                ),
            ),
        )
        result = replace(result, ref=ref)
    else:
        path = store._path_for(result.snapshot.partitions[0].verification_id)
        path.chmod(0o644)
        path.write_bytes(b"corrupt fixture verification")
    with pytest.raises(
        ResearchDatasetError, match="^dataset_unreadable_no_remote_fallback$"
    ):
        inputs.load_dataset_backtest_inputs(store.root.parent, _request(result))


def test_explicit_union_requires_complete_explicit_dated_shards(tmp_path):
    _, result = _verified_union(tmp_path)
    first, *rest = result.snapshot.partitions
    with pytest.raises(ValueError, match="^dataset_shard_instruments_required$"):
        replace(
            result.snapshot,
            partitions=(replace(first, instruments=()), *rest),
        )
