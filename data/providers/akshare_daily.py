"""AKShare immutable daily-bar adapter for the canonical market-data pipeline."""

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
    DailyBarProviderUnavailableError,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)

AKSHARE_DAILY_BAR_ADAPTER_VERSION = "karkinos.akshare.daily_bar.v1"
AKSHARE_DAILY_BAR_PAYLOAD_FORMAT = "akshare.eastmoney.daily_bar.dataframe.v1"
AKSHARE_DAILY_BAR_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="akshare",
    upstream_group="eastmoney",
    adapter_version=AKSHARE_DAILY_BAR_ADAPTER_VERSION,
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="stock_zh_a_hist",
            instrument_types=(InstrumentType.STOCK,),
            price_basis="unadjusted",
        ),
        DailyBarCapability(
            endpoint="fund_etf_hist_em",
            instrument_types=(InstrumentType.ETF,),
            price_basis="unadjusted",
        ),
    ),
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SIX_DIGIT_SYMBOL = re.compile(r"^[0-9]{6}$")
_LOT_TO_SHARES = Decimal("100")


class AkshareDailyBarError(RuntimeError):
    """Base failure for the immutable AKShare daily-bar adapter."""


class AkshareDailyBarUnavailableError(
    AkshareDailyBarError,
    DailyBarProviderUnavailableError,
):
    """AKShare/Eastmoney external I/O is temporarily unavailable."""


class AkshareDailyBarRequestError(AkshareDailyBarError):
    """The canonical request is outside the reviewed AKShare capability."""


class AkshareDailyBarResponseError(AkshareDailyBarError):
    """AKShare returned data that cannot be represented safely."""


class _AkshareClient(Protocol):
    def stock_zh_a_hist(self, **kwargs: object) -> pd.DataFrame: ...

    def fund_etf_hist_em(self, **kwargs: object) -> pd.DataFrame: ...


