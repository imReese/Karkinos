import json
import sqlite3
from dataclasses import asdict

import pytest

from data.dataset_catalog import DatasetCatalog, DatasetRef


def _inputs():
    common = dict(
        symbol="600001",
        instrument_type="stock",
        session_date="2026-09-04",
        event_time="2026-09-04T15:00:00+08:00",
        available_at="2026-09-04T15:01:00+08:00",
        captured_at="2026-09-05T10:00:00+08:00",
        source_revision="fixture-revision-1",
        availability_evidence_ref="fixture:historical-source-record",
        suspended=False,
    )
    return dict(
        universe=[
            dict(
                common,
                membership_status="member",
                listed_on="2000-01-01",
                delisted_on=None,
            )
        ],
        daily=[
            dict(
                common,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.5,
                volume=1000.0,
                amount=10500.0,
                adjustment_factor=1.0,
            )
        ],
        cutoff="2026-09-05T10:00:00+08:00",
        expected_sessions=["2026-09-04"],
        published_at="2026-09-05T10:01:00+08:00",
    )


def test_publish_reopen_replay_and_availability_cutoff(tmp_path):
    catalog = DatasetCatalog(tmp_path)
    manifest = catalog.publish_daily(**_inputs())
    reopened = DatasetCatalog(tmp_path)
    assert reopened.get(manifest.ref) == manifest
    assert (
        reopened.publish_daily(
            **{**_inputs(), "published_at": "2026-09-05T10:02:00+08:00"}
        )
        == manifest
    )
    assert reopened.read(manifest.ref, "daily").num_rows == 1
    with pytest.raises(ValueError, match="as_of_generation_incomplete"):
        reopened.read_as_of(manifest.ref, "daily", as_of="2026-09-04T15:00:00+08:00")
    revised = _inputs()
    revised["daily"][0]["close"] = 10.6
    revised["daily"][0]["source_revision"] = "fixture-revision-2"
    next_manifest = reopened.publish_daily(**revised)
    assert next_manifest.ref != manifest.ref
    assert reopened.read(manifest.ref, "daily")["close"].to_pylist() == [10.5]


@pytest.mark.parametrize(
    "change,match",
    [
        (
            lambda x: x["daily"][0].update(available_at="2026-09-06T10:00:00+08:00"),
            "time_semantics",
        ),
        (lambda x: x["universe"][0].update(listed_on="2026-09-05"), "before_listing"),
        (lambda x: x["daily"].append(x["daily"][0]), "duplicate"),
        (lambda x: x["daily"][0].update(symbol="600002"), "coverage_mismatch"),
        (lambda x: x["daily"][0].update(close=float("nan")), "invalid_close"),
        (
            lambda x: x["daily"][0].pop("availability_evidence_ref"),
            "availability_evidence_ref",
        ),
        (lambda x: x["expected_sessions"].append("2026-09-03"), "session_coverage"),
        (
            lambda x: x["daily"][0].update(captured_at="2026-09-06T10:00:00+08:00"),
            "capture_after_publication",
        ),
    ],
)
def test_bad_candidate_preserves_current_manifest(tmp_path, change, match):
    catalog = DatasetCatalog(tmp_path)
    before = catalog.publish_daily(**_inputs())
    candidate = _inputs()
    change(candidate)
    with pytest.raises(ValueError, match=match):
        catalog.publish_daily(**candidate)
    with sqlite3.connect(catalog.path) as conn:
        assert (
            conn.execute("SELECT dataset_id FROM dataset_current").fetchone()[0]
            == before.ref.dataset_id
        )
    assert catalog.read(before.ref, "daily").num_rows == 1


def test_content_and_manifest_tampering_fail_closed(tmp_path):
    catalog = DatasetCatalog(tmp_path)
    manifest = catalog.publish_daily(**_inputs())
    path = catalog._partition_path(manifest.partitions["daily"])
    path.chmod(0o644)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="digest_mismatch"):
        catalog.read(manifest.ref, "daily")
    with sqlite3.connect(catalog.path) as conn:
        changed = asdict(manifest)
        changed["cutoff"] = "2027-01-01T00:00:00+00:00"
        conn.execute(
            "UPDATE dataset_manifests SET manifest_json=?", (json.dumps(changed),)
        )
    with pytest.raises(ValueError, match="manifest_digest_mismatch"):
        catalog.get(manifest.ref)


def test_read_does_not_create_catalog(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        DatasetCatalog(tmp_path).get(DatasetRef("a" * 64))
    assert not list(tmp_path.iterdir())


def test_as_of_requires_complete_joint_generation_after_revision(tmp_path):
    catalog = DatasetCatalog(tmp_path)
    before = catalog.publish_daily(**_inputs())
    revised = _inputs()
    revised["daily"][0].update(
        available_at="2026-09-05T09:00:00+08:00", source_revision="revision-2"
    )
    after = catalog.publish_daily(**revised)
    as_of = "2026-09-04T16:00:00+08:00"
    assert catalog.read_as_of(before.ref, "daily", as_of=as_of).num_rows == 1
    for partition in ("daily", "universe"):
        with pytest.raises(ValueError, match="as_of_generation_incomplete"):
            catalog.read_as_of(after.ref, partition, as_of=as_of)
