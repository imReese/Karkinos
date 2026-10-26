"""Replay original SSE structured suspension pages for a frozen consumer roster.

The immutable capture retains its native all-market request. The returned
DailyBarRequest is only the selected SSE-stock projection over that query's
date window, not a replacement capture request. Absence is never active or a
halt. Availability is actual capture completion; this is not historical PIT.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.market.capture import (
    ProviderCapture,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.market.contracts import DailyBarRequest
from data.storage.objects import ContentAddressedObjectStore, ObjectRef

SSE_STRUCTURED_SUSPENSION_ADAPTER_VERSION = "operation.sse.suspension.native_probe.v1"
SSE_STRUCTURED_SUSPENSION_PAYLOAD_FORMAT = "sse.suspension.raw_response.v1"
_URL = "https://query.sse.com.cn/commonSoaQuery.do"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ROWS = {
    "startStopDate",
    "stopReason",
    "productCode",
    "endStopReason",
    "controlType",
    "endStopDate",
    "stopTime",
    "type",
    "productName",
}
_BODY = {
    "actionErrors",
    "actionMessages",
    "fieldErrors",
    "isPagination",
    "jsonCallBack",
    "locale",
    "pageHelp",
    "pageNo",
    "pageSize",
    "queryDate",
    "result",
    "securityCode",
    "sqlId",
    "texts",
    "type",
    "validateCode",
}
_PAGE = {
    "beginPage",
    "cacheSize",
    "data",
    "endDate",
    "endPage",
    "objectResult",
    "pageCount",
    "pageNo",
    "pageSize",
    "pageSizeWithOutLimit",
    "searchDate",
    "sort",
    "startDate",
    "total",
}


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("sse_suspension_duplicate_JSON_key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("sse_suspension_nonfinite_JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _date(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{8}", value) is None:
        raise ValueError("sse_suspension_date_invalid")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def _close(day):
    return datetime.combine(day, time(15), _SHANGHAI).astimezone(timezone.utc)


def read_sse_structured_suspension_status(
    store: ContentAddressedObjectStore,
    capture_ref: ObjectRef,
    *,
    selected_instruments: tuple[InstrumentKey, ...],
) -> tuple[ProviderCapture, DailyBarRequest, dict[date, dict[InstrumentKey, str]]]:
    """Return explicit full-day/partial-day facts only inside the frozen scope.

    One native page is positive evidence, not proof that all events were fetched.
    Cross-window copies keep distinct original captures; equal statuses merge in
    the existing Dataset owner. Unknown/unclosed/future intervals retain an
    explicit ``unknown`` marker on their identifiable in-window dates, never 0
    or activity. This preserves contradictions with another source's full-day 0.
    Explicit intraday records retain ``not_full_day`` for conflict detection.
    """
    if (
        not isinstance(selected_instruments, tuple)
        or not selected_instruments
        or any(not isinstance(key, InstrumentKey) for key in selected_instruments)
        or len(set(selected_instruments)) != len(selected_instruments)
    ):
        raise ValueError("sse_suspension_selected_roster_invalid")
    selected = {
        key.symbol: key
        for key in selected_instruments
        if key.instrument_type is InstrumentType.STOCK
        and re.fullmatch(r"6[0-9]{5}", key.symbol)
    }
    if not selected:
        raise ValueError("sse_suspension_selected_SSE_stock_roster_empty")
    _json(store.read_bytes(capture_ref))
    capture = read_provider_capture(store, capture_ref)
    if (
        capture.provider != "sse_suspension"
        or capture.operation != "suspension_status_probe"
        or capture.adapter_version != SSE_STRUCTURED_SUSPENSION_ADAPTER_VERSION
        or capture.payload_format != SSE_STRUCTURED_SUSPENSION_PAYLOAD_FORMAT
        or capture.record_count is not None
    ):
        raise ValueError("sse_suspension_source_invalid")
    request = _json(capture.request_json)
    if not isinstance(request, dict) or set(request) != {"url", "params"}:
        raise ValueError("sse_suspension_request_invalid")
    params = request["params"]
    if (
        request["url"] != _URL
        or not isinstance(params, dict)
        or set(params)
        != {
            "isPagination",
            "sqlId",
            "pageHelp.pageSize",
            "pageHelp.pageNo",
            "productCode",
            "keyWords",
            "startStopDate",
            "endStopDate",
        }
        or params["isPagination"] != "true"
        or params["sqlId"] != "GW_PL_JYTS_TFPXX"
        or params["pageHelp.pageSize"] != "25"
        or params["productCode"] != ""
        or params["keyWords"] != ""
        or not isinstance(params["pageHelp.pageNo"], str)
        or re.fullmatch(r"[1-9][0-9]{0,4}", params["pageHelp.pageNo"]) is None
    ):
        raise ValueError("sse_suspension_request_invalid")
    start, end = _date(params["startStopDate"]), _date(params["endStopDate"])
    if end < start or (end - start).days >= 3653 or capture.started_at < _close(end):
        raise ValueError("sse_suspension_request_window_not_closed")
    planned = DailyBarRequest(tuple(selected.values()), start, end)
    raw = read_provider_raw_payload(store, capture)
    if not 0 < len(raw) <= 8 * 1024 * 1024:
        raise ValueError("sse_suspension_raw_size_invalid")
    body = _json(raw)
    if (
        not isinstance(body, dict)
        or set(body) != _BODY
        or body["actionErrors"] != []
        or body["actionMessages"] != []
        or body["fieldErrors"] != {}
        or body["isPagination"] != "true"
        or body["sqlId"] != params["sqlId"]
        or body["jsonCallBack"] is not None
        or body["locale"] != "en_CN"
        or any(body[field] is not None for field in ("pageNo", "pageSize", "texts"))
        or any(
            body[field] != ""
            for field in ("queryDate", "securityCode", "type", "validateCode")
        )
        or not isinstance(body["result"], list)
        or not isinstance(body["pageHelp"], dict)
        or set(body["pageHelp"]) != _PAGE
    ):
        raise ValueError("sse_suspension_native_schema_invalid")
    page = body["pageHelp"]
    total, count, number = (
        page["total"],
        page["pageCount"],
        int(params["pageHelp.pageNo"]),
    )
    if (
        any(
            type(page[field]) is not int
            for field in (
                "beginPage",
                "cacheSize",
                "pageNo",
                "pageSize",
                "pageSizeWithOutLimit",
                "pageCount",
                "total",
            )
        )
        or total < 0
        or count != (total + 24) // 25
        or number < 1
        or number > max(count, 1)
        or page["pageNo"] != number
        or page["pageSize"] != 25
        # beginPage is the UI page-number strip's moving start, not pageNo.
        or not 1 <= page["beginPage"] <= number
        or page["cacheSize"] != 1
        or page["pageSizeWithOutLimit"] != 25
        or page["data"] != body["result"]
        or len(body["result"]) != min(25, max(total - (number - 1) * 25, 0))
        or any(
            page[field] is not None
            for field in (
                "endDate",
                "endPage",
                "objectResult",
                "searchDate",
                "sort",
                "startDate",
            )
        )
    ):
        raise ValueError("sse_suspension_page_identity_invalid")
    statuses: dict[date, dict[InstrumentKey, str]] = {}
    seen = set()
    for row in body["result"]:
        if (
            not isinstance(row, dict)
            or set(row) != _ROWS
            or not all(isinstance(value, str) for value in row.values())
            or re.fullmatch(r"[0-9]{6}", row["productCode"]) is None
        ):
            raise ValueError("sse_suspension_native_row_invalid")
        identity = tuple(row[field] for field in sorted(_ROWS))
        if identity in seen:
            raise ValueError("sse_suspension_duplicate_native_row")
        seen.add(identity)
        if row["controlType"] != "TR" or row["productCode"] not in selected:
            continue
        first = _date(row["startStopDate"])
        unclosed = not row["endStopDate"]
        last = end if unclosed else _date(row["endStopDate"])
        if last < first:
            raise ValueError("sse_suspension_reversed_interval")
        if first > end or last < start:
            raise ValueError("sse_suspension_selected_row_outside_native_window")
        # Native unknowns stay visible to same-cell/cross-capture conflict
        # checks. The query end is already closed at capture start, so even an
        # unclosed or future-ending record has a finite observable projection.
        status = "unknown"
        closed = not unclosed and _close(last) <= capture.started_at
        if closed and row["type"] == "LXTP" and row["stopTime"] == "":
            status = "0"
        elif closed and row["type"] == "LSTP" and first == last:
            if row["stopTime"] == "WH":
                status = "0"
        if row["type"] in {"LXTP", "LSTP"} and row["stopTime"] in {"AM", "PM", "930"}:
            if closed and first == last:
                status = "not_full_day"
        key = selected[row["productCode"]]
        day, stop = max(first, start), min(last, end)
        while day <= stop:
            previous = statuses.setdefault(day, {}).get(key)
            if (
                previous is not None
                and previous != status
                and "0" in (previous, status)
            ):
                raise ValueError("sse_suspension_conflicting_native_status")
            # Both nonzero markers deny a full-day conclusion and neither
            # supplies an active bar. A definite partial observation may be
            # retained over an unknown, but cannot make a later 0 acceptable.
            statuses[day][key] = (
                "not_full_day" if "not_full_day" in (previous, status) else status
            )
            day += timedelta(days=1)
    return capture, planned, statuses
