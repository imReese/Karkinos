from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import read_provider_capture, read_provider_raw_payload
from data.market.corporate_actions import (
    CorporateActionObservationError,
    read_corporate_action_observation,
    summarize_corporate_action_observation,
)
from data.providers.tushare_corporate_actions import (
    DIVIDEND_FIELDS,
    collect_tushare_dividend_observation,
)
from data.storage.objects import ContentAddressedObjectStore

STOCK = InstrumentKey("600000", InstrumentType.STOCK)
NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def dividend_frame():
    return pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "div_proc": "实施",
                "end_date": "20251231",
                "ann_date": "20260310",
                "imp_ann_date": "20260401",
                "record_date": "20260409",
                "ex_date": "20260410",
                "pay_date": "20260413",
                "div_listdate": "20260414",
                "base_date": "20260409",
                "base_share": 123.5,
                "cash_div_tax": 0.5,
                "cash_div": 0.45,
                "stk_div": 0.3,
                "stk_bo_rate": 0.1,
                "stk_co_rate": 0.2,
            }
        ]
    )


class FakePro:
    def __init__(self, frame=None):
        self.frame = dividend_frame() if frame is None else frame
        self.calls = []

    def dividend(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame


def collect(store, client, *, now=NOW):
    return collect_tushare_dividend_observation(
        store,
        instrument=STOCK,
        client=client,
        clock=lambda: now,
    )


def test_stock_collection_keeps_dates_units_status_and_capture_availability(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    client = FakePro()
    ref = collect(store, client)
    observation = read_corporate_action_observation(store, ref)
    assert client.calls == [{"ts_code": "600000.SH", "fields": DIVIDEND_FIELDS}]
    row = observation["records"][0]
    assert row["implementation_status"] == "实施"
    assert row["announcement_date"] == "2026-03-10"
    assert row["implementation_announcement_date"] == "2026-04-01"
    assert row["ex_date"] == "2026-04-10"
    assert row["cash_dividend_before_tax"] == "0.5"
    assert row["cash_dividend_after_tax"] == "0.45"
    assert row["stock_dividend_ratio"] == "0.3"
    assert row["bonus_share_ratio"] == "0.1"
    assert row["capitalization_ratio"] == "0.2"
    assert row["base_shares"] == "1235000"
    assert observation["available_at"] == observation["captured_at"] == NOW.isoformat()
    assert observation["historical_availability_verified"] is False
    capture = read_provider_capture(store, store.resolve_ref(observation["capture_id"]))
    raw = json.loads(read_provider_raw_payload(store, capture))
    assert raw["response"]["columns"] == list(client.frame.columns)
    assert capture.record_count == 1


def test_empty_response_is_observed_but_never_complete_no_action_evidence(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    ref = collect(store, FakePro(pd.DataFrame()))
    summary = summarize_corporate_action_observation(
        read_corporate_action_observation(store, ref),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )
    assert summary["status"] == "observed"
    assert summary["coverage_status"] == "provider_reported_only"
    assert summary["total_record_count"] == summary["matched_event_count"] == 0
    assert summary["returns_modeled"] is False
    assert "empty response" in " ".join(summary["limitations"])


@pytest.mark.parametrize(
    "problem,code",
    [
        ("number", "tushare_dividend_number_invalid"),
        ("number_overflow", "tushare_dividend_number_invalid"),
        ("date", "tushare_dividend_date_invalid"),
        ("symbol", "tushare_dividend_response_instrument_mismatch"),
        ("columns", "tushare_dividend_response_fields_invalid"),
        ("duplicate", "corporate_action_records_ambiguous"),
        ("truncated", "tushare_dividend_response_may_be_truncated"),
        ("type", "tushare_dividend_response_type_invalid"),
    ],
)
def test_bad_response_is_captured_before_normalization_rejects(tmp_path, problem, code):
    frame = dividend_frame()
    if problem == "number":
        frame.loc[0, "cash_div_tax"] = float("inf")
    elif problem == "number_overflow":
        frame = frame.astype(object)
        frame.loc[0, "cash_div_tax"] = "1E1000000"
    elif problem == "date":
        frame.loc[0, "ex_date"] = "20260230"
    elif problem == "symbol":
        frame.loc[0, "ts_code"] = "000001.SZ"
    elif problem == "columns":
        frame = frame.drop(columns="ex_date")
    elif problem in {"duplicate", "truncated"}:
        frame = pd.concat([frame] * (2000 if problem == "truncated" else 2))
    elif problem == "type":
        frame = {"unexpected": "response"}
    store = ContentAddressedObjectStore(tmp_path)
    with pytest.raises(CorporateActionObservationError, match=code) as failure:
        collect(store, FakePro(frame))
    capture = read_provider_capture(store, store.resolve_ref(failure.value.capture_id))
    raw = json.loads(read_provider_raw_payload(store, capture))
    assert "response" in raw
    assert capture.provider == "tushare"
    if problem == "number":
        assert "inf" in str(raw)
    elif problem == "number_overflow":
        assert "1E1000000" in str(raw)


def test_unsupported_etf_never_calls_stock_dividend_endpoint(tmp_path):
    client = FakePro()
    with pytest.raises(CorporateActionObservationError, match="instrument_unsupported"):
        collect_tushare_dividend_observation(
            ContentAddressedObjectStore(tmp_path),
            instrument=InstrumentKey("510300", InstrumentType.ETF),
            client=client,
        )
    assert client.calls == []
