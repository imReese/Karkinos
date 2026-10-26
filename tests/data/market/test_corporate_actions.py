from __future__ import annotations

import hashlib
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


def _projected_fixture(store, *, fault=None, code="600000"):
    from data.market.capture import capture_provider_payload
    from data.market.corporate_actions import (
        publish_eastmoney_corporate_action_projection,
    )

    digits = (
        "0.1234567890123456789"
        if fault == "decimal"
        else "0.12345678901234567890123456789"
    )
    decimal_fixture = fault in {"decimal", "precision_overflow"}
    profile = (
        f"10送{digits}股转2股派2元(含税)"
        if decimal_fixture
        else "10送1股转2股派2元(含税)"
    )
    term = dict(
        SECUCODE=code + ".SH",
        SECURITY_CODE=code,
        IMPL_PLAN_PROFILE=profile,
        ASSIGN_PROGRESS="实施分配",
        REPORT_DATE="2025-12-31 00:00:00",
        EQUITY_RECORD_DATE="2026-09-08 00:00:00",
        EX_DIVIDEND_DATE="2026-09-09 00:00:00",
        BONUS_RATIO=1,
        IT_RATIO=2,
        BONUS_IT_RATIO=3,
        PRETAX_BONUS_RMB=2,
    )
    if decimal_fixture:
        term.update(BONUS_RATIO="BONUS_LITERAL", BONUS_IT_RATIO="TOTAL_LITERAL")
    roles = ["股权登记日", "除权除息日", "红利发放日", "股份上市日"]
    calendar = [
        dict(
            SECUCODE=term["SECUCODE"],
            SECURITY_CODE=code,
            EVENT_CONTENT=profile,
            EVENT_TYPE="分红转增" + role,
            TRADE_DATE="2026-09-0" + ("8" if i == 0 else "9") + " 00:00:00",
        )
        for i, role in enumerate(roles)
    ]
    if fault == "unknown":
        term["BONUS_RATIO"] = None
    if fault in {"amount", "bool"}:
        term["BONUS_RATIO"] = True if fault == "bool" else 99
    if fault == "units":
        term["IMPL_PLAN_PROFILE"] = "每股派2元"
    if fault == "identity":
        calendar[2]["SECURITY_CODE"] = "999999"
    if fault == "role":
        calendar[2]["EVENT_TYPE"] = calendar[1]["EVENT_TYPE"]
    if fault == "dates":
        calendar[2]["TRADE_DATE"] = "2026-09-07 00:00:00"
    refs = []
    for index, rows in enumerate(
        (
            [term, {**term, "SECUCODE": "600002.SH", "SECURITY_CODE": "600002"}],
            calendar
            + [{**calendar[0], "SECUCODE": "600002.SH", "SECURITY_CODE": "600002"}],
        )
    ):
        params = dict(
            client="WEB",
            source="WEB",
            pageSize="500",
            pageNumber="1",
            reportName="RPT_SPECIAL_DIVIDEND" if index else "RPT_SHAREBONUS_DET",
            columns="SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,EVENT_TYPE,EVENT_CONTENT,TRADE_DATE"
            if index
            else "ALL",
            sortColumns="EVENT_CODE,SECURITY_CODE" if index else "PLAN_NOTICE_DATE",
            sortTypes="1,-1" if index else "-1",
        )
        field = "TRADE_DATE" if index else "EX_DIVIDEND_DATE"
        params["filter"] = f"({field}>='2026-01-05')({field}<='2026-10-15')"
        if not index:
            params.update(js='{"data":(x),"pages":(tp)}', quoteColumns="")
        if fault == "request" and index:
            params["reportName"] = "UNREVIEWED_REPORT"
        raw = json.dumps(
            dict(success=True, code=0, result=dict(data=rows, count=len(rows), pages=1))
        ).encode()
        if decimal_fixture:
            raw = raw.replace(b'"BONUS_LITERAL"', digits.encode()).replace(
                b'"TOTAL_LITERAL"', ("2" + digits[1:]).encode()
            )
        refs.append(
            capture_provider_payload(
                store,
                provider="foreign" if fault == "provider" else "eastmoney_datacenter",
                operation="corporate_action_calendar_window" if index else "dividend",
                request=dict(
                    method="GET",
                    url="https://datacenter-web.eastmoney.com/api/data/v1/get",
                    parameters=params,
                ),
                raw_payload=raw,
                payload_format="eastmoney.datacenter.calendar.http_response_body.v1"
                if index
                else "eastmoney.datacenter.http_response_body.v1",
                adapter_version="karkinos.artifact.eastmoney.dividend_calendar_window_raw.v1"
                if index
                else "karkinos.artifact.eastmoney.sharebonus_page_raw.v1",
                started_at=NOW - timedelta(days=1 - index),
                completed_at=NOW - timedelta(days=1 - index),
                record_count=1 if fault == "count" else len(rows),
            ).capture_ref
        )
    return publish_eastmoney_corporate_action_projection(
        store,
        fhps_capture_ref=refs[0],
        fhps_row_index=False if fault == "index" else 0,
        calendar_capture_ref=refs[1],
        calendar_row_indices=[0, 1, 2, 3],
    )


