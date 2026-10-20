"""Source-shaped TuShare SDK snapshots prove only explicit full-day halts."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.providers.tushare import TushareDailyBarResponseError
from data.providers.tushare_status import (
    TUSHARE_STATUS_ADAPTER_VERSION,
    TUSHARE_STATUS_FIELDS,
    TUSHARE_STATUS_PAYLOAD_FORMAT,
    TUSHARE_STATUS_SDK_VERSION,
    read_tushare_historical_status,
    serialize_tushare_status_frame,
)
from data.storage.objects import ContentAddressedObjectStore

AT = datetime(2026, 10, 18, 16, tzinfo=timezone.utc)
DAY = date(2020, 6, 17)


def _capture(tmp_path, *, rows=None, code="002500.SZ", mutate=None, overrides=None):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    request = {
        "ts_code": code,
        "start_date": "20200101",
        "end_date": "20261016",
        "fields": TUSHARE_STATUS_FIELDS,
    }
    frame = pd.DataFrame(
        [[code, "20200617", None, "S"]] if rows is None else rows,
        columns=TUSHARE_STATUS_FIELDS.split(","),
    )
    raw = {
        "schema": TUSHARE_STATUS_PAYLOAD_FORMAT,
        "sdk_version": TUSHARE_STATUS_SDK_VERSION,
        "request": dict(request),
        "frame": serialize_tushare_status_frame(frame),
    }
    if mutate is not None:
        mutate(request, raw)
    kwargs = {
        "provider": "tushare",
        "operation": "suspend_d",
        "adapter_version": TUSHARE_STATUS_ADAPTER_VERSION,
        "payload_format": TUSHARE_STATUS_PAYLOAD_FORMAT,
        "request": request,
        "raw_payload": json.dumps(raw, allow_nan=False).encode(),
        "started_at": AT - timedelta(seconds=1),
        "completed_at": AT,
        "record_count": len(frame),
        **(overrides or {}),
    }
    return objects, capture_provider_payload(objects, **kwargs)


@pytest.mark.parametrize("code", ["002500.SZ", "600000.SH", "920123.BJ"])
@pytest.mark.parametrize("timing", [None, ""])
def test_only_exact_raw_s_and_null_or_empty_timing_proves_halt(tmp_path, code, timing):
    objects, capture = _capture(
        tmp_path, code=code, rows=[[code, "20200617", timing, "S"]]
    )
    actual, request, statuses = read_tushare_historical_status(
        objects, capture.capture_ref
    )
    key = InstrumentKey(code[:6], InstrumentType.STOCK)
    assert actual == capture
    assert request.instruments == (key,)
    assert (request.start_date, request.end_date) == (
        date(2020, 1, 1),
        date(2026, 10, 16),
    )
    assert statuses == {DAY: {key: "0"}}
    assert actual.completed_at == AT  # Actual 2026 availability, never 2020 PIT.


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [["002500.SZ", "20200617", None, "R"]],
        [["002500.SZ", "20200617", "", "R"]],
        [["002500.SZ", "20200617", "09:30-10:30", "S"]],
        [["002500.SZ", "20200617", "09:30:00-15:00:00", "S"]],
    ],
)
def test_absence_resumption_and_nonempty_timing_never_become_full_day_halts(
    tmp_path, rows
):
    objects, capture = _capture(tmp_path, rows=rows)
    statuses = read_tushare_historical_status(objects, capture.capture_ref)[2]
    assert statuses == (
        {DAY: {InstrumentKey("002500", InstrumentType.STOCK): "not_full_day"}}
        if rows
        else {}
    )


def test_sdk_mixed_nullable_timing_is_preserved_without_changing_other_values(tmp_path):
    rows = [
        ["002500.SZ", "20200617", None, "S"],
        ["002500.SZ", "20200618", "09:30-10:30", "S"],
        ["002500.SZ", "20200619", "", "S"],
    ]
    frame = pd.DataFrame(rows, columns=TUSHARE_STATUS_FIELDS.split(","))
    original = frame.copy(deep=True)
    assert serialize_tushare_status_frame(frame)["data"] == rows
    pd.testing.assert_frame_equal(frame, original)
    objects, capture = _capture(tmp_path, rows=rows)
    statuses = read_tushare_historical_status(objects, capture.capture_ref)[2]
    assert set(statuses) == {DAY, date(2020, 6, 18), date(2020, 6, 19)}
    assert statuses[date(2020, 6, 18)] == {
        InstrumentKey("002500", InstrumentType.STOCK): "not_full_day"
    }


@pytest.mark.parametrize(
    "field", ["ts_code", "trade_date", "suspend_type", "suspend_timing"]
)
def test_serializer_never_replaces_infinity_or_nan_in_required_identity_fields(field):
    frame = pd.DataFrame(
        [["002500.SZ", "20200617", None, "S"]],
        columns=TUSHARE_STATUS_FIELDS.split(","),
        dtype=object,
    )
    frame.loc[0, field] = float("inf") if field == "suspend_timing" else float("nan")
    with pytest.raises(TushareDailyBarResponseError):
        serialize_tushare_status_frame(frame)


@pytest.mark.parametrize(
    "timing",
    ["nan", "NaN", "None", "null", " ", "09:99-10:00", "10:00-09:30", 0, False, [], {}],
)
def test_unknown_or_malformed_timing_is_rejected(tmp_path, timing):
    def mutate(request, raw):
        raw["frame"]["data"][0][2] = timing

    objects, capture = _capture(tmp_path, mutate=mutate)
    with pytest.raises(ValueError, match="tushare_historical_status_"):
        read_tushare_historical_status(objects, capture.capture_ref)


@pytest.mark.parametrize("second", [[None, "S"], [None, "R"], ["09:30-10:30", "S"]])
def test_same_day_duplicates_or_contradictions_reject_the_whole_capture(
    tmp_path, second
):
    objects, capture = _capture(
        tmp_path,
        rows=[
            ["002500.SZ", "20200617", None, "S"],
            ["002500.SZ", "20200617", *second],
        ],
    )
    with pytest.raises(ValueError, match="duplicate_invalid"):
        read_tushare_historical_status(objects, capture.capture_ref)


@pytest.mark.parametrize(
    "code",
    [
        "837023.BJ",
        "430001.BJ",
        "920123.SH",
        "002500.SH",
        "600000.SZ",
        "699999.SH",
        "399999.SZ",
        "002500.SZ,600000.SH",
    ],
)
def test_legacy_alias_unknown_prefix_and_mismatched_exchange_remain_unresolved(
    tmp_path, code
):
    objects, capture = _capture(tmp_path, code=code)
    with pytest.raises(ValueError, match="request_"):
        read_tushare_historical_status(objects, capture.capture_ref)


@pytest.mark.parametrize(
    "case",
    [
        "provider",
        "price_operation",
        "adapter",
        "format",
        "count",
        "early_capture",
        "sdk",
        "raw_request",
        "missing_timing",
        "index",
        "bool_index",
        "row_code",
        "old_alias",
        "row_day",
        "date_number",
        "unknown_status",
        "status_object",
        "extra_request",
        "fields",
        "filter",
        "filtered_r",
        "date_and_range",
        "row_width",
        "truncation",
    ],
)
def test_capture_request_frame_and_every_raw_row_are_strictly_bound(tmp_path, case):
    overrides = {
        "provider": {"provider": "akshare"},
        "price_operation": {"operation": "daily_bars"},
        "adapter": {"adapter_version": "karkinos.tushare.suspend_d.v0"},
        "format": {"payload_format": "tushare.pro.daily_bar.dataframe.v1"},
        "count": {"record_count": 0},
        "early_capture": {"started_at": datetime(2026, 10, 16, 6, tzinfo=timezone.utc)},
    }.get(case)

    def mutate(request, raw):
        frame = raw["frame"]
        row = frame["data"][0]
        if case == "sdk":
            raw["sdk_version"] = "1.4.28"
        elif case == "raw_request":
            raw["request"]["ts_code"] = "600000.SH"
        elif case == "missing_timing":
            frame["columns"].remove("suspend_timing")
            row.pop(2)
        elif case == "index":
            frame["index"] = [1]
        elif case == "bool_index":
            frame["index"] = [False]
        elif case in {"row_code", "old_alias"}:
            row[0] = "600000.SH" if case == "row_code" else "837023.BJ"
        elif case == "row_day":
            row[1] = "20191231"
        elif case == "date_number":
            row[1] = 20200617
        elif case == "unknown_status":
            row[3] = "unknown"
        elif case == "status_object":
            row[3] = {}
        elif case == "extra_request":
            request["limit"] = 1
        elif case == "fields":
            request["fields"] = "ts_code,trade_date,suspend_type"
        elif case == "filter":
            request["suspend_type"] = "R"
        elif case == "filtered_r":
            request["suspend_type"] = "S"
            row[3] = "R"
        elif case == "date_and_range":
            request["trade_date"] = "20200617"
        elif case == "row_width":
            row.append("unexpected")
        elif case == "truncation":
            frame["data"] = [row] * 5000
            frame["index"] = list(range(5000))
        if case not in {"raw_request"}:
            raw["request"] = dict(request)

    objects, capture = _capture(tmp_path, mutate=mutate, overrides=overrides)
    with pytest.raises(ValueError, match="tushare_historical_status_"):
        read_tushare_historical_status(objects, capture.capture_ref)


def test_single_day_actual_request_and_explicit_s_filter(tmp_path):
    def mutate(request, raw):
        request.pop("start_date")
        request.pop("end_date")
        request.update(trade_date="20200617", suspend_type="S")
        raw["request"] = dict(request)

    objects, capture = _capture(tmp_path, mutate=mutate)
    _, request, statuses = read_tushare_historical_status(objects, capture.capture_ref)
    assert request.start_date == request.end_date == DAY
    assert DAY in statuses
