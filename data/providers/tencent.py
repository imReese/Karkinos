"""Tencent market data via direct quotes and the AKShare Tencent history endpoint."""

from __future__ import annotations

import contextlib
import importlib
import io
import logging
import math
import re
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from core.types import AssetClass, BarFrequency, InstrumentKey, InstrumentType, Symbol
from data.market.contracts import (
    DailyBarCapability,
    DailyBarProviderUnavailableError,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)
from data.providers.akshare_sdk import provider_network_env
from data.source import DataSource, ProviderQuote

AKSHARE_TENCENT_DAILY_BAR_ADAPTER_VERSION = "karkinos.akshare_tencent.daily_bar.v1"
AKSHARE_TENCENT_DAILY_BAR_PAYLOAD_FORMAT = (
    "akshare.tencent.stock_zh_a_hist_tx.dataframe.v1"
)
AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="akshare_tencent",
    upstream_group="tencent",
    adapter_version=AKSHARE_TENCENT_DAILY_BAR_ADAPTER_VERSION,
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="stock_zh_a_hist_tx",
            instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
            price_basis="unadjusted",
        ),
    ),
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SIX_DIGIT_SYMBOL = re.compile(r"^[0-9]{6}$")
_REQUIRED_COLUMNS = (
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
)


class AkshareTencentDailyBarError(RuntimeError):
    """Base failure for the immutable Tencent daily-bar adapter."""


class AkshareTencentDailyBarUnavailableError(
    AkshareTencentDailyBarError,
    DailyBarProviderUnavailableError,
):
    """Tencent/AKShare external I/O is temporarily unavailable."""


class AkshareTencentDailyBarRequestError(AkshareTencentDailyBarError):
    """The canonical request is outside the reviewed Tencent capability."""


class AkshareTencentDailyBarResponseError(AkshareTencentDailyBarError):
    """Tencent/AKShare returned data that cannot be represented safely."""


class _AkshareTencentClient(Protocol):
    def stock_zh_a_hist_tx(
        self,
        symbol: str = "sz000001",
        start_date: str = "19000101",
        end_date: str = "20500101",
        adjust: str = "",
        timeout: float | None = None,
    ) -> pd.DataFrame: ...