def test_native_projection_is_partial_cold_replay_not_a_synthetic_capture(tmp_path):
    from decimal import Decimal

    from backtest.distributions import _total_share_rate

    store = ContentAddressedObjectStore(tmp_path)
    ref = _projected_fixture(store)
    observation = read_corporate_action_observation(
        ContentAddressedObjectStore(tmp_path), ref
    )
    row = observation["records"][0]
    assert row["cash_dividend_before_tax"] == "0.2"
    assert row["stock_dividend_ratio"] == "0.3"
    assert _total_share_rate(
        Decimal(row["bonus_share_ratio"]), Decimal(row["capitalization_ratio"])
    ) == Decimal(".3")
    assert all(
        row[key] is None
        for key in (
            "cash_dividend_after_tax",
            "base_shares",
            "base_date",
            "announcement_date",
            "implementation_announcement_date",
        )
    )
    assert observation["available_at"] == observation["captured_at"] == NOW.isoformat()
    assert observation["oldest_captured_at"] == (NOW - timedelta(days=1)).isoformat()
    assert observation["historical_availability_verified"] is False
    assert "capture_id" not in observation and len(observation["capture_ids"]) == 2
    captures = [
        read_provider_capture(store, store.resolve_ref(key))
        for key in observation["capture_ids"]
    ]
    assert [item.record_count for item in captures] == [2, 5]
    assert all(
        json.loads(item.request_json)["parameters"]["pageSize"] == "500"
        for item in captures
    )
    summary = summarize_corporate_action_observation(
        observation, start_date=date(2026, 9, 7), end_date=date(2026, 9, 11)
    )
    assert summary["coverage_status"] == summary["source_extent"] == "selected_events"
    assert summary["availability_basis"] == "all_parent_captures_completed"
    precise = read_corporate_action_observation(
        store, _projected_fixture(store, fault="decimal")
    )["records"][0]
    assert precise["bonus_share_ratio"] == "0.01234567890123456789"
    assert precise["stock_dividend_ratio"] == "0.21234567890123456789"
    unknown = read_corporate_action_observation(
        store, _projected_fixture(store, fault="unknown")
    )
    assert unknown["records"][0]["bonus_share_ratio"] is None
    # Existing v1 schema, identity, default summary and raw bindings stay untouched.
    old = collect(store, FakePro())
    assert (
        old.object_id
        == "sha256:8b34759386aa74cda8504fc3d6c7b42a2ef29ac1a60de81565186c75384f3162"
    )
    legacy = read_corporate_action_observation(store, old)
    assert (
        legacy["facts_revision_id"]
        == "sha256:3688859c5cc2474cf8ed622c6f3d40aa6da0102669b264a210e46c9ad1e31e26"
    )
    legacy_summary = summarize_corporate_action_observation(
        legacy, start_date=date(2026, 4, 1), end_date=date(2026, 4, 30)
    )
    canonical = json.dumps(
        legacy_summary,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    assert (
        hashlib.sha256(canonical).hexdigest()
        == "af885fec0e5ca9ab35a0a2df61f60c5aeef0e4d87e59114786e028f599ffa033"
    )
    assert collect(store, FakePro()) == old
    assert "source_extent" not in read_corporate_action_observation(store, old)
    assert (
        summarize_corporate_action_observation(
            read_corporate_action_observation(store, old),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )["coverage_status"]
        == "provider_reported_only"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "amount",
        "bool",
        "units",
        "identity",
        "role",
        "dates",
        "request",
        "provider",
        "count",
        "index",
        "precision_overflow",
    ],
)
def test_native_projection_rejects_unverified_source_units_roles_and_dates(
    tmp_path, fault
):
    with pytest.raises(CorporateActionObservationError):
        _projected_fixture(ContentAddressedObjectStore(tmp_path), fault=fault)


