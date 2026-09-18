"""TuShare immutable daily-bar adapter for the canonical market-data pipeline."""

from __future__ import annotations

import importlib
import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import (
    DailyBarCapability,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)

TUSHARE_DAILY_BAR_ADAPTER_VERSION = "karkinos.tushare.daily_bar.v1"
TUSHARE_DAILY_BAR_PAYLOAD_FORMAT = "tushare.pro.daily_bar.dataframe.v1"
TUSHARE_DAILY_BAR_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="tushare",
    upstream_group="tushare",
    adapter_version=TUSHARE_DAILY_BAR_ADAPTER_VERSION,
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="daily",
            instrument_types=(InstrumentType.STOCK,),
            price_basis="unadjusted",
        ),
        DailyBarCapability(
            endpoint="fund_daily",
            instrument_types=(InstrumentType.ETF,),
            price_basis="unadjusted",
        ),
    ),
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SIX_DIGIT_SYMBOL = re.compile(r"^[0-9]{6}$")
_LOT_TO_SHARES = Decimal("100")
_THOUSAND_YUAN_TO_YUAN = Decimal("1000")


class TushareDailyBarError(RuntimeError):
    """Base failure for the immutable TuShare daily-bar adapter."""


class TushareDailyBarRequestError(TushareDailyBarError):
    """The canonical request is outside the reviewed TuShare capability."""


class TushareDailyBarResponseError(TushareDailyBarError):
    """TuShare returned data that cannot be represented safely."""


class _TusharePro(Protocol):
    def daily(self, **kwargs: object) -> pd.DataFrame: ...

    def fund_daily(self, **kwargs: object) -> pd.DataFrame: ...


