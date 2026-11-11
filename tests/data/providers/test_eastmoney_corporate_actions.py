"""Real captured pages cover amounts, dates, pagination and offline replay."""

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backtest.distributions import distributions_from_evidence
from core.types import InstrumentKey, InstrumentType
from data.market.capture import read_provider_capture
from data.market.corporate_actions import (
    CorporateActionObservationError,
    _json_bytes,
    publish_corporate_action_window,
    read_corporate_action_window,
    read_market_dividend_day,
)
from data.providers import eastmoney_corporate_actions as provider
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2026, 9, 17)
NOW = datetime(2026, 9, 17, 14, tzinfo=timezone.utc)


def term(code="600000.SH", *, shares=False):
    return {
        "SECUCODE": code,
        "SECURITY_CODE": code[:6],
        "REPORT_DATE": "2026-06-30 00:00:00",
        "PLAN_NOTICE_DATE": "2026-09-17 00:00:00",
        "NOTICE_DATE": "2026-09-17 00:00:00",
        "EQUITY_RECORD_DATE": "2026-09-17 00:00:00",
        "EX_DIVIDEND_DATE": "2026-09-18 00:00:00",
        "ASSIGN_PROGRESS": "实施分配",
        "IMPL_PLAN_PROFILE": "10送1股转2股派2.00元(含税,扣税后1.80元)"
        if shares
        else "10派2.00元(含税,扣税后1.80元)",
        "BONUS_RATIO": 1 if shares else None,
        "IT_RATIO": 2 if shares else None,
        "BONUS_IT_RATIO": 3 if shares else None,
        "PRETAX_BONUS_RMB": 2,
    }


def calendar(row, *, shares=False):
    roles = [
        ("股权登记日", "2026-09-17"),
        ("除权除息日", "2026-09-18"),
        ("红利发放日", "2026-09-21"),
    ]
    if shares:
        roles.append(("股份上市日", "2026-09-22"))
    return [
        {
            "SECUCODE": row["SECUCODE"],
            "SECURITY_CODE": row["SECURITY_CODE"],
            "EVENT_TYPE": "分红转增" + role,
            "EVENT_CONTENT": row["IMPL_PLAN_PROFILE"],
            "TRADE_DATE": day + " 00:00:00",
        }
        for role, day in roles
    ]


def fake_pages(monkeypatch, terms, events, *, fault=None, clock=None):
    calls = []

    def get(url, *, params, timeout):
        assert url == provider.URL and timeout == 20
        calls.append(dict(params))
        if clock is not None:
            clock[0] += timedelta(seconds=1)
        if params["reportName"] == "RPT_SHAREBONUS_DET":
            field = params["filter"].split("=")[0][1:]
            selected = [
                row for row in terms if (row[field] or "").startswith(DAY.isoformat())
            ]
        else:
            selected = events
        size, page = int(params["pageSize"]), int(params["pageNumber"])
        rows = selected[(page - 1) * size : page * size]
        count = len(selected)
        if fault == "duplicate_page" and page == 2:
            rows = selected[: len(rows)]
        if fault == "changed_count" and page == 2:
            count += 1
        if not selected:
            body = {
                "version": None,
                "result": None,
                "success": False,
                "message": "返回数据为空",
                "code": 9201,
            }
        else:
            body = {
                "success": True,
                "code": 0,
                "result": {
                    "data": rows,
                    "count": count,
                    "pages": (count + size - 1) // size,
                },
            }
        if fault == "provider_error":
            body = {
                "success": False,
                "code": 9201,
                "message": "服务不可用",
                "result": None,
            }
        elif fault == "malformed_body":
            body = []
        elif fault == "malformed_result":
            body["result"] = ["unexpected"]
        return SimpleNamespace(
            status_code=200, content=json.dumps(body, ensure_ascii=False).encode()
        )

    monkeypatch.setattr(provider.requests, "get", get)
    return calls


@pytest.mark.parametrize("fault", ["malformed_body", "malformed_result"])
def test_malformed_response_keeps_raw_capture_for_failed_job(
    tmp_path, monkeypatch, fault
):
    store = ContentAddressedObjectStore(tmp_path)
    row = term()
    fake_pages(monkeypatch, [row], calendar(row), fault=fault)
    with pytest.raises(CorporateActionObservationError, match="page_invalid") as error:
        provider.collect_eastmoney_market_dividend_day(
            store, day=DAY, clock=lambda: NOW
        )
    capture = read_provider_capture(store, store.resolve_ref(error.value.capture_id))
    raw = json.loads(store.read_bytes(capture.raw_object_ref))
    if fault == "malformed_body":
        assert raw == []
    else:
        assert raw["result"] == ["unexpected"]
    assert capture.record_count is None


