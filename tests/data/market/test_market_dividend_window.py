"""Real date-query captures retain prospective economic and availability bounds."""

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.distributions import distributions_from_evidence
from core.types import InstrumentKey, InstrumentType
from data.market.capture import read_provider_capture
from data.market.corporate_actions import (
    CorporateActionObservationError,
    publish_corporate_action_window,
    read_corporate_action_window,
    read_market_dividend_day,
)
from data.providers.tushare_corporate_actions import (
    DIVIDEND_FIELDS,
    collect_tushare_market_dividend_day,
)
from data.storage.objects import ContentAddressedObjectStore, ObjectStoreError
from tests.server.test_dataset_corporate_actions import _response

STOCK = InstrumentKey("600000", InstrumentType.STOCK)
START = date(2026, 9, 17)


def at(day):
    return datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(
        hours=14
    )


def capture(store, day, response=None, *, clock=None, calls=None):
    frame = pd.DataFrame() if response is None else response

    def dividend(**query):
        if calls is not None:
            calls.append(query)
        field = next(key for key in query if key != "fields")
        return frame[frame[field] == query[field]] if not frame.empty else frame

    return collect_tushare_market_dividend_day(
        store,
        day=day,
        client=SimpleNamespace(dividend=dividend),
        clock=clock or (lambda: at(day)),
    )


def window(store, refs, keys=(STOCK,)):
    ref = publish_corporate_action_window(
        store, instruments=keys, day_observation_ids=[ref.object_id for ref in refs]
    )
    return ref, read_corporate_action_window(store, ref)


def test_proposal_then_implementation_retains_real_first_seen_and_record_entitlement(
    tmp_path,
):
    store = ContentAddressedObjectStore(tmp_path)
    proposal = _response()
    proposal.loc[
        0,
        ["ann_date", "div_proc", "imp_ann_date", "record_date", "ex_date", "pay_date"],
    ] = ["20260917", "预案", None, None, None, None]
    first = capture(store, START, proposal)
    _, pending = window(store, [first])
    assert pending["events"] == []
    assert pending["unimplemented_record_count"] == 1
    implementation = proposal.copy()
    implementation.loc[
        0, ["div_proc", "imp_ann_date", "record_date", "ex_date", "pay_date"]
    ] = ["实施", "20260918", "20260918", "20260921", "20260922"]
    second = capture(store, START + timedelta(days=1), implementation)
    frozen, economic = window(store, [first, second])
    assert (
        economic["events"][0]["available_at"]
        == at(START + timedelta(days=1)).isoformat()
    )
    assert economic["events"][0]["record_date"] == "2026-09-18"
    assert economic["events"][0]["ex_date"] == "2026-09-21"
    assert len(distributions_from_evidence(economic)) == 1
    third = capture(store, START + timedelta(days=2))
    _, later = window(store, [first, second, third])
    assert later["events"][0]["available_at"] == economic["events"][0]["available_at"]
    assert later["oldest_captured_at"] == at(START + timedelta(days=2)).isoformat()
    assert read_corporate_action_window(store, frozen) == economic
    revised = implementation.copy()
    revised.loc[0, ["imp_ann_date", "cash_div_tax"]] = ["20260920", "0.3"]
    fourth = capture(store, START + timedelta(days=3), revised)
    _, changed = window(store, [first, second, third, fourth])
    assert (
        changed["events"][0]["available_at"]
        == at(START + timedelta(days=3)).isoformat()
    )
    from server.services.research.research_paper_books import _merge_distributions

    with pytest.raises(ValueError, match="revision_conflict"):
        _merge_distributions([economic, changed], evaluation_start=START)


@pytest.mark.parametrize("missing_ex", [False, True])
def test_implemented_missing_key_date_is_kept_and_financial_reader_blocks(
    tmp_path, missing_ex
):
    store = ContentAddressedObjectStore(tmp_path)
    frame = _response()
    frame.loc[0, ["record_date", "ex_date", "pay_date"]] = [
        "20260917",
        None if missing_ex else "20260918",
        None,
    ]
    ref = capture(store, START, frame)
    _, report = window(store, [ref])
    assert len(report["events"]) == 1 and report["undated_event_count"] == int(
        missing_ex
    )
    with pytest.raises(ValueError, match="event_dates_incomplete"):
        distributions_from_evidence(report)


def test_one_market_day_covers_5000_new_and_maintenance_members_with_four_real_requests(
    tmp_path,
):
    store = ContentAddressedObjectStore(tmp_path)
    calls = []
    ref = capture(store, START, calls=calls)
    keys = tuple(
        InstrumentKey(f"{600000 + index:06}", InstrumentType.STOCK)
        for index in range(5000)
    )
    _, report = window(store, [ref], keys)
    assert len(calls) == 4
    assert all(
        set(call) - {"fields"}
        in ({"ann_date"}, {"imp_ann_date"}, {"record_date"}, {"ex_date"})
        for call in calls
    )
    assert all("ts_code" not in call for call in calls)
    assert len(report["instruments"]) == 5000 and report["events"] == []
    assert report["coverage_start_date"] == START.isoformat()
    assert report["coverage_status"] == "provider_reported_only"


def test_update_window_and_full_page_fail_closed_and_raw_bytes_are_reopened(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    calls = []
    with pytest.raises(CorporateActionObservationError, match="update_window_pending"):
        capture(store, START, clock=lambda: at(START) - timedelta(hours=2), calls=calls)
    assert calls == []
    frame = pd.concat([_response()] * 2000, ignore_index=True)
    frame.loc[:, "ann_date"] = "20260917"
    with pytest.raises(CorporateActionObservationError, match="may_be_truncated"):
        capture(store, START, frame)
    ref = capture(store, START)
    payload = json.loads(store.read_bytes(ref))
    cap = read_provider_capture(
        store, store.resolve_ref(payload["queries"][0]["capture_ref"]["object_id"])
    )
    path = store._path_for(cap.raw_object_ref.object_id)
    path.chmod(0o644)
    path.write_bytes(b"corrupt")
    with pytest.raises(ObjectStoreError):
        read_market_dividend_day(store, ref)


def test_window_rejects_a_missing_calendar_day(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    with pytest.raises(CorporateActionObservationError, match="dates_incomplete"):
        window(
            store, [capture(store, START), capture(store, START + timedelta(days=2))]
        )


def test_later_retraction_with_changed_announcement_date_cannot_keep_old_entitlement(
    tmp_path,
):
    store = ContentAddressedObjectStore(tmp_path)
    implemented = _response()
    implemented.loc[0, ["ann_date", "record_date", "ex_date", "pay_date"]] = [
        "20260917",
        "20260917",
        "20260918",
        "20260918",
    ]
    first = capture(store, START, implemented)
    cancelled = implemented.copy()
    cancelled.loc[0, ["ann_date", "div_proc"]] = ["20260918", "取消"]
    second = capture(store, START + timedelta(days=1), cancelled)
    with pytest.raises(CorporateActionObservationError, match="retracted_or_ambiguous"):
        window(store, [first, second])
