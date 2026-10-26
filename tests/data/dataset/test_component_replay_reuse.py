"""The Dataset consumes its own verified replay, never a prior read's trust."""

from __future__ import annotations

import pytest

from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DailyBarDatasetPartition, DailyBarDatasetSnapshot
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market.verification_evidence import (
    read_market_verification_evidence,
    read_market_verification_evidence_with_component_bars,
)
from tests.data.market.test_bse_auction_relation import CHECKED
from tests.data.market.test_bse_auction_relation import pair as native_pair  # noqa: F401
from tests.data.market.test_bse_tencent_reported_relation import (
    pair as tencent_pair,  # noqa: F401
)


def _dataset(p, evidence):
    revision, materialization = p["revisions"][0]
    bar = p.get("tencent", p["sina"])
    return publish_daily_bar_dataset_manifest(
        p["store"],
        DailyBarDatasetSnapshot(
            start_date=bar.session_date,
            end_date=bar.session_date,
            cutoff=CHECKED,
            instruments=(bar.instrument,),
            resolver_policy_id="fixture.component_replay.v1",
            market_schema_version=DAILY_BAR_SCHEMA_VERSION,
            partitions=(
                DailyBarDatasetPartition(
                    bar.session_date,
                    revision.provider,
                    revision.ref.revision_id,
                    materialization.materialization_id,
                    verification_id=evidence.verification_id,
                ),
            ),
        ),
    )


@pytest.mark.parametrize("fixture", ["native_pair", "tencent_pair"])
def test_dataset_reuses_current_verified_component_bars_and_rechecks_next_read(
    request, fixture, monkeypatch
):
    import data.market.reconciliation as reconciliation

    p = request.getfixturevalue(fixture)()
    evidence = p["publish"]()
    ref = _dataset(p, evidence)
    serialized = p["store"].read_bytes(evidence.ref)
    calls = []
    reconcile = reconciliation.reconcile_daily_bar_revisions_with_bars

    def counted(*args, **kwargs):
        result = reconcile(*args, **kwargs)
        calls.append(result)
        return result

    monkeypatch.setattr(
        reconciliation, "reconcile_daily_bar_revisions_with_bars", counted
    )
    expected = p["official"] if fixture == "tencent_pair" else p["sina"]
    for count in (1, 2):
        assert read_daily_bar_dataset(p["store"], ref).bars == (expected,)
        assert len(calls) == count
        assert calls[-1][0] == evidence.report
        assert calls[-1][1] == (expected,)

    actual, bars = read_market_verification_evidence_with_component_bars(
        p["store"], evidence.ref
    )
    assert actual == evidence
    assert bars == calls[-1][1:]
    assert len(calls) == 3
    assert read_market_verification_evidence(p["store"], evidence.ref) == evidence
    assert len(calls) == 4
    assert p["store"].read_bytes(evidence.ref) == serialized


@pytest.mark.parametrize("fixture", ["native_pair", "tencent_pair"])
@pytest.mark.parametrize("target", ["primary_quality_id", "materialization", "raw"])
def test_new_cold_read_rejects_corrupted_component_dependencies(
    request, fixture, target
):
    p = request.getfixturevalue(fixture)()
    evidence = p["publish"]()
    ref = _dataset(p, evidence)
    assert len(read_daily_bar_dataset(p["store"], ref).bars) == 1
    store = p["store"]
    if target == "materialization":
        object_id = p["revisions"][0][1].manifest_ref.object_id
    elif target == "raw":
        capture = p["official_cap"] if fixture == "tencent_pair" else p["sina_cap"]
        object_id = capture.raw_object_ref.object_id
    else:
        object_id = getattr(evidence, target)
    # Corruption is confined to the sanitized temporary fixture object store.
    path = store._path_for(object_id)
    path.chmod(0o644)
    path.write_bytes(b"corrupted")
    with pytest.raises(DatasetReaderIntegrityError):
        read_daily_bar_dataset(store, ref)