def test_partial_dataset_refuses_gross_backtest_and_paper_and_keeps_oldest_parent(
    tmp_path,
):
    from dataclasses import replace

    from backtest.distributions import distributions_from_evidence
    from core.types import InstrumentKey, InstrumentType
    from data.dataset.manifest import publish_daily_bar_dataset_manifest
    from data.dataset.reader import (
        DatasetReaderIntegrityError,
        read_daily_bar_dataset,
        read_dataset_corporate_action_evidence,
    )
    from server.ai_runtime.strategy_research_backtest import (
        _bound_formula_portfolio_inputs,
    )
    from server.services.research.research_paper_books import _merge_distributions
    from tests.server.test_research_datasets import _publish

    original = _publish(tmp_path)
    store = ContentAddressedObjectStore(tmp_path / "objects")
    old_bytes = store.read_bytes(original.manifest_ref)
    snapshot = read_daily_bar_dataset(store, original).snapshot
    ref = _projected_fixture(store)
    updated = replace(
        snapshot,
        cutoff=NOW + timedelta(days=1),
        corporate_action_observation_ids=(ref.object_id,),
    )
    published = publish_daily_bar_dataset_manifest(store, updated)
    restored = read_daily_bar_dataset(store, published)
    evidence = restored.corporate_action_evidence
    assert evidence["coverage_status"] == "selected_events"
    assert evidence["availability_basis"] == "all_parent_captures_completed"
    assert store.read_bytes(original.manifest_ref) == old_bytes
    assert restored.bars == read_daily_bar_dataset(store, original).bars
    assert (
        read_dataset_corporate_action_evidence(
            store, updated, include_capture_freshness=True
        )["oldest_captured_at"]
        == (NOW - timedelta(days=1)).isoformat()
    )
    with pytest.raises(ValueError, match="cash_dividend_evidence_required"):
        distributions_from_evidence(evidence, include_shares=True)
    with pytest.raises(ValueError, match="cash_dividend_evidence_required"):
        _bound_formula_portfolio_inputs(
            tmp_path,
            {"immutable_dataset_id": published.dataset_id},
            require_distributions=True,
        )
    with pytest.raises(
        ValueError,
        match="paper_book_corporate_action_evidence_invalid:cash_dividend_evidence_required",
    ):
        _merge_distributions([evidence], evaluation_start=date(2026, 9, 7))
    with pytest.raises(DatasetReaderIntegrityError, match="after_cutoff"):
        read_dataset_corporate_action_evidence(
            store, replace(updated, cutoff=NOW - timedelta(hours=1))
        )
    second = InstrumentKey("600001", InstrumentType.STOCK)
    with pytest.raises(DatasetReaderIntegrityError, match="coverage_mismatch"):
        read_dataset_corporate_action_evidence(
            store, replace(updated, instruments=(*updated.instruments, second))
        )
    # The first full per-stock report must not erase the second partial projection.
    legacy = collect(store, FakePro())
    second_ref = _projected_fixture(store, code="600001")
    mixed = replace(
        updated,
        instruments=(*updated.instruments, second),
        corporate_action_observation_ids=(legacy.object_id, second_ref.object_id),
    )
    mixed_evidence = read_dataset_corporate_action_evidence(store, mixed)
    assert mixed_evidence["coverage_status"] == "selected_events"
    assert mixed_evidence["availability_basis"] == "all_parent_captures_completed"


@pytest.mark.parametrize("mutation", ["facts", "parent", "raw", "source_extent"])
def test_native_projection_cold_reader_recomputes_original_raw_and_envelope(
    tmp_path, mutation
):
    store = ContentAddressedObjectStore(tmp_path)
    ref = _projected_fixture(store)
    observation = json.loads(store.read_bytes(ref))
    if mutation == "facts":
        facts = json.loads(store.read_bytes(ObjectRef(**observation["facts_ref"])))
        facts["records"][0]["cash_dividend_before_tax"] = "9"
        changed = store.put_bytes(
            json.dumps(
                facts, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        observation["facts_ref"] = dict(
            object_id=changed.object_id, size_bytes=changed.size_bytes
        )
    elif mutation == "parent":
        parent = json.loads(
            store.read_bytes(ObjectRef(**observation["parents"][1]["capture_ref"]))
        )
        parent["completed_at"] = (NOW + timedelta(seconds=1)).isoformat()
        changed = store.put_bytes(
            json.dumps(
                parent, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        observation["parents"][1]["capture_ref"] = dict(
            object_id=changed.object_id, size_bytes=changed.size_bytes
        )
    elif mutation == "source_extent":
        observation["source_extent"] = "provider_reported_only"
    else:
        capture = read_provider_capture(
            store, ObjectRef(**observation["parents"][0]["capture_ref"])
        )
        raw_path = store._path_for(capture.raw_object_ref.object_id)
        raw_path.chmod(0o644)
        raw_path.write_bytes(b"corrupted sanitized native fixture")
    forged = store.put_bytes(
        json.dumps(
            observation, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    with pytest.raises(CorporateActionObservationError):
        read_corporate_action_observation(store, forged)
