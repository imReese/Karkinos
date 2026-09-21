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

BAOSTOCK_DAILY_BAR_ADAPTER_VERSION = "karkinos.baostock.daily_bar.v1"
BAOSTOCK_DAILY_BAR_PAYLOAD_FORMAT = "baostock.history_k_data_plus.rows.v1"
BAOSTOCK_DAILY_BAR_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="baostock",
    upstream_group="baostock",
    adapter_version=BAOSTOCK_DAILY_BAR_ADAPTER_VERSION,
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
        if request.start_date != request.end_date:
            raise BaoStockDailyBarRequestError(
                "baostock_daily_bar_request_must_be_single_session"
            )

        targets = tuple(
            (instrument, _provider_code(instrument))
            for instrument in request.instruments
        )
        started_at = _aware_utc(self._clock(), field="started_at")
        if started_at < _session_close_utc(request.start_date):
            raise BaoStockDailyBarRequestError("baostock_daily_bar_session_not_closed")

        client = self._resolve_client()
        rows: list[ProviderDailyBarRow] = []
        calls: list[dict[str, object]] = []

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
                    )
                    raw_rows = _consume_result(result)
                    parsed = _rows_from_result(
                        raw_rows,
                        fields=tuple(result.fields),
                        instrument=instrument,
                        expected_code=code,
                        expected_session=request.start_date,
                    )
                    rows.extend(parsed)
                    calls.append(
                        {
                            "code": code,
                            "fields": list(result.fields),
                            "rows": raw_rows,
                        }
                    )
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

        return ProviderDailyBarBatch(
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
) -> _Result:
    try:
        result = client.query_history_k_data_plus(
            code,
            _FIELDS_TEXT,
            start_date=session.isoformat(),
            end_date=session.isoformat(),
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
        if session != expected_session:
            raise BaoStockDailyBarResponseError(
                f"baostock_response_session_mismatch:{session.isoformat()}"
            )

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
    if len(result) > 1:
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
        elif symbol.startswith(("000", "001", "002", "003", "300", "301")):
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