class AkshareTencentDailyBarProvider:
    """Fetch raw/unadjusted SSE/SZSE stock and ETF daily bars from Tencent."""

    def __init__(
        self,
        client: _AkshareTencentClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        if not isinstance(request, DailyBarRequest):
            raise TypeError("akshare_tencent_daily_bar_request_invalid")
        if request.start_date != request.end_date:
            raise AkshareTencentDailyBarRequestError(
                "akshare_tencent_daily_bar_request_must_be_single_session"
            )

        targets = tuple(
            (instrument, _provider_symbol(instrument))
            for instrument in request.instruments
        )
        started_at = _aware_utc(self._clock(), field="started_at")
        if started_at < _session_close_utc(request.start_date):
            raise AkshareTencentDailyBarRequestError(
                "akshare_tencent_daily_bar_session_not_closed"
            )

        client = self._resolve_client()
        rows: list[ProviderDailyBarRow] = []
        calls: list[dict[str, object]] = []

        for instrument, symbol in targets:
            kwargs = {
                "symbol": symbol,
                "start_date": request.start_date.strftime("%Y%m%d"),
                "end_date": request.end_date.strftime("%Y%m%d"),
                "adjust": "",
            }
            try:
                # AKShare wraps this endpoint with tqdm.  Do not leak progress
                # bars into a long-running worker's stdout/stderr.
                with contextlib.redirect_stdout(io.StringIO()):
                    with contextlib.redirect_stderr(io.StringIO()):
                        frame = client.stock_zh_a_hist_tx(
                            symbol=kwargs["symbol"],
                            start_date=kwargs["start_date"],
                            end_date=kwargs["end_date"],
                            adjust=kwargs["adjust"],
                        )
            except Exception as exc:
                raise AkshareTencentDailyBarUnavailableError(
                    f"akshare_tencent_history_failed:{symbol}"
                ) from exc

            if not isinstance(frame, pd.DataFrame):
                raise AkshareTencentDailyBarResponseError(
                    "akshare_tencent_response_must_be_dataframe"
                )

            parsed_rows = _rows_from_frame(
                frame,
                instrument=instrument,
                expected_session=request.start_date,
            )
            rows.extend(parsed_rows)
            calls.append(
                {
                    "symbol": symbol,
                    "request": kwargs,
                    "frame": _serialize_dataframe(frame),
                }
            )

        completed_at = _aware_utc(self._clock(), field="completed_at")
        if completed_at < started_at:
            raise AkshareTencentDailyBarError(
                "akshare_tencent_provider_clock_moved_backwards"
            )

        import json

        raw_payload = json.dumps(
            {
                "schema": AKSHARE_TENCENT_DAILY_BAR_PAYLOAD_FORMAT,
                "calls": calls,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

        return ProviderDailyBarBatch(
            provider="akshare_tencent",
            adapter_version=AKSHARE_TENCENT_DAILY_BAR_ADAPTER_VERSION,
            payload_format=AKSHARE_TENCENT_DAILY_BAR_PAYLOAD_FORMAT,
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

    def _resolve_client(self) -> _AkshareTencentClient:
        if self._client is not None:
            return self._client
        try:
            module = importlib.import_module("akshare")
        except (ImportError, OSError) as exc:
            raise AkshareTencentDailyBarUnavailableError(
                "akshare_tencent_sdk_load_failed"
            ) from exc
        self._client = module
        return module


def _provider_symbol(instrument: InstrumentKey) -> str:
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise AkshareTencentDailyBarRequestError(
            "akshare_tencent_instrument_type_unsupported:"
            f"{instrument.instrument_type.value}"
        )

    symbol = instrument.symbol.strip()
    if _SIX_DIGIT_SYMBOL.fullmatch(symbol) is None:
        raise AkshareTencentDailyBarRequestError(
            f"akshare_tencent_symbol_must_be_six_digits:{symbol}"
        )

    if instrument.instrument_type is InstrumentType.STOCK:
        if symbol.startswith(("600", "601", "603", "605", "688", "689")):
            exchange = "sh"
        elif symbol.startswith(("000", "001", "002", "003", "300", "301")):
            exchange = "sz"
        elif symbol.startswith(("4", "8", "920")):
            raise AkshareTencentDailyBarRequestError(
                f"akshare_tencent_beijing_exchange_unsupported:{symbol}"
            )
        else:
            raise AkshareTencentDailyBarRequestError(
                f"akshare_tencent_stock_exchange_unknown:{symbol}"
            )
    else:
        if symbol.startswith("5"):
            exchange = "sh"
        elif symbol.startswith("1"):
            exchange = "sz"
        else:
            raise AkshareTencentDailyBarRequestError(
                f"akshare_tencent_etf_exchange_unknown:{symbol}"
            )

    return f"{exchange}{symbol}"


def _rows_from_frame(
    frame: pd.DataFrame,
    *,
    instrument: InstrumentKey,
    expected_session: date,
) -> list[ProviderDailyBarRow]:
    if frame.empty:
        return []

    missing = set(_REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise AkshareTencentDailyBarResponseError(
            "akshare_tencent_response_columns_missing:" + ",".join(sorted(missing))
        )

    result: list[ProviderDailyBarRow] = []
    for _, item in frame.iterrows():
        session = _trade_date(item["date"])
        if session != expected_session:
            raise AkshareTencentDailyBarResponseError(
                f"akshare_tencent_response_session_mismatch:{session.isoformat()}"
            )

        result.append(
            ProviderDailyBarRow(
                instrument=instrument,
                session_date=session,
                event_time=_session_close_utc(session),
                # Tencent does not expose a per-row publication timestamp.
                available_at=None,
                open_value=_decimal(item["open"], field="open"),
                high_value=_decimal(item["high"], field="high"),
                low_value=_decimal(item["low"], field="low"),
                close_value=_decimal(item["close"], field="close"),
                # AKShare normalizes Tencent's source units before returning:
                # volume -> shares, amount -> CNY.
                volume=_decimal(item["volume"], field="volume"),
                amount=_decimal(item["amount"], field="amount"),
                suspended=False,
            )
        )

    if len(result) > 1:
        raise AkshareTencentDailyBarResponseError(
            f"akshare_tencent_response_duplicate_session:{expected_session.isoformat()}"
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
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise AkshareTencentDailyBarResponseError(
            "akshare_tencent_trade_date_invalid"
        ) from exc
    if parsed.isoformat() != text:
        raise AkshareTencentDailyBarResponseError("akshare_tencent_trade_date_invalid")
    return parsed


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise AkshareTencentDailyBarResponseError(
            f"akshare_tencent_response_number_invalid:{field}"
        )
    if hasattr(value, "item") and not isinstance(value, (str, bytes, Decimal)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise AkshareTencentDailyBarResponseError(
            f"akshare_tencent_response_number_invalid:{field}"
        )
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AkshareTencentDailyBarResponseError(
            f"akshare_tencent_response_number_invalid:{field}"
        ) from exc
    if not result.is_finite():
        raise AkshareTencentDailyBarResponseError(
            f"akshare_tencent_response_number_invalid:{field}"
        )
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
            raise AkshareTencentDailyBarResponseError(
                "akshare_tencent_response_json_number_invalid"
            )
        return value
    if isinstance(value, (str, int, bool)):
        return value
    if pd.isna(value):
        return None
    return str(value)


def _session_close_utc(session: date) -> datetime:
    return datetime.combine(session, time(15), _SHANGHAI).astimezone(timezone.utc)


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"akshare_tencent_{field}_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"akshare_tencent_{field}_must_be_timezone_aware")
    result = value.astimezone(timezone.utc)
    if not math.isfinite(result.timestamp()):
        raise ValueError(f"akshare_tencent_{field}_invalid")
    return result


logger = logging.getLogger(__name__)

_CHINA_MARKET_TZ = ZoneInfo("Asia/Shanghai")

TENCENT_DAILY_BAR_ADAPTER_VERSION = "karkinos.tencent.daily_bar.v1"
TENCENT_DAILY_BAR_PAYLOAD_FORMAT = "tencent.stock_zh_a_hist_tx.dataframe.v1"
TENCENT_DAILY_BAR_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="tencent",
    upstream_group="tencent",
    adapter_version=TENCENT_DAILY_BAR_ADAPTER_VERSION,
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="stock_zh_a_hist_tx",
            instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
            price_basis="unadjusted",
        ),
    ),
)


def resolve_tencent_market_prefix(symbol: Symbol | str, asset_class: AssetClass) -> str:
    """Resolve Tencent quote prefix ('sh', 'sz', 'bj') for a given symbol."""
    sym = str(symbol).strip()
    if asset_class == AssetClass.INDEX:
        if sym.startswith(("399",)):
            return "sz"
        return "sh"

    if sym.startswith(("4", "8", "920")):
        return "bj"
    if sym.startswith(("6", "9", "5", "7")):
        return "sh"
    if sym.startswith(("0", "3", "1", "2")):
        return "sz"
    return "sh"


def fetch_tencent_realtime_quote(
    symbol: Symbol | str,
    asset_class: AssetClass = AssetClass.STOCK,
    *,
    timeout_seconds: float = 3.0,
) -> dict[str, Any] | None:
    """Fetch realtime quote directly from Tencent official quote endpoint (qt.gtimg.cn).

    High-availability, ultra-low latency (<50ms), zero authentication required.
    """
    sym = str(symbol).strip()
    if not sym:
        return None

    prefix = resolve_tencent_market_prefix(sym, asset_class)
    tencent_code = f"{prefix}{sym}"
    url = f"http://qt.gtimg.cn/q={tencent_code}"

    try:
        resp = requests.get(url, timeout=max(float(timeout_seconds), 0.1))
        resp.encoding = "gbk"
        text = resp.text.strip()
        if "~" not in text:
            return None
        parts = text.split("~")
        if len(parts) <= 32:
            return None

        price = float(parts[3])
        if price <= 0:
            return None

        name = str(parts[1]).strip() or None
        prev_close = float(parts[4]) if parts[4] else None
        lots = float(parts[6]) if parts[6] else None
        time_str = parts[30]
        if len(time_str) == 14:
            try:
                dt = datetime.strptime(time_str, "%Y%m%d%H%M%S").replace(
                    tzinfo=_CHINA_MARKET_TZ
                )
            except ValueError:
                dt = datetime.now(_CHINA_MARKET_TZ)
        else:
            dt = datetime.now(_CHINA_MARKET_TZ)

        change = float(parts[31]) if parts[31] else None
        pct = float(parts[32]) / 100.0 if parts[32] else None
        amount = (
            float(parts[57]) * 10000.0
            if len(parts) > 57 and parts[57]
            else (float(parts[37]) * 10000.0 if len(parts) > 37 and parts[37] else None)
        )

        volume = None
        if lots is not None:
            volume = lots if asset_class == AssetClass.INDEX else lots * 100.0

        quote = ProviderQuote(
            symbol=sym,
            asset_class=asset_class,
            provider_name="tencent",
            provider_symbol=tencent_code,
            price=price,
            timestamp=dt.isoformat(timespec="seconds"),
            volume=volume,
            turnover=amount,
            quote_source="tencent_realtime_quote",
            display_name=name,
            previous_close=prev_close,
            change=change,
            change_percent=pct,
        )
        return quote.to_payload()
    except Exception:
        logger.warning(
            "Tencent realtime quote fetch failed for %s (%s)",
            sym,
            asset_class.value,
            exc_info=True,
        )
        return None


class TencentDailyBarProvider(AkshareTencentDailyBarProvider):
    """Fetch raw/unadjusted SSE/SZSE stock and ETF daily bars with provider='tencent'."""

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return TENCENT_DAILY_BAR_DESCRIPTOR

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        batch = super().fetch_daily_bars(request)
        return ProviderDailyBarBatch(
            provider="tencent",
            adapter_version=TENCENT_DAILY_BAR_ADAPTER_VERSION,
            payload_format=TENCENT_DAILY_BAR_PAYLOAD_FORMAT,
            started_at=batch.started_at,
            completed_at=batch.completed_at,
            raw_payload=batch.raw_payload,
            rows=batch.rows,
        )


class TencentSource(DataSource):
    """Tencent market data adapter providing realtime quotes and daily bars."""

    def __init__(
        self,
        client: _AkshareTencentClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._daily_provider = TencentDailyBarProvider(client=client, clock=clock)

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict[str, Any] | None:
        """Fetch latest realtime quote from Tencent."""
        return fetch_tencent_realtime_quote(symbol, asset_class=asset_class)

    def supports_bars(
        self,
        asset_class: AssetClass = AssetClass.STOCK,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> bool:
        """Tencent supports Daily bars for Stock and ETF."""
        if frequency == BarFrequency.DAILY:
            return asset_class in (AssetClass.STOCK, AssetClass.FUND)
        return False

    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        """Fetch bars using Tencent hist API via AKShare client."""
        if not self.supports_bars(asset_class, frequency):
            raise NotImplementedError(
                f"TencentSource does not support {frequency} bars for {asset_class}"
            )
        import akshare as ak

        prefix = resolve_tencent_market_prefix(symbol, asset_class)
        tencent_code = f"{prefix}{str(symbol).strip()}"
        df = ak.stock_zh_a_hist_tx(
            symbol=tencent_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="",
        )
        if df is None or df.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ]
            )
        col_map = {
            "date": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
        }
        df = df.rename(columns=col_map)
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(
            _CHINA_MARKET_TZ
        )
        return df.reset_index(drop=True)

    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """TencentSource does not expose tick-level data."""
        raise NotImplementedError("TencentSource does not support tick-level data")

    def list_symbols(self) -> list[Symbol]:
        """TencentSource does not expose a local symbol directory."""
        return []


def legacy_index_daily(ak, *, symbol: str, start_date: str, end_date: str):
    """Fetch the AKShare wrapped Tencent index daily series."""
    with provider_network_env():
        return ak.stock_zh_index_daily_tx(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
