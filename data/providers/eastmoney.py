"""Eastmoney data through AKShare daily/fund endpoints and TuShare DC quotes."""

from __future__ import annotations

import importlib
import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
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
from data.providers.akshare_sdk import provider_network_env

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


def legacy_daily_bars(
    ak,
    retry,
    *,
    endpoint: str,
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str | None = None,
):
    """Fetch the legacy Eastmoney stock, ETF, or index history endpoint."""
    if endpoint not in {"stock_zh_a_hist", "fund_etf_hist_em", "index_zh_a_hist"}:
        raise ValueError(f"eastmoney_legacy_daily_endpoint_unsupported:{endpoint}")
    kwargs = {
        "symbol": symbol,
        "period": "daily",
        "start_date": start_date,
        "end_date": end_date,
    }
    if adjust is not None:
        kwargs["adjust"] = adjust
    return retry(getattr(ak, endpoint), **kwargs)


def legacy_minute_bars(ak, retry, *, asset_class: str, symbol: str, period: str):
    """Fetch legacy Eastmoney stock or ETF minute history."""
    if asset_class == "stock":
        endpoint = ak.stock_zh_a_hist_min_em
    elif asset_class == "fund":
        endpoint = ak.fund_etf_hist_min_em
    else:
        raise ValueError(f"eastmoney_legacy_minute_asset_unsupported:{asset_class}")
    return retry(endpoint, symbol=symbol, period=period)


def legacy_stock_master(ak):
    with provider_network_env():
        return ak.stock_zh_a_spot_em()


def legacy_stock_bid_ask(ak, retry, *, symbol: str):
    return retry(ak.stock_bid_ask_em, symbol=symbol, retry_delay_seconds=0)


def legacy_etf_spot(ak, retry):
    return retry(ak.fund_etf_spot_em)


def legacy_index_spot(ak, *, symbol: str):
    with provider_network_env():
        return ak.stock_zh_index_spot_em(symbol=symbol)


def legacy_fund_name_map(ak):
    with provider_network_env():
        return ak.fund_name_em()


def legacy_open_end_fund_info(ak, retry, *, symbol: str):
    return retry(ak.fund_open_fund_info_em, symbol=symbol, indicator="单位净值走势")


def legacy_open_end_fund_daily(ak, retry):
    return retry(ak.fund_open_fund_daily_em)


def legacy_fund_page(*, fund_code: str) -> str:
    import requests

    url = f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
    with provider_network_env():
        response = requests.get(url, timeout=3)
    response.raise_for_status()
    return response.text


def fetch_eastmoney_realtime_quote_via_tushare(ts_code: str) -> dict | None:
    """Fetch the Eastmoney ``dc`` feed, preserving legacy quote payload fields."""
    import tushare as ts

    df = None
    try:
        from tushare.stock import rtq

        df = rtq.get_realtime_quotes_dc(ts_code)
    except Exception:
        realtime_quote = getattr(ts, "realtime_quote", None)
        if not callable(realtime_quote):
            return None
        try:
            df = realtime_quote(ts_code=ts_code, src="dc")
        except Exception:
            return None
    if df is None or df.empty:
        return None

    row = df.iloc[0].to_dict()
    price = _row_float(row, "PRICE", "price")
    if price is None or price <= 0:
        return None

    previous_close = _row_float(row, "PRE_CLOSE", "pre_close")
    change = _row_float(row, "CHANGE", "change")
    if change is None and previous_close not in {None, 0}:
        change = price - float(previous_close)
    change_percent = _row_float(row, "PCT_CHG", "pct_chg")
    if change_percent is None and previous_close not in {None, 0}:
        change_percent = (price - float(previous_close)) / float(previous_close)
    elif change_percent is not None:
        change_percent = change_percent / 100

    trade_date = _format_trade_date(_row_value(row, "DATE", "date"))
    timestamp = _format_quote_timestamp(trade_date, _row_value(row, "TIME", "time"))
    # DATE identifies this quote's session, not the session owning PRE_CLOSE.
    # Keep the legacy provider and quote-source identity for persisted readers.
    return {
        "price": price,
        "volume": _row_float(row, "VOLUME", "volume", "VOL", "vol"),
        "turnover": _row_float(row, "AMOUNT", "amount"),
        "timestamp": timestamp or trade_date,
        "source": "tushare",
        "quote_source": "tushare_realtime_quote",
        "metadata": {
            "upstream_group": "eastmoney",
            "transport_sdk": "tushare",
        },
        "display_name": _row_str(row, "NAME", "name"),
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
    }


def _row_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            return row[name]
    return None


def _row_float(row: dict[str, Any], *names: str) -> float | None:
    value = _row_value(row, *names)
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_str(row: dict[str, Any], *names: str) -> str | None:
    value = _row_value(row, *names)
    if value in {None, ""}:
        return None
    return str(value)


def _format_trade_date(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    raw = str(value)
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _format_quote_timestamp(trade_date: str | None, time_value: Any) -> str | None:
    if not trade_date:
        return None
    if time_value in {None, ""}:
        return trade_date
    formatted_time = str(time_value).strip()
    if not formatted_time:
        return trade_date
    return f"{trade_date}T{formatted_time}"
