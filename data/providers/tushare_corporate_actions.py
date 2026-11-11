"""Explicit, bounded TuShare dividend observations; no import-time SDK calls."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal, DecimalException
from typing import Any

import pandas as pd

from core.types import InstrumentKey, InstrumentType
from data.market.capture import (
    capture_provider_payload,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.market.corporate_actions import (
    CorporateActionObservationError,
    publish_corporate_action_observation,
)
from data.providers.tushare import (
    TushareDailyBarRequestError,
    _request_target,
    tushare_pro_client,
)
from data.storage.objects import ContentAddressedObjectStore, ObjectRef

ADAPTER_VERSION = "karkinos.tushare.dividend.v1"
PAYLOAD_FORMAT = "tushare.pro.dividend.dataframe.v1"
_DATE_MAPPING = {
    "end_date": "report_period",
    "ann_date": "announcement_date",
    "imp_ann_date": "implementation_announcement_date",
    "record_date": "record_date",
    "ex_date": "ex_date",
    "pay_date": "pay_date",
    "div_listdate": "share_listing_date",
    "base_date": "base_date",
}
_NUMBER_MAPPING = {
    "cash_div_tax": "cash_dividend_before_tax",
    "cash_div": "cash_dividend_after_tax",
    "stk_div": "stock_dividend_ratio",
    "stk_bo_rate": "bonus_share_ratio",
    "stk_co_rate": "capitalization_ratio",
    "base_share": "base_shares",
}
DIVIDEND_FIELDS = ",".join(("ts_code", "div_proc", *_DATE_MAPPING, *_NUMBER_MAPPING))


class TushareDividendRequestDeferred(CorporateActionObservationError):
    """Keep completed source captures while the provider's rate window resets."""

    def __init__(self, *, retry_seconds: int, failure_evidence_ref: str) -> None:
        super().__init__("tushare_dividend_rate_limited")
        self.retry_seconds = retry_seconds
        self.failure_evidence_ref = failure_evidence_ref


def collect_tushare_dividend_observation(
    store: ContentAddressedObjectStore,
    *,
    instrument: InstrumentKey,
    client: Any = None,
    token: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ObjectRef:
    """Capture one stock's response before interpreting even malformed records."""
    if instrument.instrument_type is not InstrumentType.STOCK:
        raise CorporateActionObservationError("corporate_action_instrument_unsupported")
    try:
        _, ts_code = _request_target(instrument)
    except TushareDailyBarRequestError as exc:
        raise CorporateActionObservationError(
            "tushare_dividend_symbol_unsupported"
        ) from exc
    now = clock or (lambda: datetime.now(timezone.utc))
    started = now()
    try:
        provider = client if client is not None else tushare_pro_client(token)
        response = provider.dividend(ts_code=ts_code, fields=DIVIDEND_FIELDS)
    except Exception as exc:
        raise CorporateActionObservationError("tushare_dividend_unavailable") from exc
    completed = now()
    capture = capture_provider_payload(
        store,
        provider="tushare",
        operation="dividend",
        request={
            "instrument": {"symbol": instrument.symbol, "instrument_type": "stock"},
            "ts_code": ts_code,
            "fields": DIVIDEND_FIELDS,
        },
        raw_payload=_raw_response(response),
        payload_format=PAYLOAD_FORMAT,
        adapter_version=ADAPTER_VERSION,
        started_at=started,
        completed_at=completed,
        record_count=len(response) if isinstance(response, pd.DataFrame) else None,
    )
    try:
        records = _normalize_response(response, ts_code)
        return publish_corporate_action_observation(
            store, instrument=instrument, capture=capture, records=records
        )
    except (TypeError, ValueError) as exc:
        code = (
            str(exc)
            if isinstance(exc, CorporateActionObservationError)
            else "tushare_dividend_response_invalid"
        )
        raise CorporateActionObservationError(
            code, capture_id=capture.capture_id
        ) from exc


def _normalize_response(response: Any, ts_code: str) -> list[dict[str, Any]]:
    if not isinstance(response, pd.DataFrame):
        raise CorporateActionObservationError("tushare_dividend_response_type_invalid")
    if len(response) >= 2000:
        raise CorporateActionObservationError(
            "tushare_dividend_response_may_be_truncated"
        )
    if response.empty:
        return []
    if response.columns.has_duplicates or set(DIVIDEND_FIELDS.split(",")) - set(
        response.columns
    ):
        raise CorporateActionObservationError(
            "tushare_dividend_response_fields_invalid"
        )
    records = []
    for source in response.to_dict(orient="records"):
        if source["ts_code"] != ts_code:
            raise CorporateActionObservationError(
                "tushare_dividend_response_instrument_mismatch"
            )
        status = source["div_proc"]
        if not isinstance(status, str) or not status.strip():
            raise CorporateActionObservationError("tushare_dividend_progress_missing")
        row: dict[str, Any] = {
            "source_code": ts_code,
            "implementation_status": status.strip(),
        }
        row.update(
            {
                target: _date_text(source[field])
                for field, target in _DATE_MAPPING.items()
            }
        )
        row.update(
            {
                target: _number_text(
                    source[field], multiplier=10000 if field == "base_share" else 1
                )
                for field, target in _NUMBER_MAPPING.items()
            }
        )
        records.append(row)
    return records


def _date_text(value: Any) -> str | None:
    if _missing(value):
        return None
    text = (
        value.isoformat()
        if isinstance(value, date) and not isinstance(value, datetime)
        else str(value).strip()
    )
    try:
        result = (
            datetime.strptime(text, "%Y%m%d").date()
            if len(text) == 8
            else date.fromisoformat(text)
        )
    except ValueError as exc:
        raise CorporateActionObservationError("tushare_dividend_date_invalid") from exc
    return result.isoformat()


def _number_text(value: Any, *, multiplier: int) -> str | None:
    if _missing(value):
        return None
    try:
        number = Decimal(str(value)) * multiplier
        if isinstance(value, bool) or not number.is_finite() or number < 0:
            raise ValueError("invalid_number")
        return format(number.normalize(), "f") if number else "0"
    except (DecimalException, ValueError, TypeError) as exc:
        raise CorporateActionObservationError(
            "tushare_dividend_number_invalid"
        ) from exc


def _missing(value: Any) -> bool:
    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or bool(pd.isna(value))
    )


