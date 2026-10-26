"""Actual native shape with sanitized stocks: bytes, scope, dates and conflicts."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.providers.sse_suspension import (
    SSE_STRUCTURED_SUSPENSION_ADAPTER_VERSION,
    SSE_STRUCTURED_SUSPENSION_PAYLOAD_FORMAT,
    read_sse_structured_suspension_status,
)
from data.storage.objects import ContentAddressedObjectStore, ObjectIntegrityError

AT = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
KEYS = tuple(
    InstrumentKey(symbol, InstrumentType.STOCK) for symbol in ("600000", "600001")
)


def _row(**changes):
    return {
        "startStopDate": "20200116",
        "stopReason": "重要事项未公告",
        "productCode": "600000",
        "endStopReason": "重要公告",
        "controlType": "TR",
        "endStopDate": "20200116",
        "stopTime": "",
        "type": "LXTP",
        "productName": "样例股票",
        **changes,
    }


def _capture(
    tmp_path, rows=None, *, mutate_request=None, mutate_body=None, raw=None, **overrides
):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    request = {
        "url": "https://query.sse.com.cn/commonSoaQuery.do",
        "params": {
            "isPagination": "true",
            "sqlId": "GW_PL_JYTS_TFPXX",
            "pageHelp.pageSize": "25",
            "pageHelp.pageNo": "1",
            "productCode": "",
            "keyWords": "",
            "startStopDate": "20200101",
            "endStopDate": "20201231",
        },
    }
    if mutate_request:
        mutate_request(request)
    rows = [_row()] if rows is None else rows
    body = {
        "actionErrors": [],
        "actionMessages": [],
        "fieldErrors": {},
        "isPagination": "true",
        "jsonCallBack": None,
        "locale": "en_CN",
        "pageNo": None,
        "pageSize": None,
        "queryDate": "",
        "securityCode": "",
        "sqlId": "GW_PL_JYTS_TFPXX",
        "texts": None,
        "type": "",
        "validateCode": "",
        "result": rows,
        "pageHelp": {
            "beginPage": 1,
            "cacheSize": 1,
            "data": rows,
            "endDate": None,
            "endPage": None,
            "objectResult": None,
            "pageCount": (len(rows) + 24) // 25,
            "pageNo": 1,
            "pageSize": 25,
            "pageSizeWithOutLimit": 25,
            "searchDate": None,
            "sort": None,
            "startDate": None,
            "total": len(rows),
        },
    }
    if mutate_body:
        mutate_body(body)
    capture = capture_provider_payload(
        objects,
        **{
            "provider": "sse_suspension",
            "operation": "suspension_status_probe",
            "request": request,
            "raw_payload": json.dumps(body).encode() if raw is None else raw,
            "adapter_version": SSE_STRUCTURED_SUSPENSION_ADAPTER_VERSION,
            "payload_format": SSE_STRUCTURED_SUSPENSION_PAYLOAD_FORMAT,
            "started_at": AT - timedelta(seconds=1),
            "completed_at": AT,
            **overrides,
        },
    )
    return objects, capture


def _read(objects, capture, keys=KEYS):
    return read_sse_structured_suspension_status(
        objects, capture.capture_ref, selected_instruments=keys
    )


def test_original_page_preserved_and_only_frozen_typed_stock_roster_returned(tmp_path):
    rows = [
        _row(),
        _row(productCode="600009"),
        _row(productCode="113001", controlType="GB"),
        _row(productCode="600001", controlType="GB"),
        _row(productCode="900001"),
        _row(productCode="600002"),
    ]
    objects, cap = _capture(tmp_path, rows)
    before = objects.read_bytes(cap.raw_object_ref)
    actual, projected, statuses = _read(objects, cap)
    assert actual == cap and actual.completed_at == AT
    assert projected.instruments == KEYS
    assert statuses == {date(2020, 1, 16): {KEYS[0]: "0"}}
    assert json.loads(cap.request_json)["params"]["productCode"] == ""
    assert objects.read_bytes(cap.raw_object_ref) == before
    etf = InstrumentKey("600000", InstrumentType.ETF)
    assert _read(objects, cap, (etf, KEYS[1]))[2] == {}


def test_cross_year_literal_interval_is_inclusive_but_clipped_to_native_query_window(
    tmp_path,
):
    objects, cap = _capture(
        tmp_path, [_row(startStopDate="20191231", endStopDate="20200102")]
    )
    _, request, statuses = _read(objects, cap)
    assert request.start_date == date(2020, 1, 1)
    assert statuses == {
        date(2020, 1, 1): {KEYS[0]: "0"},
        date(2020, 1, 2): {KEYS[0]: "0"},
    }


@pytest.mark.parametrize(
    "kind,timing,expected",
    [
        ("LSTP", "WH", "0"),
        ("LSTP", "AM", "not_full_day"),
        ("LSTP", "PM", "not_full_day"),
        ("LSTP", "930", "not_full_day"),
        ("LXTP", "PM", "not_full_day"),
    ],
)
def test_literal_full_or_partial_time_is_never_silently_dropped(
    tmp_path, kind, timing, expected
):
    objects, cap = _capture(tmp_path, [_row(type=kind, stopTime=timing)])
    assert _read(objects, cap)[2] == {date(2020, 1, 16): {KEYS[0]: expected}}


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_row(endStopDate="")],
        [_row(endStopDate="20270101")],
        [_row(stopTime="unknown")],
        [_row(type="unknown")],
        [_row(type="LSTP", stopTime="WH", endStopDate="20200117")],
    ],
)
def test_empty_unclosed_future_and_unknown_semantics_remain_unknown(tmp_path, rows):
    objects, cap = _capture(tmp_path, rows)
    statuses = _read(objects, cap)[2]
    assert all(
        value == "unknown" for day in statuses.values() for value in day.values()
    )
    assert bool(statuses) == bool(rows)


def test_explicit_full_and_partial_same_day_contradiction_rejected(tmp_path):
    objects, cap = _capture(tmp_path, [_row(), _row(type="LSTP", stopTime="PM")])
    with pytest.raises(ValueError, match="conflicting_native_status"):
        _read(objects, cap)


def test_unobserved_LXTP_WH_is_not_silently_treated_as_blank_time(tmp_path):
    objects, cap = _capture(tmp_path, [_row(stopTime="WH")])
    assert _read(objects, cap)[2] == {date(2020, 1, 16): {KEYS[0]: "unknown"}}


def test_multi_day_partial_time_retains_unknown_instead_of_hiding_counterevidence(
    tmp_path,
):
    objects, cap = _capture(tmp_path, [_row(stopTime="PM", endStopDate="20200117")])
    assert _read(objects, cap)[2] == {
        day: {KEYS[0]: "unknown"} for day in (date(2020, 1, 16), date(2020, 1, 17))
    }


@pytest.mark.parametrize(
    "unknown",
    [
        {"stopTime": "UNKNOWN"},
        {"type": "UNKNOWN"},
        {"endStopDate": ""},
        {"endStopDate": "20270101"},
        {"stopTime": "PM", "endStopDate": "20200117"},
    ],
)
@pytest.mark.parametrize("unknown_first", [True, False])
def test_unknown_same_cell_cannot_disappear_in_either_native_row_order(
    tmp_path, unknown, unknown_first
):
    uncertain = _row(**unknown)
    rows = [uncertain, _row()] if unknown_first else [_row(), uncertain]
    objects, cap = _capture(tmp_path, rows)
    with pytest.raises(ValueError, match="conflicting_native_status"):
        _read(objects, cap)


def test_unknown_other_selected_or_foreign_stock_does_not_globally_disable_known_fact(
    tmp_path,
):
    objects, cap = _capture(
        tmp_path,
        [
            _row(),
            _row(productCode="600001", stopTime="UNKNOWN"),
            _row(productCode="600009", stopTime="UNKNOWN"),
        ],
    )
    assert _read(objects, cap)[2] == {
        date(2020, 1, 16): {KEYS[0]: "0", KEYS[1]: "unknown"}
    }


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "sse_disclosure"},
        {"operation": "daily_bars"},
        {"adapter_version": "future.v2"},
        {"payload_format": "other"},
        {"record_count": 1},
        {"started_at": datetime(2020, 1, 1, tzinfo=timezone.utc)},
    ],
)
def test_native_source_and_capture_time_cannot_be_relabelled(tmp_path, change):
    objects, cap = _capture(tmp_path, **change)
    with pytest.raises(ValueError, match="sse_suspension_"):
        _read(objects, cap)


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "https://example.invalid/commonSoaQuery.do"),
        ("productCode", "600000"),
        ("keyWords", "selected"),
        ("sqlId", "other"),
        ("pageHelp.pageSize", "100"),
        ("pageHelp.pageNo", "2"),
        ("isPagination", "false"),
        ("startStopDate", "20201301"),
    ],
)
def test_original_native_request_identity_is_not_a_synthetic_40_request(
    tmp_path, field, value
):
    def mutate(request):
        if field == "url":
            request[field] = value
        else:
            request["params"][field] = value

    objects, cap = _capture(tmp_path, mutate_request=mutate)
    with pytest.raises(ValueError):
        _read(objects, cap)


@pytest.mark.parametrize(
    "case",
    ["total", "page", "data", "errors", "extra", "duplicate_row", "invalid_date"],
)
def test_native_page_identity_error_duplicate_and_date_fail_closed(tmp_path, case):
    def mutate(body):
        if case == "total":
            body["pageHelp"]["total"] = 2
        elif case == "page":
            body["pageHelp"]["pageNo"] = 2
        elif case == "data":
            body["pageHelp"]["data"] = []
        elif case == "errors":
            body["actionErrors"] = ["failure"]
        elif case == "extra":
            body["result"][0]["unknown"] = "field"
        elif case == "invalid_date":
            body["result"][0]["endStopDate"] = "20200230"

    rows = [_row(), _row()] if case == "duplicate_row" else None
    objects, cap = _capture(tmp_path, rows, mutate_body=mutate)
    with pytest.raises(ValueError, match="sse_suspension_|day is out of range"):
        _read(objects, cap)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}'])
def test_closed_JSON_duplicates_and_nonfinite_rejected(tmp_path, raw):
    objects, cap = _capture(tmp_path, raw=raw)
    with pytest.raises(ValueError, match="sse_suspension_"):
        _read(objects, cap)


def test_real_page_seven_has_moving_UI_begin_page_and_exact_native_identity(tmp_path):
    rows = [_row(productCode=f"600{index:03}") for index in range(25)]

    def request(value):
        value["params"]["pageHelp.pageNo"] = "7"

    def body(value):
        value["pageHelp"].update(beginPage=2, pageNo=7, pageCount=60, total=1492)

    objects, cap = _capture(tmp_path, rows, mutate_request=request, mutate_body=body)
    assert _read(objects, cap)[2] == {date(2020, 1, 16): {key: "0" for key in KEYS}}


def test_each_cold_reopens_original_bytes(tmp_path):
    objects, cap = _capture(tmp_path)
    assert _read(objects, cap)[2]
    original = objects.read_bytes(cap.raw_object_ref)
    path = (
        objects.root
        / "sha256"
        / cap.raw_object_ref.object_id[7:9]
        / cap.raw_object_ref.object_id[9:]
    )
    path.chmod(0o600)  # Corrupt this sanitized temporary object only.
    path.write_bytes(original + b" ")
    with pytest.raises(ObjectIntegrityError):
        _read(objects, cap)
