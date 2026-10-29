"""A complete feature pool needs dated exclusions, not only observed bars."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import serialize_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    dataset_cross_section_memberships,
)
from data.market.capture import (
    capture_provider_payload,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.providers.eastmoney import read_official_stock_master_captures
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.storage.objects import ContentAddressedObjectStore
from data.store import (
    normalize_stock_master_metadata,
    require_stock_master_capture_evidence,
)
from server.services.market.market_universe_truth import normalize_a_share_members
from tests.data.dataset.test_bse_official_activity import (
    DAYS as BSE_DAYS,
)
from tests.data.dataset.test_bse_official_activity import (
    KEYS as BSE_KEYS,
)
from tests.data.dataset.test_bse_official_activity import (
    _capture as bse_capture,
)
from tests.data.dataset.test_bse_official_activity import (
    _inputs as bse_inputs,
)
from tests.data.dataset.test_bse_official_activity import (
    _row as bse_row,
)
from tests.data.dataset.test_historical_session_status import (
    CAPTURED_AT,
    DAYS,
    KEYS,
    MASTER_AT,
)
from tests.data.dataset.test_historical_session_status import (
    _inputs as bao_inputs,
)
from tests.data.providers.test_official_stock_master import _capture as official_capture
from tests.server.test_verified_interval_dataset import DAYS as OFFICIAL_DAYS
from tests.server.test_verified_interval_dataset import _side

ERROR = "dataset_cross_section_membership_invalid"


def _metadata_inputs(
    tmp_path, *, source="bao", mutate=None, status_mutate=None, active_record_count=None
):
    if source == "bse":
        objects, snapshot, old_master, capture = bse_inputs(tmp_path)
    else:
        objects, snapshot, old_master, capture = bao_inputs(
            tmp_path,
            mutate=status_mutate,
            capture_overrides=(
                {"record_count": active_record_count}
                if active_record_count is not None
                else None
            ),
        )
    master = json.loads(objects.read_bytes(old_master))
    master.update(
        schema_version="karkinos.market_universe_snapshot.v3",
        trade_date_role="daily_bar_window_end",
        historical_membership_verified=False,
        member_metadata=[
            {
                "symbol": key.symbol,
                "display_name": "Fixture Company",
                "list_status": "L",
                "list_date": "2010-01-01",
            }
            for key in snapshot.instruments
        ],
    )
    if mutate is not None:
        mutate(master)
    master_ref = objects.put_bytes(json.dumps(master).encode())
    snapshot = replace(
        snapshot,
        session_memberships=tuple(
            replace(
                member,
                source_observation_ids=tuple(
                    master_ref.object_id if ref == old_master.object_id else ref
                    for ref in member.source_observation_ids
                ),
            )
            for member in snapshot.session_memberships
        ),
    )
    return objects, snapshot, master_ref, capture


def _prelisting_and_bao_zero(tmp_path):
    def newly_listed(master):
        master["member_metadata"][1]["list_date"] = str(DAYS[1])

    objects, snapshot, master, capture = _metadata_inputs(
        tmp_path,
        mutate=newly_listed,
        status_mutate=lambda request, raw: raw["calls"][1]["rows"].pop(0),
        active_record_count=2,
    )
    snapshot = replace(
        snapshot,
        partitions=(
            replace(snapshot.partitions[0], instruments=KEYS[:1]),
            snapshot.partitions[1],
        ),
        session_memberships=(
            replace(snapshot.session_memberships[0], instruments=KEYS[:1]),
            snapshot.session_memberships[1],
        ),
    )
    return objects, snapshot, master, capture


def _damaged(snapshot, **changes):
    """Exercise read-boundary rejection after bypassing constructor guards."""
    damaged = copy.copy(snapshot)
    for name, value in changes.items():
        object.__setattr__(damaged, name, value)
    return damaged


def test_prelisting_and_explicit_bao_zero_cover_the_declared_pool(tmp_path):
    objects, snapshot, master, _ = _prelisting_and_bao_zero(tmp_path)
    original = serialize_daily_bar_dataset_manifest(snapshot)
    original_master = objects.read_bytes(master)
    expected = {DAYS[0]: KEYS[:1], DAYS[1]: KEYS[1:]}

    assert (
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)
        == expected
    )
    assert (
        dataset_cross_section_memberships(objects, snapshot, as_of=CAPTURED_AT)
        == expected
    )
    assert serialize_daily_bar_dataset_manifest(snapshot) == original
    assert objects.read_bytes(master) == original_master
    assert all(member.decision_at is None for member in snapshot.session_memberships)
    assert snapshot.membership_evidence_bound is False


def test_bse_zero_activity_covers_absence_without_inventing_a_traded_member(tmp_path):
    objects, snapshot, _, _ = _metadata_inputs(tmp_path, source="bse")
    assert dataset_cross_section_memberships(
        objects, snapshot, allow_retrospective=True
    ) == {BSE_DAYS[0]: BSE_KEYS, BSE_DAYS[1]: BSE_KEYS[1:]}
    assert snapshot.session_memberships[1].instruments == BSE_KEYS[1:]
    assert snapshot.session_memberships[1].decision_at is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"as_of": CAPTURED_AT.replace(tzinfo=None)},
        {"as_of": CAPTURED_AT.replace(tzinfo=None), "allow_retrospective": True},
        {"as_of": MASTER_AT},
        {"as_of": MASTER_AT, "allow_retrospective": True},
    ],
)
def test_as_of_requires_explicit_mode_and_actual_source_availability(tmp_path, kwargs):
    objects, snapshot, _, _ = _metadata_inputs(tmp_path)
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, **kwargs)


def test_late_current_master_cannot_become_historical_pit_by_opt_in(tmp_path):
    objects, snapshot, _, _ = _metadata_inputs(tmp_path)
    historical_as_of = MASTER_AT.replace(year=2020)
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(
            objects,
            snapshot,
            as_of=historical_as_of,
            allow_retrospective=True,
        )


@pytest.mark.parametrize(
    "case", ["missing", "invalid", "duplicate", "prelisting_conflict"]
)
def test_missing_or_conflicting_listing_facts_never_shrink_the_pool(tmp_path, case):
    def mutate(master):
        row = master["member_metadata"][0]
        if case == "missing":
            row.pop("list_date")
        elif case == "invalid":
            row["list_date"] = "unknown"
        elif case == "duplicate":
            master["member_metadata"].append(dict(row))
        else:
            row["list_date"] = str(DAYS[-1] + timedelta(days=1))

    objects, snapshot, _, _ = _metadata_inputs(tmp_path, mutate=mutate)
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


def test_missing_post_listing_status_stays_unknown_instead_of_available_only(tmp_path):
    objects, snapshot, old_master, capture = bao_inputs(
        tmp_path, mutate=lambda request, raw: raw["calls"][0]["rows"].pop()
    )
    master = json.loads(objects.read_bytes(old_master))
    master["member_metadata"] = [
        {"symbol": key.symbol, "list_date": "2010-01-01"} for key in KEYS
    ]
    master_ref = objects.put_bytes(json.dumps(master).encode())
    snapshot = replace(
        snapshot,
        session_memberships=tuple(
            replace(
                member,
                source_observation_ids=(master_ref.object_id, capture.capture_id),
            )
            for member in snapshot.session_memberships
        ),
    )
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


def test_two_bound_masters_must_agree_on_listing_metadata(tmp_path):
    objects, snapshot, master_ref, _ = _metadata_inputs(tmp_path)
    conflicting = json.loads(objects.read_bytes(master_ref))
    conflicting["member_metadata"][0]["list_date"] = "2011-01-01"
    counter = objects.put_bytes(json.dumps(conflicting).encode())
    snapshot = replace(
        snapshot,
        session_memberships=tuple(
            replace(
                member,
                source_observation_ids=(
                    *member.source_observation_ids,
                    counter.object_id,
                ),
            )
            for member in snapshot.session_memberships
        ),
    )
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


@pytest.mark.parametrize(
    "case", ["missing_session", "duplicate_session", "missing_refs", "availability"]
)
def test_session_coverage_and_bound_sources_are_required(tmp_path, case):
    objects, snapshot, _, _ = _metadata_inputs(tmp_path)
    members = snapshot.session_memberships
    if case == "missing_session":
        snapshot = _damaged(snapshot, session_memberships=members[:1])
    elif case == "duplicate_session":
        snapshot = _damaged(snapshot, session_memberships=(members[0], members[0]))
    elif case == "missing_refs":
        snapshot = replace(
            snapshot,
            session_memberships=(
                replace(members[0], source_observation_ids=()),
                members[1],
            ),
        )
    else:
        snapshot = replace(
            snapshot,
            session_memberships=(
                replace(members[0], available_at=MASTER_AT),
                members[1],
            ),
        )
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


def test_maintenance_rows_do_not_establish_traded_pool_membership(tmp_path):
    objects, snapshot, _, _ = _metadata_inputs(tmp_path)
    snapshot = replace(
        snapshot,
        session_memberships=(
            replace(
                snapshot.session_memberships[0],
                instruments=KEYS[:1],
                maintenance_instruments=KEYS[1:],
            ),
            snapshot.session_memberships[1],
        ),
    )
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


def test_conflicting_bse_activity_is_not_resolved_by_capture_order(tmp_path):
    objects, snapshot, _, _ = _metadata_inputs(tmp_path, source="bse")
    active = bse_capture(objects, rows=[bse_row(day, traded=True) for day in BSE_DAYS])
    snapshot = replace(
        snapshot,
        session_memberships=tuple(
            replace(
                member,
                source_observation_ids=(
                    *member.source_observation_ids,
                    active.capture_id,
                ),
            )
            for member in snapshot.session_memberships
        ),
    )
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


def test_later_cold_read_detects_changed_raw_status_bytes(tmp_path):
    objects, snapshot, _, capture = _metadata_inputs(tmp_path)
    expected = {DAYS[0]: KEYS, DAYS[1]: KEYS[1:]}
    assert (
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)
        == expected
    )

    digest = capture.raw_object_ref.digest
    raw_path = objects.root / "sha256" / digest[:2] / digest[2:]
    raw_path.chmod(0o644)
    raw_path.write_bytes(b"tampered synthetic fixture")
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


def test_retrospective_mode_still_respects_the_frozen_dataset_cutoff(tmp_path):
    objects, snapshot, _, _ = _metadata_inputs(tmp_path)
    snapshot = _damaged(snapshot, cutoff=MASTER_AT)
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)


def test_optional_master_activity_preserves_default_projection_and_actual_query_day(
    tmp_path,
):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    _, refs, _, _ = official_capture(objects)
    query_day = OFFICIAL_DAYS[-1]
    default = read_official_stock_master_captures(
        objects, refs, trade_date=str(query_day)
    )
    activity = {}
    with_activity = read_official_stock_master_captures(
        objects, refs, trade_date=str(query_day), dated_activity=activity
    )
    assert with_activity == default
    assert activity == {
        query_day: {
            InstrumentKey("000001", InstrumentType.STOCK): "0",
            InstrumentKey("600000", InstrumentType.STOCK): "1",
        }
    }
    metadata = {row["symbol"]: row for row in default[0]}
    assert metadata["000001"]["trade_status"] == "0"
    assert metadata["000001"]["status_session_date"] == str(query_day)
    assert "trade_status" not in metadata["600000"]


def test_verified_master_raw_positive_activity_conflicts_with_prelisting(tmp_path):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    _, original_refs, _, _ = official_capture(objects)
    status_day = OFFICIAL_DAYS[-1]
    listing_day = status_day + timedelta(days=1)
    refs = []
    for identity in original_refs:
        capture = read_provider_capture(objects, objects.resolve_ref(identity))
        request = json.loads(capture.request_json)
        if capture.provider == "sse" and request["params"]["STOCK_TYPE"] == "1":
            payload = json.loads(read_provider_raw_payload(objects, capture))
            target = next(
                row for row in payload["result"] if row["A_STOCK_CODE"] == "600000"
            )
            target["LIST_DATE"] = listing_day.strftime("%Y%m%d")
            capture = capture_provider_payload(
                objects,
                provider=capture.provider,
                operation=capture.operation,
                request=request,
                raw_payload=json.dumps(payload).encode(),
                payload_format=capture.payload_format,
                adapter_version=capture.adapter_version,
                started_at=capture.started_at,
                completed_at=capture.completed_at,
                record_count=capture.record_count,
            )
        refs.append(capture.capture_id)
    rows, started, completed = read_official_stock_master_captures(
        objects, refs, trade_date=str(status_day)
    )
    members = normalize_a_share_members([row["symbol"] for row in rows])
    master = {
        "schema_version": "karkinos.market_universe_snapshot.v3",
        "trade_date": str(status_day),
        "membership_basis": "current_active_stock_master",
        "availability_basis": "capture_completed_at",
        "observation_basis": "adapter_response",
        "capture_started_at": started.isoformat(),
        "capture_completed_at": completed.isoformat(),
        "available_at": completed.isoformat(),
        "members": members,
        "member_metadata": normalize_stock_master_metadata(rows, members),
        "source_capture_ids": sorted(refs),
    }
    # This is an exact, raw-verified projection. Its canonical owner currently
    # retains roster status 0, while status 1 remains in the bound raw capture.
    require_stock_master_capture_evidence(objects, master)
    target = next(row for row in master["member_metadata"] if row["symbol"] == "600000")
    assert target["list_date"] == str(listing_day)
    assert "trade_status" not in target
    master_ref = objects.put_bytes(json.dumps(master).encode())
    partitions = []
    memberships = []
    for day, selected in ((status_day, KEYS[1:]), (listing_day, KEYS)):
        revision, materialization, _ = _side(
            objects, day, TDX_PROVIDER_DESCRIPTOR, instruments=selected
        )
        partitions.append(
            DailyBarDatasetPartition(
                day,
                revision.provider,
                revision.ref.revision_id,
                materialization.materialization_id,
                instruments=selected,
            )
        )
        memberships.append(
            DailyBarDatasetMembership(day, selected, completed, (master_ref.object_id,))
        )
    snapshot = DailyBarDatasetSnapshot(
        start_date=status_day,
        end_date=listing_day,
        cutoff=completed,
        instruments=KEYS,
        resolver_policy_id="fixture.exploratory.v1",
        market_schema_version=revision.market_schema_version,
        partitions=tuple(partitions),
        session_memberships=tuple(memberships),
        universe_policy_id="fixture.current_survivor_minus_explicit_nontrading.v1",
    )
    with pytest.raises(DatasetReaderIntegrityError, match=ERROR):
        dataset_cross_section_memberships(objects, snapshot, allow_retrospective=True)