class TushareDailyBarProvider:
    """Fetch raw/unadjusted stock and ETF daily bars from TuShare Pro."""

    def __init__(
        self,
        client: _TusharePro | None = None,
        *,
        token: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._token = token
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return TUSHARE_DAILY_BAR_DESCRIPTOR

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        if not isinstance(request, DailyBarRequest):
            raise TypeError("tushare_daily_bar_request_invalid")
        if request.start_date != request.end_date:
            raise TushareDailyBarRequestError(
                "tushare_daily_bar_request_must_be_single_session"
            )

        started_at = _aware_utc(self._clock(), field="started_at")
        if started_at < _session_close_utc(request.start_date):
            raise TushareDailyBarRequestError("tushare_daily_bar_session_not_closed")

        client = self._resolve_client()
        rows: list[ProviderDailyBarRow] = []
        captures: list[dict[str, object]] = []
        for instrument in request.instruments:
            endpoint, ts_code = _request_target(instrument)
            method = getattr(client, endpoint)
            try:
                frame = method(
                    ts_code=ts_code,
                    start_date=request.start_date.strftime("%Y%m%d"),
                    end_date=request.end_date.strftime("%Y%m%d"),
                )
            except Exception as exc:
                raise TushareDailyBarError(
                    f"tushare_{endpoint}_failed:{ts_code}"
                ) from exc
            if not isinstance(frame, pd.DataFrame):
                raise TushareDailyBarResponseError(
                    f"tushare_response_must_be_dataframe:{endpoint}"
                )
            parsed_rows = _rows_from_frame(
                frame,
                instrument=instrument,
                expected_session=request.start_date,
                endpoint=endpoint,
            )
            captures.append(
                {
                    "endpoint": endpoint,
                    "ts_code": ts_code,
                    "frame": _serialize_dataframe(frame),
                }
            )
            rows.extend(parsed_rows)

        completed_at = _aware_utc(self._clock(), field="completed_at")
        if completed_at < started_at:
            raise TushareDailyBarError("tushare_provider_clock_moved_backwards")

        payload = json.dumps(
            {
                "schema": TUSHARE_DAILY_BAR_PAYLOAD_FORMAT,
                "calls": captures,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return ProviderDailyBarBatch(
            provider="tushare",
            adapter_version=TUSHARE_DAILY_BAR_ADAPTER_VERSION,
            payload_format=TUSHARE_DAILY_BAR_PAYLOAD_FORMAT,
            started_at=started_at,
            completed_at=completed_at,
            raw_payload=payload,
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

    def _resolve_client(self) -> _TusharePro:
        if self._client is not None:
            return self._client
        try:
            module = importlib.import_module("tushare")
        except (ImportError, OSError) as exc:
            raise TushareDailyBarError("tushare_sdk_load_failed") from exc
        try:
            return module.pro_api(self._token) if self._token else module.pro_api()
        except Exception as exc:
            raise TushareDailyBarError("tushare_client_initialization_failed") from exc


def _request_target(instrument: InstrumentKey) -> tuple[str, str]:
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise TushareDailyBarRequestError(
            f"tushare_instrument_type_unsupported:{instrument.instrument_type.value}"
        )
    symbol = instrument.symbol.strip()
    if _SIX_DIGIT_SYMBOL.fullmatch(symbol) is None:
        raise TushareDailyBarRequestError(f"tushare_symbol_must_be_six_digits:{symbol}")
    if instrument.instrument_type is InstrumentType.STOCK:
        endpoint = "daily"
        exchange = _stock_exchange(symbol)
    else:
        endpoint = "fund_daily"
        exchange = _etf_exchange(symbol)
    return endpoint, f"{symbol}.{exchange}"


def _stock_exchange(symbol: str) -> str:
    if symbol.startswith(("600", "601", "603", "605", "688", "689")):
        return "SH"
    if symbol.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZ"
    if symbol.startswith(("4", "8", "920")):
        return "BJ"
    raise TushareDailyBarRequestError(f"tushare_stock_exchange_unknown:{symbol}")


def _etf_exchange(symbol: str) -> str:
    if symbol.startswith("5"):
        return "SH"
    if symbol.startswith("1"):
        return "SZ"
    raise TushareDailyBarRequestError(f"tushare_etf_exchange_unknown:{symbol}")


def _rows_from_frame(
    frame: pd.DataFrame,
    *,
    instrument: InstrumentKey,
    expected_session: date,
    endpoint: str,
) -> list[ProviderDailyBarRow]:
    if frame.empty:
        return []
    required = {"trade_date", "open", "high", "low", "close", "vol", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise TushareDailyBarResponseError(
            f"tushare_response_columns_missing:{endpoint}:{','.join(sorted(missing))}"
        )

    result: list[ProviderDailyBarRow] = []
    for _, row in frame.iterrows():
        session = _trade_date(row["trade_date"])
        if session != expected_session:
            raise TushareDailyBarResponseError(
                f"tushare_response_session_mismatch:{session.isoformat()}"
            )
        volume_lots = _decimal(row["vol"], field="vol")
        amount_thousand = _decimal(row["amount"], field="amount")
        result.append(
            ProviderDailyBarRow(
                instrument=instrument,
                session_date=session,
                event_time=_daily_event_time(session),
                available_at=None,
                open_value=_decimal(row["open"], field="open"),
                high_value=_decimal(row["high"], field="high"),
                low_value=_decimal(row["low"], field="low"),
                close_value=_decimal(row["close"], field="close"),
                volume=volume_lots * _LOT_TO_SHARES,
                amount=amount_thousand * _THOUSAND_YUAN_TO_YUAN,
                suspended=False,
            )
        )
    if len(result) > 1:
        raise TushareDailyBarResponseError(
            f"tushare_response_duplicate_session:{expected_session.isoformat()}"
        )
    return result


def _trade_date(value: object) -> date:
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise TushareDailyBarResponseError("tushare_trade_date_invalid")
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise TushareDailyBarResponseError("tushare_trade_date_invalid") from exc


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise TushareDailyBarResponseError(f"tushare_response_number_invalid:{field}")
    if hasattr(value, "item") and not isinstance(value, (str, bytes, Decimal)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise TushareDailyBarResponseError(f"tushare_response_number_invalid:{field}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TushareDailyBarResponseError(
            f"tushare_response_number_invalid:{field}"
        ) from exc
    if not result.is_finite():
        raise TushareDailyBarResponseError(f"tushare_response_number_invalid:{field}")
    return result


def _serialize_dataframe(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "columns": [_json_scalar(value) for value in frame.columns],
        "index": [_json_scalar(value) for value in frame.index],
        "data": [
            [_json_scalar(value) for value in values]
            for values in frame.itertuples(index=False, name=None)
        ],
    }


def _json_scalar(value: object) -> object:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TushareDailyBarResponseError("tushare_response_json_number_invalid")
        return value
    if isinstance(value, (str, int, bool)):
        return value
    if pd.isna(value):
        return None
    return str(value)


def _session_close_utc(session: date) -> datetime:
    return datetime.combine(session, time(15), _SHANGHAI).astimezone(timezone.utc)


def _daily_event_time(session: date) -> datetime:
    return _session_close_utc(session)


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"tushare_{field}_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"tushare_{field}_must_be_timezone_aware")
    return value.astimezone(timezone.utc)