def _raw_response(response: Any) -> bytes:
    # This is an SDK value snapshot, explicitly not HTTP wire bytes. Nonfinite
    # values remain diagnosable strings; normalization may reject them afterwards.
    payload: dict[str, Any]
    if isinstance(response, pd.DataFrame):
        payload = {
            "columns": [_raw_value(item) for item in response.columns],
            "index": [_raw_value(item) for item in response.index],
            "data": [
                [_raw_value(item) for item in row]
                for row in response.itertuples(index=False, name=None)
            ],
        }
    else:
        payload = {
            "returned_type": type(response).__name__,
            "value": _raw_value(response),
        }
    return json.dumps(
        {"schema_version": PAYLOAD_FORMAT, "response": payload},
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _raw_value(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except ValueError:
            return (
                _raw_value(value.tolist()) if hasattr(value, "tolist") else str(value)
            )
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_raw_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _raw_value(item) for key, item in value.items()}
    return str(value)


def collect_tushare_market_dividend_day(
    store: ContentAddressedObjectStore,
    *,
    day: date,
    client: Any = None,
    token: str | None = None,
    clock: Callable[[], datetime] | None = None,
    before_fetch: Callable[[], None] | None = None,
    resume_ref: str | None = None,
) -> ObjectRef:
    """Four documented date queries, never fabricated per-stock SDK requests."""
    from datetime import time
    from zoneinfo import ZoneInfo

    from data.market.corporate_actions import (
        DIVIDEND_DATE_QUERIES,
        publish_market_dividend_day,
    )

    now = clock or (lambda: datetime.now(timezone.utc))
    if now() < datetime.combine(day, time(21), ZoneInfo("Asia/Shanghai")):
        raise CorporateActionObservationError("tushare_dividend_update_window_pending")
    captures = _restore_dividend_queries(store, resume_ref, day=day, now=now())
    completed = {
        next(key for key in json.loads(capture.request_json) if key != "fields")
        for capture, _ in captures
    }
    provider = client if client is not None else tushare_pro_client(token)
    for field in DIVIDEND_DATE_QUERIES:
        if field in completed:
            continue
        if before_fetch is not None:
            before_fetch()
        started = now()
        try:
            response = provider.dividend(
                **{field: day.strftime("%Y%m%d"), "fields": DIVIDEND_FIELDS}
            )
        except Exception as exc:
            frequency = re.search(r"频率超限.*?\d+次/(分钟|小时|天)", str(exc))
            if frequency:
                progress = store.put_bytes(
                    json.dumps(
                        {
                            "date": day.isoformat(),
                            "capture_ids": [
                                capture.capture_id for capture, _ in captures
                            ],
                        },
                        sort_keys=True,
                    ).encode("utf-8")
                )
                raise TushareDividendRequestDeferred(
                    retry_seconds={"分钟": 60, "小时": 3600, "天": 86400}[frequency[1]],
                    failure_evidence_ref=progress.object_id,
                ) from exc
            raise CorporateActionObservationError(
                "tushare_dividend_unavailable"
            ) from exc
        capture = capture_provider_payload(
            store,
            provider="tushare",
            operation="dividend",
            request={field: day.strftime("%Y%m%d"), "fields": DIVIDEND_FIELDS},
            raw_payload=_raw_response(response),
            payload_format=PAYLOAD_FORMAT,
            adapter_version=ADAPTER_VERSION,
            started_at=started,
            completed_at=now(),
            record_count=len(response) if isinstance(response, pd.DataFrame) else None,
        )
        try:
            captures.append((capture, _normalize_market_dividend_response(response)))
        except (TypeError, ValueError) as exc:
            raise CorporateActionObservationError(
                str(exc), capture_id=capture.capture_id
            ) from exc
    return publish_market_dividend_day(store, day=day, captures_and_records=captures)


def _normalize_market_dividend_response(response):
    if not isinstance(response, pd.DataFrame):
        raise CorporateActionObservationError("tushare_dividend_response_type_invalid")
    if len(response) >= 2000:
        raise CorporateActionObservationError(
            "tushare_dividend_response_may_be_truncated"
        )
    records = []
    if response.empty:
        return records
    if response.columns.has_duplicates or set(DIVIDEND_FIELDS.split(",")) - set(
        response.columns
    ):
        raise CorporateActionObservationError(
            "tushare_dividend_response_fields_invalid"
        )
    for code in response["ts_code"].unique():
        if (
            not isinstance(code, str)
            or len(code) != 9
            or code[6] != "."
            or code[7:] not in {"SH", "SZ", "BJ"}
            or not code[:6].isdigit()
        ):
            raise CorporateActionObservationError(
                "tushare_dividend_response_instrument_mismatch"
            )
        records.extend(_normalize_response(response[response["ts_code"] == code], code))
    return records


def _restore_dividend_queries(store, resume_ref, *, day, now):
    """Reopen original bytes; a retry pointer never certifies complete coverage."""
    from datetime import time
    from zoneinfo import ZoneInfo

    from data.market.corporate_actions import DIVIDEND_DATE_QUERIES

    if resume_ref is None:
        return []
    progress = json.loads(store.read_bytes(store.resolve_ref(resume_ref)))
    if (
        set(progress) != {"date", "capture_ids"}
        or progress["date"] != day.isoformat()
        or not isinstance(progress["capture_ids"], list)
        or len(progress["capture_ids"]) >= len(DIVIDEND_DATE_QUERIES)
    ):
        raise CorporateActionObservationError("tushare_dividend_resume_invalid")
    captures = []
    for field, identity in zip(DIVIDEND_DATE_QUERIES, progress["capture_ids"]):
        capture = read_provider_capture(store, store.resolve_ref(identity))
        if (
            capture.provider != "tushare"
            or capture.operation != "dividend"
            or capture.adapter_version != ADAPTER_VERSION
            or capture.payload_format != PAYLOAD_FORMAT
            or json.loads(capture.request_json)
            != {field: day.strftime("%Y%m%d"), "fields": DIVIDEND_FIELDS}
            or capture.started_at
            < datetime.combine(day, time(21), ZoneInfo("Asia/Shanghai"))
            or capture.completed_at > now
        ):
            raise CorporateActionObservationError("tushare_dividend_resume_invalid")
        raw = json.loads(read_provider_raw_payload(store, capture))
        if raw.get("schema_version") != PAYLOAD_FORMAT:
            raise CorporateActionObservationError("tushare_dividend_resume_invalid")
        response = pd.DataFrame(**raw["response"])
        if len(response) != capture.record_count:
            raise CorporateActionObservationError("tushare_dividend_resume_invalid")
        # The SDK snapshot encodes pandas missing scalars as strings. Restore
        # their missingness before normalization; do not turn them into zero or
        # accept other nonfinite values such as infinity.
        response = response.replace(
            {
                field: {"nan": None, "NaT": None, "<NA>": None}
                for field in (*_DATE_MAPPING, *_NUMBER_MAPPING)
                if field in response
            }
        )
        captures.append((capture, _normalize_market_dividend_response(response)))
    return captures