@pytest.mark.parametrize("shares", [False, True])
def test_market_capture_replays_cash_and_share_dates_with_source_units(
    tmp_path, monkeypatch, shares
):
    store = ContentAddressedObjectStore(tmp_path)
    row = term(shares=shares)
    clock = [NOW]
    calls = fake_pages(monkeypatch, [row], calendar(row, shares=shares), clock=clock)
    ref = provider.collect_eastmoney_market_dividend_day(
        store, day=DAY, clock=lambda: clock[0]
    )
    assert len(calls) == 5
    payload = json.loads(store.read_bytes(ref))
    assert "schema_version" not in payload
    first = read_provider_capture(
        store, store.resolve_ref(payload["captures"][0]["object_id"])
    )
    original = store.read_bytes(first.raw_object_ref)
    monkeypatch.setattr(
        provider.requests,
        "get",
        lambda *a, **k: pytest.fail("offline replay contacted provider"),
    )
    window = publish_corporate_action_window(
        store,
        instruments=[InstrumentKey("600000", InstrumentType.STOCK)],
        day_observation_ids=[ref.object_id],
    )
    evidence = read_corporate_action_window(store, window)
    assert evidence["provider"] == "eastmoney_datacenter"
    assert evidence["available_at"] == clock[0].isoformat()
    assert evidence["historical_availability_verified"] is False
    event = evidence["events"][0]
    assert event["cash_div_tax"] == "0.2" and event["cash_div"] == "0.18"
    assert event["stk_div"] == ("0.3" if shares else "0")
    assert event["base_shares"] is None
    assert event["source_revision_id"] == ref.object_id
    assert event["available_at"] == clock[0].isoformat()
    assert event["pay_date"] == "2026-09-21"
    assert event["div_listdate"] == ("2026-09-22" if shares else None)
    distribution = distributions_from_evidence(evidence, include_shares=True)[0]
    assert str(distribution.cash_per_share) == "0.2"
    assert store.read_bytes(first.raw_object_ref) == original
    assert read_corporate_action_window(store, window) == evidence


@pytest.mark.parametrize(
    "fault",
    [
        "changed_count",
        "duplicate_page",
        "provider_error",
        "terms_conflict",
        "missing_pay_date",
        "calendar_conflict",
    ],
)
def test_bad_or_incomplete_pages_never_become_usable_distributions(
    tmp_path, monkeypatch, fault
):
    store = ContentAddressedObjectStore(tmp_path)
    row = term()
    events = calendar(row)
    rows = [row]
    if fault in {"changed_count", "duplicate_page"}:
        rows = [term(f"{600000 + i}.SH") for i in range(501)]
    elif fault == "terms_conflict":
        row["PRETAX_BONUS_RMB"] = 3
    elif fault == "missing_pay_date":
        events = events[:2]
    elif fault == "calendar_conflict":
        events[1]["TRADE_DATE"] = "2026-09-19 00:00:00"
    fake_pages(monkeypatch, rows, events, fault=fault)
    if fault == "missing_pay_date":
        ref = provider.collect_eastmoney_market_dividend_day(
            store, day=DAY, clock=lambda: NOW
        )
        window = publish_corporate_action_window(
            store,
            instruments=[InstrumentKey("600000", InstrumentType.STOCK)],
            day_observation_ids=[ref.object_id],
        )
        with pytest.raises(ValueError, match="event_dates_incomplete"):
            distributions_from_evidence(read_corporate_action_window(store, window))
    else:
        with pytest.raises(CorporateActionObservationError):
            provider.collect_eastmoney_market_dividend_day(
                store, day=DAY, clock=lambda: NOW
            )


def test_empty_market_day_keeps_four_real_queries_and_exact_capture_binding(
    tmp_path, monkeypatch
):
    store = ContentAddressedObjectStore(tmp_path)
    calls = fake_pages(monkeypatch, [], [])
    with pytest.raises(CorporateActionObservationError, match="update_window_pending"):
        provider.collect_eastmoney_market_dividend_day(
            store, day=DAY, clock=lambda: NOW - timedelta(hours=2)
        )
    assert calls == []
    ref = provider.collect_eastmoney_market_dividend_day(
        store, day=DAY, clock=lambda: NOW
    )
    assert len(calls) == 4
    assert read_market_dividend_day(store, ref)["rows"] == []
    payload = json.loads(store.read_bytes(ref))
    changed = deepcopy(payload)
    changed["captures"] = changed["captures"][:-1]
    with pytest.raises(CorporateActionObservationError, match="pages_incomplete"):
        read_market_dividend_day(store, store.put_bytes(_json_bytes(changed)))
    changed = deepcopy(payload)
    changed["date"] = "2026-09-16"
    with pytest.raises(CorporateActionObservationError, match="capture_invalid"):
        read_market_dividend_day(store, store.put_bytes(_json_bytes(changed)))


def test_complete_multiple_pages_preserve_every_reported_proposal(
    tmp_path, monkeypatch
):
    store = ContentAddressedObjectStore(tmp_path)
    rows = [term(f"{600000 + i}.SH") for i in range(501)]
    for row in rows:
        row.update(
            ASSIGN_PROGRESS="董事会决议通过",
            IMPL_PLAN_PROFILE="不低于当年归母净利润的35%",
        )
    calls = fake_pages(monkeypatch, rows, [])
    ref = provider.collect_eastmoney_market_dividend_day(
        store, day=DAY, clock=lambda: NOW
    )
    observed = read_market_dividend_day(store, ref)
    assert len(calls) == 7
    assert len(observed["rows"]) == 501
    assert {row["source_code"] for row, _ in observed["rows"]} == {
        row["SECUCODE"] for row in rows
    }
    assert all(row["cash_dividend_before_tax"] is None for row, _ in observed["rows"])
