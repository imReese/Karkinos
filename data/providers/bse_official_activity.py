"""Replay explicit official BSE daily activity from immutable public captures.

Zero volume and amount mean no recorded transaction in this source, not a
confirmed exchange suspension. Missing rows remain unknown. This reader creates
no price bars, performs no provider I/O and grants no point-in-time availability.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.market.capture import (
    ProviderCapture,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.market.contracts import DailyBarRequest
from data.storage.objects import ContentAddressedObjectStore, ObjectRef

_FIELDS = {"cjje", "cjl", "jrsp", "jrkp", "jsrq", "drzd", "drzx", "zrsp"}
_PAGE = "https://www.bse.cn/products/neeq_listed_companies/company_time_sharing.html"
_URL = re.compile(
    r"https://www\.bse\.cn/companyEchartsController/getKLine/list/(920[0-9]{3})\.do"
)


def read_bse_official_historical_activity(
    store: ContentAddressedObjectStore, capture_ref: ObjectRef
) -> tuple[ProviderCapture, DailyBarRequest, dict[date, dict[InstrumentKey, str]]]:
    """Read one upstream's explicit no-transaction facts and traded counterfacts.

    The existing membership reader consumes ``0`` as a dated nontrading fact and
    ``1`` as conflicting transaction activity. Availability remains the actual
    capture completion, and the consumer must retain exploratory decision_at=None.
    """
    capture = read_provider_capture(store, capture_ref)
    if (
        capture.provider,
        capture.operation,
        capture.payload_format,
        capture.adapter_version,
    ) != (
        "bse_official_kline_probe",
        "public_kline_probe",
        "bse.companyEcharts.kline.raw_public_response.probe.v1",
        "operation.bse.official_kline.public_probe.v1",
    ) or capture.record_count is not None:
        raise ValueError("bse_official_activity_source_invalid")
    request = json.loads(capture.request_json)
    if not isinstance(request, dict) or not isinstance(request.get("url"), str):
        raise TypeError("bse_official_activity_request_invalid")
    match = _URL.fullmatch(request["url"])
    if match is None or request != {
        "method": "GET",
        "url": request["url"],
        "params": {
            "begin": "0",
            "end": "-1",
            "type": "dayKline",
            "xxfcbj": "2",
            "callback": "karkinosHistoricalKlineRead",
        },
        "headers": {"Referer": _PAGE, "User-Agent": "Mozilla/5.0"},
    }:
        raise ValueError("bse_official_activity_request_invalid")
    instrument = InstrumentKey(match[1], InstrumentType.STOCK)
    body = read_provider_raw_payload(store, capture)
    if not 8 <= len(body) <= 4 * 1024 * 1024:
        raise ValueError("bse_official_activity_raw_size_invalid")
    wrapped = re.fullmatch(
        r"\s*karkinosHistoricalKlineRead\((\{.*\})\)\s*;?\s*",
        body.decode("utf-8"),
        re.DOTALL,
    )
    if wrapped is None:
        raise ValueError("bse_official_activity_closed_jsonp_required")
    value = json.loads(
        wrapped[1],
        parse_float=Decimal,
        parse_constant=_invalid_constant,
        object_pairs_hook=_unique_pairs,
    )
    if (
        not isinstance(value, dict)
        or set(value) != {"data", "status", "msg"}
        or type(value["status"]) is not int
        or value["status"] != 0
        or value["msg"] != ""
        or not isinstance(value["data"], list)
        or not 1 <= len(value["data"]) <= 12000
    ):
        raise ValueError("bse_official_activity_payload_invalid")
    statuses = {}
    for row in value["data"]:
        if not isinstance(row, dict) or set(row) != _FIELDS:
            raise ValueError("bse_official_activity_fields_invalid")
        raw_day = row["jsrq"]
        if not isinstance(raw_day, str) or re.fullmatch(r"[0-9]{8}", raw_day) is None:
            raise ValueError("bse_official_activity_date_invalid")
        day = datetime.strptime(raw_day, "%Y%m%d").date()
        if day.strftime("%Y%m%d") != raw_day or day in statuses:
            raise ValueError("bse_official_activity_date_or_duplicate_invalid")
        if (
            datetime.combine(day, time(15), ZoneInfo("Asia/Shanghai")).astimezone(UTC)
            > capture.started_at
        ):
            raise ValueError("bse_official_activity_session_not_closed")
        numbers = {field: _number(row[field]) for field in _FIELDS - {"jsrq"}}
        volume, amount = numbers["cjl"], numbers["cjje"]
        if volume != volume.to_integral_value():
            raise ValueError("bse_official_activity_fractional_shares")
        if (volume == 0) != (amount == 0):
            raise ValueError("bse_official_activity_zero_pair_inconsistent")
        prices = [numbers[field] for field in ("jrkp", "jrsp", "drzd", "drzx")]
        if volume == 0 and all(price == 0 for price in prices):
            statuses[day] = {instrument: "0"}
            continue
        open_price, close, high, low = prices
        if (
            min(prices) <= 0
            or not low <= min(open_price, close) <= max(open_price, close) <= high
        ):
            raise ValueError("bse_official_activity_ohlc_invalid")
        statuses[day] = {instrument: "0" if volume == 0 else "1"}
    return (
        capture,
        DailyBarRequest((instrument,), min(statuses), max(statuses)),
        statuses,
    )


def _number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise TypeError("bse_official_activity_number_invalid")
    result = Decimal(value)
    if not result.is_finite() or result < 0:
        raise ValueError("bse_official_activity_number_invalid")
    return result


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("bse_official_activity_duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("bse_official_activity_nonfinite_json")
