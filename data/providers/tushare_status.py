"""Replay explicit TuShare full-day suspension observations from immutable bytes.

This is a historical backfill, with availability at actual capture completion.
Missing records, resumptions and intraday suspensions never imply a full-day halt.
No provider I/O, historical code aliasing or price normalization occurs here.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import InstrumentKey, InstrumentType
from data.market.capture import (
    ProviderCapture,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.market.contracts import DailyBarRequest
from data.storage.objects import ContentAddressedObjectStore, ObjectRef

TUSHARE_STATUS_ADAPTER_VERSION = "karkinos.tushare.suspend_d.v1"
TUSHARE_STATUS_PAYLOAD_FORMAT = "tushare.pro.suspend_d.dataframe.v1"
TUSHARE_STATUS_SDK_VERSION = "1.4.29"
TUSHARE_STATUS_FIELDS = "ts_code,trade_date,suspend_timing,suspend_type"

_FIELDS = TUSHARE_STATUS_FIELDS.split(",")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)")
_TIMING = re.compile(
    r"([0-9]{2}:[0-9]{2}(?::[0-9]{2})?)-([0-9]{2}:[0-9]{2}(?::[0-9]{2})?)"
)


def serialize_tushare_status_frame(frame: pd.DataFrame) -> dict[str, object]:
    """Preserve SDK values, restoring its nullable timing column to JSON null.

    SDK 1.4.29 constructs a DataFrame directly from returned items. Pandas may
    coerce a null timing in a string column to NaN. Only this documented nullable
    field is restored; strings such as 'NaN' remain strings for strict rejection.
    """
    from data.providers.tushare import _serialize_dataframe

    if not isinstance(frame, pd.DataFrame) or list(frame.columns) != _FIELDS:
        raise ValueError("tushare_historical_status_frame_invalid")
    preserved = frame.copy()
    timing = preserved["suspend_timing"].astype(object)
    preserved["suspend_timing"] = timing.where(timing.notna(), None)
    return _serialize_dataframe(preserved)


def read_tushare_historical_status(
    store: ContentAddressedObjectStore, capture_ref: ObjectRef
) -> tuple[ProviderCapture, DailyBarRequest, dict[date, dict[InstrumentKey, str]]]:
    """Read full-day facts and explicit counterevidence; absence stays unknown.

    The single-code v1 contract requires exact returned/requested code identity.
    Legacy BSE codes need separately captured mapping and are unsupported here.
    This source is one upstream's observation, not independent halt agreement.
    R and intraday S retain ``not_full_day`` solely for conflict detection;
    they neither imply an active bar nor justify excluding an instrument.
    """
    capture = read_provider_capture(store, capture_ref)
    if (
        capture.provider != "tushare"
        or capture.operation != "suspend_d"
        or capture.adapter_version != TUSHARE_STATUS_ADAPTER_VERSION
        or capture.payload_format != TUSHARE_STATUS_PAYLOAD_FORMAT
    ):
        raise ValueError("tushare_historical_status_source_invalid")
    request = json.loads(capture.request_json)
    planned = _status_request(request)
    if capture.started_at < datetime.combine(
        planned.end_date, time(15), _SHANGHAI
    ).astimezone(timezone.utc):
        raise ValueError("tushare_historical_status_session_not_closed")

    payload = json.loads(read_provider_raw_payload(store, capture))
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "sdk_version", "request", "frame"}
        or payload["schema"] != TUSHARE_STATUS_PAYLOAD_FORMAT
        or payload["sdk_version"] != TUSHARE_STATUS_SDK_VERSION
        or payload["request"] != request
    ):
        raise ValueError("tushare_historical_status_payload_invalid")
    frame = payload["frame"]
    if (
        not isinstance(frame, dict)
        or set(frame) != {"columns", "index", "data"}
        or frame["columns"] != _FIELDS
        or not isinstance(frame["data"], list)
        or not isinstance(frame["index"], list)
        or any(type(value) is not int for value in frame["index"])
        or frame["index"] != list(range(len(frame["data"])))
        or len(frame["data"]) >= 5000
        or len(frame["data"]) > (planned.end_date - planned.start_date).days + 1
        or type(capture.record_count) is not int
        or capture.record_count != len(frame["data"])
    ):
        raise ValueError("tushare_historical_status_frame_invalid")

    key = planned.instruments[0]
    seen: set[date] = set()
    statuses: dict[date, dict[InstrumentKey, str]] = {}
    for row in frame["data"]:
        if (
            not isinstance(row, list)
            or len(row) != len(_FIELDS)
            or row[0] != request["ts_code"]
            or not isinstance(row[3], str)
            or row[3] not in {"S", "R"}
            or (request.get("suspend_type") == "S" and row[3] != "S")
            or (row[2] is not None and not isinstance(row[2], str))
        ):
            raise ValueError("tushare_historical_status_row_invalid")
        day = _status_date(row[1])
        if not planned.start_date <= day <= planned.end_date or day in seen:
            # A same-day S/R or full-day/intraday contradiction is never a halt.
            raise ValueError("tushare_historical_status_date_or_duplicate_invalid")
        seen.add(day)
        timing = row[2]
        if timing is None or timing == "":
            statuses[day] = {key: "0" if row[3] == "S" else "not_full_day"}
        else:
            match = _TIMING.fullmatch(timing)
            if match is None:
                raise ValueError("tushare_historical_status_timing_invalid")
            try:
                start, end = (time.fromisoformat(value) for value in match.groups())
            except ValueError as exc:
                raise ValueError("tushare_historical_status_timing_invalid") from exc
            if start >= end:
                raise ValueError("tushare_historical_status_timing_invalid")
            statuses[day] = {key: "not_full_day"}
    return capture, planned, statuses


def _status_request(request: object) -> DailyBarRequest:
    from data.providers.tushare import TushareDailyBarRequestError, _request_target

    if not isinstance(request, dict):
        raise ValueError("tushare_historical_status_request_invalid")
    keys = set(request) - {"suspend_type"}
    if (
        keys
        not in (
            {"ts_code", "trade_date", "fields"},
            {"ts_code", "start_date", "end_date", "fields"},
        )
        or request.get("fields") != TUSHARE_STATUS_FIELDS
        or not isinstance(request.get("ts_code"), str)
        or _CODE.fullmatch(request["ts_code"]) is None
        or ("suspend_type" in request and request["suspend_type"] != "S")
    ):
        raise ValueError("tushare_historical_status_request_invalid")
    start = _status_date(request.get("trade_date", request.get("start_date")))
    end = _status_date(request.get("trade_date", request.get("end_date")))
    if start < date(2000, 1, 3) or end < start or (end - start).days >= 3653:
        raise ValueError("tushare_historical_status_request_range_invalid")
    key = InstrumentKey(request["ts_code"][:6], InstrumentType.STOCK)
    try:
        _, expected_code = _request_target(key)
    except TushareDailyBarRequestError as exc:
        raise ValueError("tushare_historical_status_request_code_invalid") from exc
    if expected_code != request["ts_code"] or (
        expected_code.endswith(".BJ") and not key.symbol.startswith("920")
    ):
        raise ValueError("tushare_historical_status_request_code_invalid")
    return DailyBarRequest((key,), start, end)


def _status_date(value: object) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{8}", value) is None:
        raise ValueError("tushare_historical_status_date_invalid")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError as exc:
        raise ValueError("tushare_historical_status_date_invalid") from exc