class AkshareDailyBarProvider:
    """Fetch raw/unadjusted stock and ETF daily bars from Eastmoney via AKShare."""

    def __init__(
        self,
        client: _AkshareClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return AKSHARE_DAILY_BAR_DESCRIPTOR

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        if not isinstance(request, DailyBarRequest):
            raise TypeError("akshare_daily_bar_request_invalid")
        if request.start_date != request.end_date:
            raise AkshareDailyBarRequestError(
                "akshare_daily_bar_request_must_be_single_session"
            )

        started_at = _aware_utc(self._clock(), field="started_at")
        if started_at < _session_close_utc(request.start_date):
            raise AkshareDailyBarRequestError("akshare_daily_bar_session_not_closed")

        client = self._resolve_client()
        rows: list[ProviderDailyBarRow] = []
        captures: list[dict[str, object]] = []
        for instrument in request.instruments:
            endpoint = _endpoint_for(instrument)
            method = getattr(client, endpoint)
            kwargs = {
                "symbol": instrument.symbol,
                "period": "daily",
                "start_date": request.start_date.strftime("%Y%m%d"),
                "end_date": request.end_date.strftime("%Y%m%d"),
                "adjust": "",
            }
            try:
                frame = method(**kwargs)
            except Exception as exc:
                raise AkshareDailyBarUnavailableError(
                    f"akshare_{endpoint}_failed:{instrument.symbol}"
                ) from exc
            if not isinstance(frame, pd.DataFrame):
                raise AkshareDailyBarResponseError(
                    f"akshare_response_must_be_dataframe:{endpoint}"
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
                    "symbol": instrument.symbol,
                    "request": kwargs,
                    "frame": _serialize_dataframe(frame),
                }
            )
            rows.extend(parsed_rows)

        completed_at = _aware_utc(self._clock(), field="completed_at")
        if completed_at < started_at:
            raise AkshareDailyBarError("akshare_provider_clock_moved_backwards")

        payload = json.dumps(
            {
                "schema": AKSHARE_DAILY_BAR_PAYLOAD_FORMAT,
                "calls": captures,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return ProviderDailyBarBatch(
            provider="akshare",
            adapter_version=AKSHARE_DAILY_BAR_ADAPTER_VERSION,
            payload_format=AKSHARE_DAILY_BAR_PAYLOAD_FORMAT,
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

    def _resolve_client(self) -> _AkshareClient:
        if self._client is not None:
            return self._client
        try:
            return importlib.import_module("akshare")
        except (ImportError, OSError) as exc:
            raise AkshareDailyBarUnavailableError("akshare_sdk_load_failed") from exc


def _endpoint_for(instrument: InstrumentKey) -> str:
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise AkshareDailyBarRequestError(
            f"akshare_instrument_type_unsupported:{instrument.instrument_type.value}"
        )
    symbol = instrument.symbol.strip()
    if _SIX_DIGIT_SYMBOL.fullmatch(symbol) is None:
        raise AkshareDailyBarRequestError(f"akshare_symbol_must_be_six_digits:{symbol}")
    return (
        "stock_zh_a_hist"
        if instrument.instrument_type is InstrumentType.STOCK
        else "fund_etf_hist_em"
    )


def normalize_akshare_stock_daily_units(frame: pd.DataFrame) -> pd.DataFrame:
    """Eastmoney stock daily volume is lots; amount is already CNY."""
    result = frame.copy()
    if not result.empty:
        result["volume"] = result["volume"].map(
            lambda value: float(_decimal(value, field="成交量") * _LOT_TO_SHARES)
        )
    result.attrs.update(volume_unit="shares", amount_unit="CNY", adjustment_mode="none")
    return result


def _rows_from_frame(
    frame: pd.DataFrame,
    *,
    instrument: InstrumentKey,
    expected_session: date,
    endpoint: str,
) -> list[ProviderDailyBarRow]:
    if frame.empty:
        return []
    required = {"日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"}
    missing = required - set(frame.columns)
    if missing:
        raise AkshareDailyBarResponseError(
            f"akshare_response_columns_missing:{endpoint}:{','.join(sorted(missing))}"
        )

    result: list[ProviderDailyBarRow] = []
    for _, row in frame.iterrows():
        session = _trade_date(row["日期"])
        if session != expected_session:
            raise AkshareDailyBarResponseError(
                f"akshare_response_session_mismatch:{session.isoformat()}"
            )
        volume_lots = _decimal(row["成交量"], field="成交量")
        result.append(
            ProviderDailyBarRow(
                instrument=instrument,
                session_date=session,
                event_time=_daily_event_time(session),
                available_at=None,
                open_value=_decimal(row["开盘"], field="开盘"),
                high_value=_decimal(row["最高"], field="最高"),
                low_value=_decimal(row["最低"], field="最低"),
                close_value=_decimal(row["收盘"], field="收盘"),
                volume=volume_lots * _LOT_TO_SHARES,
                amount=_decimal(row["成交额"], field="成交额"),
                suspended=False,
            )
        )
    if len(result) > 1:
        raise AkshareDailyBarResponseError(
            f"akshare_response_duplicate_session:{expected_session.isoformat()}"
        )
    return result


def _trade_date(value: object) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise AkshareDailyBarResponseError("akshare_trade_date_invalid") from exc


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise AkshareDailyBarResponseError(f"akshare_response_number_invalid:{field}")
    if hasattr(value, "item") and not isinstance(value, (str, bytes, Decimal)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise AkshareDailyBarResponseError(f"akshare_response_number_invalid:{field}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise AkshareDailyBarResponseError(
            f"akshare_response_number_invalid:{field}"
        ) from exc
    if not result.is_finite():
        raise AkshareDailyBarResponseError(f"akshare_response_number_invalid:{field}")
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
            raise AkshareDailyBarResponseError("akshare_response_json_number_invalid")
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
        raise TypeError(f"akshare_{field}_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"akshare_{field}_must_be_timezone_aware")
    return value.astimezone(timezone.utc)
