"""BaoStock immutable daily-bar adapter for the canonical market-data pipeline."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import math
import re
import threading
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import (
    DailyBarCapability,
    DailyBarProviderUnavailableError,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)

BAOSTOCK_DAILY_BAR_ADAPTER_VERSION = "karkinos.baostock.daily_bar.v2"
BAOSTOCK_DAILY_BAR_PAYLOAD_FORMAT = "baostock.history_k_data_plus.rows.v2"
BAOSTOCK_DAILY_BAR_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="baostock",
    upstream_group="baostock",
    adapter_version=BAOSTOCK_DAILY_BAR_ADAPTER_VERSION,
    unsupported_stock_prefixes=("4", "8", "92"),
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="query_history_k_data_plus",
            instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
            price_basis="unadjusted",
        ),
    ),
)

_FIELDS = (
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adjustflag",
    "tradestatus",
)
_FIELDS_TEXT = ",".join(_FIELDS)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SIX_DIGIT_SYMBOL = re.compile(r"^[0-9]{6}$")
_SESSION_LOCK = threading.Lock()


class BaoStockDailyBarError(RuntimeError):
    """Base failure for the immutable BaoStock daily-bar adapter."""


class BaoStockDailyBarUnavailableError(
    BaoStockDailyBarError,
    DailyBarProviderUnavailableError,
):
    """BaoStock could not complete external SDK/session I/O."""


class BaoStockDailyBarRequestError(BaoStockDailyBarError):
    """The canonical request is outside the reviewed BaoStock capability."""


class BaoStockDailyBarResponseError(BaoStockDailyBarError):
    """BaoStock returned data that cannot be represented safely."""

    captured_batch: ProviderDailyBarBatch | None = None

    @property
    def public_error_code(self) -> str:
        code = str(self).split(":", 1)[0]
        return (
            code
            if code.startswith("baostock_response_")
            else "baostock_response_invalid"
        )


class _Result(Protocol):
    error_code: str
    error_msg: str
    fields: list[str]

    def next(self) -> bool: ...

    def get_row_data(self) -> list[str]: ...


class _BaoStockClient(Protocol):
    def login(self, user_id: str = "anonymous", password: str = "123456") -> object: ...

    def logout(self, user_id: str = "anonymous") -> object: ...

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        start_date: str | None = None,
        end_date: str | None = None,
        frequency: str = "d",
        adjustflag: str = "3",
    ) -> _Result: ...


class BaoStockDailyBarProvider:
    """Fetch raw/unadjusted SSE/SZSE stock and ETF daily bars from BaoStock."""

    def __init__(
        self,
        client: _BaoStockClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return BAOSTOCK_DAILY_BAR_DESCRIPTOR

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        if not isinstance(request, DailyBarRequest):
            raise TypeError("baostock_daily_bar_request_invalid")
        targets = tuple(
            (instrument, _provider_code(instrument))
            for instrument in request.instruments
        )
        started_at = _aware_utc(self._clock(), field="started_at")
        if started_at < _session_close_utc(request.end_date):
            raise BaoStockDailyBarRequestError("baostock_daily_bar_session_not_closed")

        client = self._resolve_client()
        rows: list[ProviderDailyBarRow] = []
        calls: list[dict[str, object]] = []
        failure = None

        # BaoStock's SDK owns one module-global socket/session.  Serialize the
        # complete login/query/logout lifecycle inside one process so concurrent
        # Karkinos callers cannot overwrite each other's session state.
        with _SESSION_LOCK:
            _login(client)
            try:
                for instrument, code in targets:
                    result = _query(
                        client,
                        code=code,
                        session=request.start_date,
                        end_session=request.end_date,
                    )
                    raw_rows = _consume_result(result)
                    calls.append(
                        {
                            "code": code,
                            "fields": list(result.fields),
                            "rows": raw_rows,
                        }
                    )
                    try:
                        parsed = _rows_from_result(
                            raw_rows,
                            fields=tuple(result.fields),
                            instrument=instrument,
                            expected_code=code,
                            expected_session=request.start_date,
                            expected_end=request.end_date,
                        )
                    except BaoStockDailyBarResponseError as exc:
                        failure = exc
                        break
                    rows.extend(parsed)
            finally:
                _logout(client)

        completed_at = _aware_utc(self._clock(), field="completed_at")
        if completed_at < started_at:
            raise BaoStockDailyBarError("baostock_provider_clock_moved_backwards")

        raw_payload = json.dumps(
            {
                "schema": BAOSTOCK_DAILY_BAR_PAYLOAD_FORMAT,
                "request": {
                    "frequency": "d",
                    "adjustflag": "3",
                    "start_date": request.start_date.isoformat(),
                    "end_date": request.end_date.isoformat(),
                    "fields": list(_FIELDS),
                },
                "calls": calls,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

        batch = ProviderDailyBarBatch(
            provider="baostock",
            adapter_version=BAOSTOCK_DAILY_BAR_ADAPTER_VERSION,
            payload_format=BAOSTOCK_DAILY_BAR_PAYLOAD_FORMAT,
            started_at=started_at,
            completed_at=completed_at,
            raw_payload=raw_payload,
            rows=tuple(
                sorted(
                    rows,
                    key=lambda row: (
                        row.instrument.instrument_type.value,
                        row.instrument.symbol,
                    ),
                )
            ),
        )
        if failure is not None:
            failure.captured_batch = batch
            raise failure
        return batch

    def _resolve_client(self) -> _BaoStockClient:
        if self._client is not None:
            return self._client
        try:
            module = importlib.import_module("baostock")
        except (ImportError, OSError) as exc:
            raise BaoStockDailyBarUnavailableError("baostock_sdk_load_failed") from exc
        self._client = module
        return module


def _login(client: _BaoStockClient) -> None:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = client.login()
    except Exception as exc:
        raise BaoStockDailyBarUnavailableError("baostock_login_failed") from exc
    if str(getattr(result, "error_code", "")) != "0":
        raise BaoStockDailyBarUnavailableError("baostock_login_rejected")


def _logout(client: _BaoStockClient) -> None:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = client.logout()
    except Exception as exc:
        raise BaoStockDailyBarUnavailableError("baostock_logout_failed") from exc
    if result is not None and str(getattr(result, "error_code", "")) not in {"", "0"}:
        raise BaoStockDailyBarUnavailableError("baostock_logout_rejected")


def _query(
    client: _BaoStockClient,
    *,
    code: str,
    session: date,
    end_session: date | None = None,
) -> _Result:
    try:
        result = client.query_history_k_data_plus(
            code,
            _FIELDS_TEXT,
            start_date=session.isoformat(),
            end_date=(end_session or session).isoformat(),
            frequency="d",
            adjustflag="3",
        )
    except Exception as exc:
        raise BaoStockDailyBarUnavailableError(
            f"baostock_history_query_failed:{code}"
        ) from exc
    if str(getattr(result, "error_code", "")) != "0":
        raise BaoStockDailyBarUnavailableError(
            f"baostock_history_query_rejected:{code}"
        )
    fields = getattr(result, "fields", None)
    if not isinstance(fields, list) or tuple(fields) != _FIELDS:
        raise BaoStockDailyBarResponseError("baostock_response_fields_invalid")
    return result


def _consume_result(result: _Result) -> list[list[str]]:
    rows: list[list[str]] = []
    try:
        while result.next():
            row = result.get_row_data()
            if not isinstance(row, list) or not all(
                isinstance(item, str) for item in row
            ):
                raise BaoStockDailyBarResponseError("baostock_response_row_invalid")
            rows.append(list(row))
    except BaoStockDailyBarResponseError:
        raise
    except Exception as exc:
        raise BaoStockDailyBarResponseError(
            "baostock_response_iteration_failed"
        ) from exc
    return rows


def _rows_from_result(
    raw_rows: list[list[str]],
    *,
    fields: tuple[str, ...],
    instrument: InstrumentKey,
    expected_code: str,
    expected_session: date,
    expected_end: date | None = None,
) -> list[ProviderDailyBarRow]:
    result: list[ProviderDailyBarRow] = []
    for raw in raw_rows:
        if len(raw) != len(fields):
            raise BaoStockDailyBarResponseError("baostock_response_row_width_invalid")
        row = dict(zip(fields, raw, strict=True))
        if row["code"] != expected_code:
            raise BaoStockDailyBarResponseError("baostock_response_code_mismatch")
        if row["adjustflag"] != "3":
            raise BaoStockDailyBarResponseError("baostock_response_adjustflag_invalid")
        if row["tradestatus"] not in {"0", "1"}:
            raise BaoStockDailyBarResponseError("baostock_response_tradestatus_invalid")

        session = _trade_date(row["date"])
        if not expected_session <= session <= (expected_end or expected_session):
            raise BaoStockDailyBarResponseError(
                f"baostock_response_session_mismatch:{session.isoformat()}"
            )

        # A source-declared halted session is a status fact, not a traded-price
        # observation. Bao may retain previous OHLC while leaving volume blank.
        # Its entire raw row remains captured. Missing planned bars still block
        # the unchanged membership quality check; no last price is fabricated.
        if row["tradestatus"] == "0":
            continue

        result.append(
            ProviderDailyBarRow(
                instrument=instrument,
                session_date=session,
                event_time=_session_close_utc(session),
                # BaoStock does not expose a per-row publication timestamp.
                # ingestion conservatively falls back to batch.completed_at.
                available_at=None,
                open_value=_decimal(row["open"], field="open"),
                high_value=_decimal(row["high"], field="high"),
                low_value=_decimal(row["low"], field="low"),
                close_value=_decimal(row["close"], field="close"),
                # BaoStock daily history documents/returns volume in shares and
                # amount in CNY, already matching Karkinos canonical units.
                volume=_decimal(row["volume"], field="volume"),
                amount=_decimal(row["amount"], field="amount"),
                suspended=row["tradestatus"] == "0",
            )
        )
    if len({row.session_date for row in result}) != len(result):
        raise BaoStockDailyBarResponseError(
            f"baostock_response_duplicate_session:{expected_session.isoformat()}"
        )
    return result


def _provider_code(instrument: InstrumentKey) -> str:
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise BaoStockDailyBarRequestError(
            f"baostock_instrument_type_unsupported:{instrument.instrument_type.value}"
        )
    symbol = instrument.symbol.strip()
    if _SIX_DIGIT_SYMBOL.fullmatch(symbol) is None:
        raise BaoStockDailyBarRequestError(
            f"baostock_symbol_must_be_six_digits:{symbol}"
        )

    if instrument.instrument_type is InstrumentType.STOCK:
        if symbol.startswith(("600", "601", "603", "605", "688", "689")):
            exchange = "sh"
        elif symbol.startswith(("000", "001", "002", "003", "300", "301", "302")):
            exchange = "sz"
        elif symbol.startswith(("4", "8", "920")):
            raise BaoStockDailyBarRequestError(
                f"baostock_beijing_exchange_unsupported:{symbol}"
            )
        else:
            raise BaoStockDailyBarRequestError(
                f"baostock_stock_exchange_unknown:{symbol}"
            )
    else:
        if symbol.startswith("5"):
            exchange = "sh"
        elif symbol.startswith("1"):
            exchange = "sz"
        else:
            raise BaoStockDailyBarRequestError(
                f"baostock_etf_exchange_unknown:{symbol}"
            )

    return f"{exchange}.{symbol}"


def read_baostock_historical_status(store, capture_ref):
    """Read explicit dated statuses from a reviewed capture, without price bars.

    Missing rows are unknown. Capture completion remains the availability of
    this historical backfill; it never establishes historical decision timing.
    These are BaoStock observations, not independent-source status agreement.
    """
    from data.market.capture import read_provider_capture, read_provider_raw_payload
    from data.market.contracts import MAX_DAILY_BAR_RANGE_JOB_INSTRUMENTS

    capture = read_provider_capture(store, capture_ref)
    if (
        capture.provider != "baostock"
        or capture.operation != "daily_bars"
        or capture.adapter_version != "karkinos.baostock.daily_bar.v2"
        or capture.payload_format != "baostock.history_k_data_plus.rows.v2"
    ):
        raise ValueError("baostock_historical_status_source_invalid")
    request = json.loads(capture.request_json)
    instruments = tuple(
        InstrumentKey.from_values(row["symbol"], row["instrument_type"])
        for row in request["instruments"]
        if isinstance(row, dict) and set(row) == {"symbol", "instrument_type"}
    )
    planned = DailyBarRequest(
        instruments,
        date.fromisoformat(request["start_date"]),
        date.fromisoformat(request["end_date"]),
    )
    if (
        request != planned.to_capture_request()
        or len(instruments) > MAX_DAILY_BAR_RANGE_JOB_INSTRUMENTS
        or (planned.end_date - planned.start_date).days >= 3653
        or any(key.instrument_type is not InstrumentType.STOCK for key in instruments)
        or capture.started_at < _session_close_utc(planned.end_date)
    ):
        raise ValueError("baostock_historical_status_request_invalid")
    payload = json.loads(read_provider_raw_payload(store, capture))
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "request", "calls"}
        or payload["schema"] != capture.payload_format
        or payload["request"]
        != {
            "frequency": "d",
            "adjustflag": "3",
            "start_date": planned.start_date.isoformat(),
            "end_date": planned.end_date.isoformat(),
            "fields": list(_FIELDS),
        }
        or not isinstance(payload["calls"], list)
        or len(payload["calls"]) != len(instruments)
    ):
        raise ValueError("baostock_historical_status_payload_invalid")
    expected = {_provider_code(key): key for key in instruments}
    seen = set()
    statuses: dict[date, dict[InstrumentKey, str]] = {}
    parsed_count = 0
    for call in payload["calls"]:
        if (
            not isinstance(call, dict)
            or set(call) != {"code", "fields", "rows"}
            or call["code"] not in expected
            or call["code"] in seen
            or call["fields"] != list(_FIELDS)
            or not isinstance(call["rows"], list)
            or len(call["rows"]) > (planned.end_date - planned.start_date).days + 1
            or any(
                not isinstance(row, list)
                or len(row) != len(_FIELDS)
                or not all(isinstance(value, str) for value in row)
                for row in call["rows"]
            )
        ):
            raise ValueError("baostock_historical_status_call_invalid")
        seen.add(call["code"])
        key = expected[call["code"]]
        parsed_count += len(
            _rows_from_result(
                call["rows"],
                fields=_FIELDS,
                instrument=key,
                expected_code=call["code"],
                expected_session=planned.start_date,
                expected_end=planned.end_date,
            )
        )
        for row in call["rows"]:
            day = date.fromisoformat(row[0])
            if day.isoformat() != row[0] or key in statuses.get(day, {}):
                raise ValueError("baostock_historical_status_session_invalid")
            if row[-1] == "0" and any(
                value.strip() and _decimal(value, field=field) != 0
                for field, value in zip(("volume", "amount"), row[6:8], strict=True)
            ):
                raise ValueError("baostock_historical_status_activity_conflict")
            statuses.setdefault(day, {})[key] = row[-1]
    if capture.record_count != parsed_count:
        raise ValueError("baostock_historical_status_record_count_invalid")
    return capture, planned, statuses


def _trade_date(value: str) -> date:
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise BaoStockDailyBarResponseError("baostock_trade_date_invalid") from exc
    if parsed.isoformat() != text:
        raise BaoStockDailyBarResponseError("baostock_trade_date_invalid")
    return parsed


def _decimal(value: str, *, field: str) -> Decimal:
    text = value.strip()
    if not text:
        raise BaoStockDailyBarResponseError(f"baostock_response_number_missing:{field}")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise BaoStockDailyBarResponseError(
            f"baostock_response_number_invalid:{field}"
        ) from exc
    if not result.is_finite():
        raise BaoStockDailyBarResponseError(f"baostock_response_number_invalid:{field}")
    return result


def _session_close_utc(session: date) -> datetime:
    return datetime.combine(session, time(15), _SHANGHAI).astimezone(timezone.utc)


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"baostock_{field}_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"baostock_{field}_must_be_timezone_aware")
    result = value.astimezone(timezone.utc)
    if not math.isfinite(result.timestamp()):
        raise ValueError(f"baostock_{field}_invalid")
    return result
