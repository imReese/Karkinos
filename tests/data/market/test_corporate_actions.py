from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from data.market.capture import read_provider_capture
from data.market.corporate_actions import (
    CorporateActionObservationError,
    read_corporate_action_observation,
    summarize_corporate_action_observation,
)
from data.storage.objects import ContentAddressedObjectStore, ObjectRef
from tests.data.providers.test_tushare_corporate_actions import (
    NOW,
    FakePro,
    collect,
    dividend_frame,
)


def test_new_capture_reuses_facts_but_revision_preserves_old_observation(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    first_ref = collect(store, FakePro())
    again_ref = collect(store, FakePro(), now=NOW + timedelta(days=1))
    changed = dividend_frame()
    changed.loc[0, "cash_div_tax"] = 0.6
    revised_ref = collect(store, FakePro(changed), now=NOW + timedelta(days=2))
    first, again, revised = [
        read_corporate_action_observation(store, ref)
        for ref in (first_ref, again_ref, revised_ref)
    ]
    assert first_ref != again_ref != revised_ref
    assert first["facts_revision_id"] == again["facts_revision_id"]
    assert revised["facts_revision_id"] != first["facts_revision_id"]
    assert revised["records"][0]["cash_dividend_before_tax"] == "0.6"
    assert read_corporate_action_observation(store, first_ref) == first
    assert first["records"][0]["cash_dividend_before_tax"] == "0.5"


def test_offline_summary_separates_dates_from_availability_and_keeps_undated_plan(
    tmp_path,
):
    frame = dividend_frame()
    plan = frame.iloc[0].to_dict()
    plan.update(div_proc="预案", end_date="20261231", ann_date="20260901")
    for field in (
        "imp_ann_date",
        "record_date",
        "ex_date",
        "pay_date",
        "div_listdate",
        "base_date",
    ):
        plan[field] = None
    frame = pd.concat([frame, pd.DataFrame([plan])], ignore_index=True)
    store = ContentAddressedObjectStore(tmp_path)
    ref = collect(store, FakePro(frame))
    observation = read_corporate_action_observation(
        ContentAddressedObjectStore(tmp_path), ref
    )
    summary = summarize_corporate_action_observation(
        observation,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )
    assert summary["total_record_count"] == 2
    assert summary["matched_event_count"] == 1
    assert summary["undated_event_count"] == 1
    assert len(summary["events"]) == 2
    assert {event["div_proc"] for event in summary["events"]} == {"实施", "预案"}
    for event in summary["events"]:
        assert event["available_at"] == NOW.isoformat()
        assert event["source_revision_id"] == observation["facts_revision_id"]
        assert event["observation_id"] == ref.object_id
    assert summary["historical_availability_verified"] is False
    assert summary["returns_modeled"] is False


def test_reader_rejects_rebound_capture_even_when_objects_have_valid_hashes(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    first_ref = collect(store, FakePro())
    later_ref = collect(store, FakePro(), now=NOW + timedelta(days=1))
    first = json.loads(store.read_bytes(first_ref))
    later = json.loads(store.read_bytes(later_ref))
    first["capture_ref"] = later["capture_ref"]
    forged = store.put_bytes(
        json.dumps(
            first, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    with pytest.raises(CorporateActionObservationError, match="binding_invalid"):
        read_corporate_action_observation(store, forged)


def test_reader_checks_raw_capture_bytes_and_not_only_manifest(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    ref = collect(store, FakePro())
    observed = read_corporate_action_observation(store, ref)
    capture = read_provider_capture(store, store.resolve_ref(observed["capture_id"]))
    raw_path = store._path_for(capture.raw_object_ref.object_id)
    raw_path.chmod(0o644)
    raw_path.write_bytes(b"corrupt fixture")
    with pytest.raises(CorporateActionObservationError, match="unreadable"):
        read_corporate_action_observation(store, ref)


def test_reader_reports_decimal_overflow_as_public_observation_error(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    ref = collect(store, FakePro())
    observation = json.loads(store.read_bytes(ref))
    facts = json.loads(store.read_bytes(ObjectRef(**observation["facts_ref"])))
    facts["records"][0]["cash_dividend_before_tax"] = "1E1000000"
    facts_ref = store.put_bytes(
        json.dumps(
            facts, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    observation["facts_ref"] = {
        "object_id": facts_ref.object_id,
        "size_bytes": facts_ref.size_bytes,
    }
    malformed_ref = store.put_bytes(
        json.dumps(
            observation, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    with pytest.raises(
        CorporateActionObservationError, match="corporate_action_record_number_invalid"
    ):
        read_corporate_action_observation(store, malformed_ref)
