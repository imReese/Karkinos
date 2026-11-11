"""Dated market-wide distribution terms and their original payment calendar."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, DecimalException, Inexact, localcontext
from typing import Any
from zoneinfo import ZoneInfo

import requests

from data.market.capture import (
    ProviderCapture,
    capture_provider_payload,
    read_provider_capture,
)
from data.market.corporate_actions import (
    DATE_FIELDS,
    NUMBER_FIELDS,
    CorporateActionObservationError,
    _canonical_records,
    _native_date,
    _number_text,
)
from data.providers.akshare_sdk import provider_network_env
from data.storage.objects import ContentAddressedObjectStore, ObjectRef

PROVIDER = "eastmoney_datacenter"
ADAPTER = "eastmoney.dividend"
PAYLOAD_FORMAT = "eastmoney.datacenter.http_response_body"
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_TERMS = "RPT_SHAREBONUS_DET"
_CALENDAR = "RPT_SPECIAL_DIVIDEND"
_DATE_QUERIES = (
    "PLAN_NOTICE_DATE",
    "NOTICE_DATE",
    "EQUITY_RECORD_DATE",
    "EX_DIVIDEND_DATE",
)
_TERM_FIELDS = (
    "SECUCODE",
    "SECURITY_CODE",
    "REPORT_DATE",
    *_DATE_QUERIES,
    "ASSIGN_PROGRESS",
    "IMPL_PLAN_PROFILE",
    "BONUS_RATIO",
    "IT_RATIO",
    "BONUS_IT_RATIO",
    "PRETAX_BONUS_RMB",
)
_ROLES = {
    "分红转增股权登记日": "record_date",
    "分红转增除权除息日": "ex_date",
    "分红转增红利发放日": "pay_date",
    "分红转增股份上市日": "share_listing_date",
}
_PAGE_SIZE = 500
_MAX_PAGES = 20
_NUMBER = r"([0-9]+(?:\.[0-9]+)?)"
_PLAN = re.compile(
    r"10(?:送" + _NUMBER + r"股?)?(?:转(?:增)?" + _NUMBER + r"股?)?"
    r"(?:派" + _NUMBER + r"元)?(?:\(含税(?:,扣税后" + _NUMBER + r"元)?\))?"
)


def _parameters(report: str, condition: str, page: int) -> dict[str, str]:
    return {
        "reportName": report,
        "columns": "ALL",
        "filter": condition,
        "pageSize": str(_PAGE_SIZE),
        "pageNumber": str(page),
        "sortColumns": "SECUCODE,REPORT_DATE,PLAN_NOTICE_DATE"
        if report == _TERMS
        else "SECUCODE,EVENT_TYPE,TRADE_DATE",
        "sortTypes": "1,1,1",
        "source": "WEB",
        "client": "WEB",
    }


def _page(raw: bytes) -> tuple[list[dict[str, Any]], int, int]:
    body = json.loads(raw, parse_float=Decimal)
    if not isinstance(body, dict):
        raise CorporateActionObservationError("eastmoney_dividend_page_invalid")
    if (
        body.get("code") == 9201
        and body.get("success") is False
        and body.get("message") == "返回数据为空"
        and body.get("result") is None
    ):
        return [], 0, 1
    result = body.get("result")
    if not isinstance(result, dict):
        raise CorporateActionObservationError("eastmoney_dividend_page_invalid")
    rows, count, pages = (result.get(key) for key in ("data", "count", "pages"))
    if (
        body.get("success") is not True
        or type(body.get("code")) is not int
        or body["code"] != 0
        or not isinstance(rows, list)
        or type(count) is not int
        or count < 0
        or type(pages) is not int
        or pages != max(1, (count + _PAGE_SIZE - 1) // _PAGE_SIZE)
        or not 1 <= pages <= _MAX_PAGES
    ):
        raise CorporateActionObservationError("eastmoney_dividend_page_invalid")
    return rows, count, pages


def _read_query(
    store: ContentAddressedObjectStore,
    captures: Iterator[ProviderCapture],
    report: str,
    condition: str,
    *,
    day: date,
) -> list[dict[str, Any]]:
    result, expected = [], None
    for page in range(1, _MAX_PAGES + 1):
        try:
            capture = next(captures)
        except StopIteration as exc:
            raise CorporateActionObservationError(
                "eastmoney_dividend_pages_incomplete"
            ) from exc
        if (
            capture.provider != PROVIDER
            or capture.operation != "dividend"
            or capture.adapter_version != ADAPTER
            or capture.payload_format != PAYLOAD_FORMAT
            or json.loads(capture.request_json)
            != {
                "method": "GET",
                "url": URL,
                "parameters": _parameters(report, condition, page),
            }
            or capture.started_at
            < datetime.combine(day, time(21), ZoneInfo("Asia/Shanghai"))
        ):
            raise CorporateActionObservationError("eastmoney_dividend_capture_invalid")
        rows, count, pages = _page(store.read_bytes(capture.raw_object_ref))
        if (
            (expected is not None and expected != (count, pages))
            or capture.record_count != len(rows)
            or len(rows) != min(_PAGE_SIZE, count - (page - 1) * _PAGE_SIZE)
        ):
            raise CorporateActionObservationError("eastmoney_dividend_pages_incomplete")
        expected = count, pages
        result.extend(rows)
        if page == pages:
            return result
    raise CorporateActionObservationError("eastmoney_dividend_pages_incomplete")


def _terms(queries: list[list[dict[str, Any]]], *, day: date) -> list[dict[str, Any]]:
    terms: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for field, rows in zip(_DATE_QUERIES, queries, strict=True):
        seen = set()
        for row in rows:
            # Quotes and accounting ratios on the source page do not define
            # the distribution; only compare its actual terms across queries.
            row = {field: row[field] for field in _TERM_FIELDS}
            code = row["SECUCODE"]
            if (
                not isinstance(code, str)
                or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code)
                or row["SECURITY_CODE"] != code[:6]
                or _native_date(row[field]) != day.isoformat()
            ):
                raise CorporateActionObservationError(
                    "eastmoney_dividend_identity_invalid"
                )
            identity = code, row["REPORT_DATE"], row["PLAN_NOTICE_DATE"]
            if identity in seen or (identity in terms and terms[identity] != row):
                raise CorporateActionObservationError(
                    "eastmoney_dividend_terms_conflicting"
                )
            seen.add(identity)
            terms[identity] = row
    return list(terms.values())


def _calendar_queries(
    terms: list[dict[str, Any]],
) -> Iterator[tuple[str, list[str], date, date]]:
    implementations = [
        row
        for row in terms
        if row["ASSIGN_PROGRESS"] == "实施分配" and row["EQUITY_RECORD_DATE"]
    ]
    codes = sorted({row["SECUCODE"] for row in implementations})
    for offset in range(0, len(codes), 40):
        batch = codes[offset : offset + 40]
        dates = [
            date.fromisoformat(_native_date(row[field]))
            for row in implementations
            if row["SECUCODE"] in batch
            for field in ("EQUITY_RECORD_DATE", "EX_DIVIDEND_DATE")
            if row[field]
        ]
        start, end = min(dates), max(dates) + timedelta(days=366)
        condition = (
            "(SECUCODE in (" + ",".join('"' + code + '"' for code in batch) + "))"
        )
        condition += (
            f"(TRADE_DATE>='{start.isoformat()}')(TRADE_DATE<='{end.isoformat()}')"
        )
        yield condition, batch, start, end


def _record(row: dict[str, Any], calendar: list[dict[str, Any]]) -> dict[str, Any]:
    record: dict[str, Any] = dict.fromkeys((*DATE_FIELDS, *NUMBER_FIELDS))
    status = row["ASSIGN_PROGRESS"]
    if not isinstance(status, str) or not status.strip():
        raise CorporateActionObservationError("eastmoney_dividend_status_missing")
    record.update(
        source_code=row["SECUCODE"],
        implementation_status="实施" if status == "实施分配" else status,
        report_period=None
        if row["REPORT_DATE"] is None
        else _native_date(row["REPORT_DATE"]),
        announcement_date=None
        if row["PLAN_NOTICE_DATE"] is None
        else _native_date(row["PLAN_NOTICE_DATE"]),
        implementation_announcement_date=_native_date(row["NOTICE_DATE"])
        if status == "实施分配" and row["NOTICE_DATE"]
        else None,
        record_date=None
        if row["EQUITY_RECORD_DATE"] is None
        else _native_date(row["EQUITY_RECORD_DATE"]),
        ex_date=None
        if row["EX_DIVIDEND_DATE"] is None
        else _native_date(row["EX_DIVIDEND_DATE"]),
    )
    match = _PLAN.fullmatch(row["IMPL_PLAN_PROFILE"] or "")
    if match is None or not any(match.groups()[:3]):
        if status == "实施分配":
            raise CorporateActionObservationError("eastmoney_dividend_terms_unverified")
        return record
    bonus, capitalized, cash = (Decimal(value or "0") for value in match.groups()[:3])
    for field, value in (
        ("BONUS_RATIO", bonus),
        ("IT_RATIO", capitalized),
        ("BONUS_IT_RATIO", bonus + capitalized),
        ("PRETAX_BONUS_RMB", cash),
    ):
        if row[field] is not None and Decimal(_number_text(row[field])) != value:
            raise CorporateActionObservationError(
                "eastmoney_dividend_terms_conflicting"
            )
    record.update(
        bonus_share_ratio=_number_text(bonus / 10),
        capitalization_ratio=_number_text(capitalized / 10),
        stock_dividend_ratio=_number_text((bonus + capitalized) / 10),
        cash_dividend_before_tax=_number_text(cash / 10),
        cash_dividend_after_tax=None
        if match[4] is None
        else _number_text(Decimal(match[4]) / 10),
    )
    dates = {}
    for event in calendar:
        if (
            event["SECUCODE"] != row["SECUCODE"]
            or event["EVENT_CONTENT"] != row["IMPL_PLAN_PROFILE"]
        ):
            continue
        role = _ROLES.get(event["EVENT_TYPE"])
        if role is None:
            raise CorporateActionObservationError(
                "eastmoney_dividend_calendar_role_invalid"
            )
        value = _native_date(event["TRADE_DATE"])
        if record["record_date"] and value < record["record_date"]:
            continue
        if role in dates:
            raise CorporateActionObservationError(
                "eastmoney_dividend_calendar_ambiguous"
            )
        dates[role] = value
    for role in ("record_date", "ex_date"):
        if role in dates and dates[role] != record[role]:
            raise CorporateActionObservationError(
                "eastmoney_dividend_calendar_conflicting"
            )
    record.update(
        {role: dates.get(role) for role in ("pay_date", "share_listing_date")}
    )
    return record


def read_eastmoney_market_dividend_day(
    store: ContentAddressedObjectStore, ref: ObjectRef, value: dict[str, Any]
) -> dict[str, Any]:
    """Reconstruct every value from complete immutable pages, without network I/O."""
    if set(value) != {"provider", "date", "captures"} or value["provider"] != PROVIDER:
        raise CorporateActionObservationError("eastmoney_dividend_day_invalid")
    day = date.fromisoformat(value["date"])
    captures = [
        read_provider_capture(store, ObjectRef(**item)) for item in value["captures"]
    ]
    cursor = iter(captures)
    queries = [
        _read_query(store, cursor, _TERMS, f"({field}='{day.isoformat()}')", day=day)
        for field in _DATE_QUERIES
    ]
    terms = _terms(queries, day=day)
    calendar = []
    for condition, codes, start, end in _calendar_queries(terms):
        rows = _read_query(store, cursor, _CALENDAR, condition, day=day)
        if any(
            row["SECUCODE"] not in codes
            or row["SECURITY_CODE"] != row["SECUCODE"][:6]
            or not start.isoformat()
            <= _native_date(row["TRADE_DATE"])
            <= end.isoformat()
            for row in rows
        ):
            raise CorporateActionObservationError(
                "eastmoney_dividend_calendar_identity_invalid"
            )
        calendar.extend(rows)
    if next(cursor, None) is not None:
        raise CorporateActionObservationError("eastmoney_dividend_unexpected_capture")
    try:
        with localcontext() as context:
            context.traps[Inexact] = True
            records = _canonical_records([_record(row, calendar) for row in terms])
    except DecimalException as exc:
        raise CorporateActionObservationError(
            "eastmoney_dividend_precision_invalid"
        ) from exc
    latest = max(captures, key=lambda capture: capture.completed_at)
    return {
        "date": day,
        "provider": PROVIDER,
        "rows": [(record, latest) for record in records],
        "available_at": latest.completed_at,
        "oldest_captured_at": min(capture.completed_at for capture in captures),
        "observation_id": ref.object_id,
    }


def collect_eastmoney_market_dividend_day(
    store: ContentAddressedObjectStore,
    *,
    day: date,
    clock: Callable[[], datetime] | None = None,
    before_fetch: Callable[[], None] | None = None,
) -> ObjectRef:
    now = clock or (lambda: datetime.now(timezone.utc))
    if now() < datetime.combine(day, time(21), ZoneInfo("Asia/Shanghai")):
        raise CorporateActionObservationError("corporate_action_update_window_pending")
    captures: list[ProviderCapture] = []

    def query(report: str, condition: str) -> list[dict[str, Any]]:
        rows = []
        expected = None
        for page in range(1, _MAX_PAGES + 1):
            if before_fetch is not None:
                before_fetch()
            parameters = _parameters(report, condition, page)
            started = now()
            try:
                with provider_network_env():
                    response = requests.get(URL, params=parameters, timeout=20)
            except requests.RequestException as exc:
                raise CorporateActionObservationError(
                    "eastmoney_dividend_unavailable"
                ) from exc
            completed = now()
            raw = response.content
            try:
                data, count, pages = _page(raw)
            except (ValueError, TypeError, KeyError):
                data, count, pages = None, None, None
            capture = capture_provider_payload(
                store,
                provider=PROVIDER,
                operation="dividend",
                request={"method": "GET", "url": URL, "parameters": parameters},
                raw_payload=raw,
                payload_format=PAYLOAD_FORMAT,
                adapter_version=ADAPTER,
                started_at=started,
                completed_at=completed,
                record_count=len(data) if data is not None else None,
            )
            captures.append(capture)
            if (
                response.status_code != 200
                or data is None
                or count is None
                or pages is None
                or (expected is not None and expected != (count, pages))
                or len(data) != min(_PAGE_SIZE, count - (page - 1) * _PAGE_SIZE)
            ):
                raise CorporateActionObservationError(
                    "eastmoney_dividend_page_invalid", capture_id=capture.capture_id
                )
            expected = count, pages
            rows.extend(data)
            if page == pages:
                return rows
        raise CorporateActionObservationError("eastmoney_dividend_pages_incomplete")

    queries = [
        query(_TERMS, f"({field}='{day.isoformat()}')") for field in _DATE_QUERIES
    ]
    terms = _terms(queries, day=day)
    for condition, _, _, _ in _calendar_queries(terms):
        query(_CALENDAR, condition)
    value = {
        "provider": PROVIDER,
        "date": day.isoformat(),
        "captures": [
            {
                "object_id": capture.capture_id,
                "size_bytes": capture.capture_ref.size_bytes,
            }
            for capture in captures
        ],
    }
    ref = store.put_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    read_eastmoney_market_dividend_day(store, ref, value)
    return ref
