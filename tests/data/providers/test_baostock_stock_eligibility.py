"""Dated ST facts preserve source identity, missingness and actual capture time."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from data.market.capture import capture_provider_payload
from data.providers.baostock import read_baostock_stock_eligibility
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 17)
NOW = datetime(2026, 9, 18, 1, tzinfo=timezone.utc)


def eligibility_capture(objects, *, day=DAY, completed=NOW, flag="1", fault=None):
    request = {
        "code": "sh.600000",
        "fields": "date,code,tradestatus,isST",
        "start_date": str(day),
        "end_date": str(day),
        "frequency": "d",
        "adjustflag": "3",
    }
    payload = {
        "fields": request["fields"].split(","),
        "rows": [[str(day), request["code"], "1", flag]],
        "error_code": "0",
        "error_msg": "success",
    }
    if fault == "wrong_security":
        payload["rows"][0][1] = "sz.000001"
    elif fault == "wrong_date":
        payload["rows"][0][0] = str(day - timedelta(days=1))
    elif fault == "unknown_flag":
        payload["rows"][0][3] = ""
    elif fault == "duplicate":
        payload["rows"] *= 2
    elif fault == "provider_error":
        payload["error_code"] = "10002007"
    elif fault == "wrong_fields":
        payload["fields"][-1] = "is_st"
    elif fault == "empty":
        payload["rows"] = []
    return capture_provider_payload(
        objects,
        provider="baostock",
        operation="stock_eligibility",
        request=request,
        raw_payload=json.dumps(payload).encode(),
        payload_format="baostock.history_k_data_plus.stock_eligibility",
        adapter_version="baostock.stock_eligibility",
        started_at=completed,
        completed_at=completed,
        record_count=99 if fault == "wrong_count" else len(payload["rows"]),
    )


@pytest.mark.parametrize("flag", ["0", "1"])
def test_replay_keeps_trading_and_st_facts_separate(tmp_path, flag):
    objects = ContentAddressedObjectStore(tmp_path)
    original = eligibility_capture(objects, flag=flag)
    raw = objects.read_bytes(original.raw_object_ref)
    capture, request, activity, special = read_baostock_stock_eligibility(
        objects, original.capture_ref
    )
    key = request.instruments[0]
    assert activity == {DAY: {key: "1"}}
    assert special == {DAY: {key: flag}}
    assert capture.completed_at == NOW
    assert objects.read_bytes(original.raw_object_ref) == raw


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_security",
        "wrong_date",
        "unknown_flag",
        "duplicate",
        "provider_error",
        "wrong_fields",
        "wrong_count",
    ],
)
def test_invalid_eligibility_cannot_explain_an_omitted_stock(tmp_path, fault):
    objects = ContentAddressedObjectStore(tmp_path)
    capture = eligibility_capture(objects, fault=fault)
    with pytest.raises(ValueError, match="baostock_stock_eligibility"):
        read_baostock_stock_eligibility(objects, capture.capture_ref)


def test_missing_rows_remain_unknown(tmp_path):
    objects = ContentAddressedObjectStore(tmp_path)
    capture = eligibility_capture(objects, fault="empty")
    _, _, activity, special = read_baostock_stock_eligibility(
        objects, capture.capture_ref
    )
    assert activity == special == {}
