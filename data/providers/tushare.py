"""TuShare immutable daily-bar adapter for the canonical market-data pipeline."""

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

TUSHARE_DAILY_BAR_ADAPTER_VERSION = "karkinos.tushare.daily_bar.v2"
TUSHARE_DAILY_BAR_PAYLOAD_FORMAT = "tushare.pro.daily_bar.dataframe.v1"
TUSHARE_MARKET_DAILY_PAYLOAD_FORMAT = "tushare.pro.market_daily.dataframe.v2"
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


class TushareDailyBarUnavailableError(
    TushareDailyBarError,
    DailyBarProviderUnavailableError,
):
    """TuShare external SDK/API I/O is temporarily unavailable."""


class TushareDailyBarRequestError(TushareDailyBarError):
    """The canonical request is outside the reviewed TuShare capability."""


class TushareDailyBarResponseError(TushareDailyBarError):
    """TuShare returned data that cannot be represented safely."""


class _TusharePro(Protocol):
    def daily(self, **kwargs: object) -> pd.DataFrame: ...

    def fund_daily(self, **kwargs: object) -> pd.DataFrame: ...


def tushare_pro_client(token: str | None) -> Any:
    """Open a TuShare Pro client without changing global token state."""
    import tushare as ts

    return ts.pro_api(token) if token else ts.pro_api()


def fetch_tushare_pro_daily_range(
    client: Any,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    return client.daily(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_tushare_pro_market_daily(client: Any, *, trade_date: str) -> pd.DataFrame:
    return client.daily(trade_date=trade_date)


def fetch_tushare_pro_stock_basic(client: Any) -> pd.DataFrame:
    # Listing status is not among every SDK response's default fields. Ask for
    # the source facts explicitly instead of inferring active status from an
    # arbitrary stock-name/quote table.
    frame = client.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
    )
    if not isinstance(frame, pd.DataFrame) or not {
        "ts_code",
        "name",
        "list_status",
        "list_date",
        "delist_date",
    }.issubset(frame.columns):
        raise TushareDailyBarResponseError("tushare_stock_master_schema_invalid")
    # The official endpoint caps one response at 6,000 rows. Reaching that
    # bound cannot establish complete active membership.
    if len(frame) >= 6000:
        raise TushareDailyBarResponseError("tushare_stock_master_truncation_possible")
    if not frame.empty and not frame["list_status"].eq("L").all():
        raise TushareDailyBarResponseError("tushare_stock_master_status_mismatch")
    return frame


def fetch_tushare_pro_fund_nav(
    client: Any,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    return client.fund_nav(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )


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
        started_at = _aware_utc(self._clock(), field="started_at")
        if started_at < _session_close_utc(request.end_date):
            raise TushareDailyBarRequestError("tushare_daily_bar_session_not_closed")

        client = self._resolve_client()
        rows: list[ProviderDailyBarRow] = []
        captures: list[dict[str, object]] = []
        market_batch = (
            request.start_date == request.end_date
            and len(request.instruments) > 1
            and all(
                key.instrument_type is InstrumentType.STOCK
                for key in request.instruments
            )
        )
        if market_batch:
            targets = {_request_target(key)[1]: key for key in request.instruments}
            trade_date = request.start_date.strftime("%Y%m%d")
            try:
                frame = fetch_tushare_pro_market_daily(client, trade_date=trade_date)
            except Exception as exc:
                raise TushareDailyBarUnavailableError(
                    "tushare_market_daily_failed"
                ) from exc
            if not isinstance(frame, pd.DataFrame):
                raise TushareDailyBarResponseError(
                    "tushare_response_must_be_dataframe:daily"
                )
            if not frame.empty:
                if "ts_code" not in frame.columns:
                    raise TushareDailyBarResponseError(
                        "tushare_response_columns_missing:daily:ts_code"
                    )
                selected = frame.loc[frame["ts_code"].isin(targets)]
                for ts_code, group in selected.groupby("ts_code", sort=False):
                    rows.extend(
                        _rows_from_frame(
                            group,
                            instrument=targets[str(ts_code)],
                            expected_session=request.start_date,
                            endpoint="daily",
                        )
                    )
            captures.append(
                {
                    "endpoint": "daily",
                    "request": {"trade_date": trade_date},
                    "frame": _serialize_dataframe(frame),
                }
            )
        for instrument in () if market_batch else request.instruments:
            endpoint, ts_code = _request_target(instrument)
            method = getattr(client, endpoint)
            try:
                frame = method(
                    ts_code=ts_code,
                    start_date=request.start_date.strftime("%Y%m%d"),
                    end_date=request.end_date.strftime("%Y%m%d"),
                )
            except Exception as exc:
                raise TushareDailyBarUnavailableError(
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
                expected_end=request.end_date,
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

        payload_format = (
            TUSHARE_MARKET_DAILY_PAYLOAD_FORMAT
            if market_batch
            else TUSHARE_DAILY_BAR_PAYLOAD_FORMAT
        )
        payload = json.dumps(
            {
                "schema": payload_format,
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
            payload_format=payload_format,
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
            raise TushareDailyBarUnavailableError("tushare_sdk_load_failed") from exc
        try:
            return module.pro_api(self._token) if self._token else module.pro_api()
        except Exception as exc:
            raise TushareDailyBarUnavailableError(
                "tushare_client_initialization_failed"
            ) from exc


def normalize_tushare_daily_units(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert a renamed daily frame using the same units as the typed adapter."""
    result = frame.copy()
    for column, factor in (
        ("volume", _LOT_TO_SHARES),
        ("amount", _THOUSAND_YUAN_TO_YUAN),
    ):
        if column in result:
            result[column] = result[column].map(
                lambda value: float(_decimal(value, field=column) * factor)
            )
    result.attrs.update(volume_unit="shares", amount_unit="CNY", adjustment_mode="none")
    return result


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
    if symbol.startswith(("000", "001", "002", "003", "300", "301", "302")):
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
    expected_end: date | None = None,
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
        if not expected_session <= session <= (expected_end or expected_session):
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
    if len({row.session_date for row in result}) != len(result):
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


import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import timedelta

from core.types import AssetClass, BarFrequency, Symbol
from data.providers.eastmoney import fetch_eastmoney_realtime_quote_via_tushare
from data.source import DataSource, normalize_provider_quote

logger = logging.getLogger(__name__)

_DEFAULT_REALTIME_TIMEOUT_SECONDS = 2.0
_CHINA_MARKET_TZ = ZoneInfo("Asia/Shanghai")

TUSHARE_PROVIDER_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="tushare",
    upstream_group="tushare",
    adapter_version="karkinos.tushare.source.v2",
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="daily",
            instrument_types=(InstrumentType.STOCK,),
            price_basis="unadjusted",
        ),
    ),
)


def _clean_stock_master_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized or None


class TushareSource(DataSource):
    """TuShare Pro data with legacy Eastmoney realtime quote dispatch.

    TuShare Pro requests use the token supplied by configuration or the caller.
    """

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return TUSHARE_PROVIDER_DESCRIPTOR

    def __init__(
        self,
        token: str | None = None,
        realtime_timeout_seconds: float = _DEFAULT_REALTIME_TIMEOUT_SECONDS,
    ) -> None:
        self._token = token
        self._realtime_timeout_seconds = max(float(realtime_timeout_seconds), 0.001)

    def _get_pro(self):
        return tushare_pro_client(self._token)

    def supports_bars(
        self,
        asset_class: AssetClass = AssetClass.STOCK,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> bool:
        return asset_class == AssetClass.STOCK and frequency == BarFrequency.DAILY

    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        pro = self._get_pro()

        if asset_class != AssetClass.STOCK:
            raise NotImplementedError(
                f"Tushare adapter only supports STOCK, got: {asset_class}"
            )

        if frequency == BarFrequency.DAILY:
            df = fetch_tushare_pro_daily_range(
                pro,
                ts_code=self._stock_ts_code(symbol),
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        else:
            raise NotImplementedError(
                f"Tushare does not support frequency: {frequency}"
            )

        return self._normalize_bars(df)

    def fetch_market_daily_bars(self, trade_date: str) -> pd.DataFrame:
        """Fetch one complete TuShare daily cross-section for local freezing."""

        try:
            normalized_date = datetime.strptime(str(trade_date), "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise ValueError("tushare_market_daily_trade_date_invalid") from exc
        frame = fetch_tushare_pro_market_daily(
            self._get_pro(), trade_date=normalized_date.strftime("%Y%m%d")
        )
        if frame is None or frame.empty or "ts_code" not in frame.columns:
            raise ValueError("tushare_market_daily_result_empty")
        normalized = self._normalize_bars(frame)
        normalized["symbol"] = frame["ts_code"].astype(str).str[:6].to_numpy()
        return normalized

    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        raise NotImplementedError("Tushare tick data not supported in this adapter")

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict | None:
        """Fetch the latest A-share quote through the legacy TuShare source.

        Eastmoney realtime quotes via the TuShare SDK are preferred for current
        prices. When unavailable, fall back to the latest TuShare Pro daily bar.
        """
        if asset_class == AssetClass.STOCK:
            ts_code = self._stock_ts_code(symbol)
            realtime = self._fetch_realtime_quote_with_timeout(ts_code)
            if realtime is not None:
                return self._normalize_latest_quote(
                    symbol, asset_class, realtime, ts_code
                )
            return self._normalize_latest_quote(
                symbol, asset_class, self._fetch_daily_latest(ts_code), ts_code
            )

        if asset_class == AssetClass.FUND:
            return self.fetch_confirmed_fund_nav(symbol)

        return None

    def fetch_confirmed_fund_nav(self, symbol: Symbol) -> dict | None:
        """Fetch the latest published open-end fund NAV, never an estimate."""

        ts_code = self._fund_ts_code(symbol)
        return self._normalize_latest_quote(
            symbol,
            AssetClass.FUND,
            self._fetch_fund_nav_latest(ts_code),
            ts_code,
        )

    def list_symbols(self) -> list[Symbol]:
        return [
            Symbol(str(item["symbol"])) for item in self.list_symbol_metadata() or []
        ]

    def list_symbol_metadata(self) -> list[dict[str, object]]:
        """Return codes and names from the same TuShare stock-master response."""
        pro = self._get_pro()
        df = fetch_tushare_pro_stock_basic(pro)
        rows: list[dict[str, object]] = []
        for _, row in df.iterrows():
            provider_symbol = _clean_stock_master_text(row.get("ts_code"))
            if not provider_symbol:
                continue
            symbol = provider_symbol.split(".", maxsplit=1)[0]
            exchange = _clean_stock_master_text(row.get("exchange"))
            if not exchange and "." in provider_symbol:
                exchange = {
                    "SH": "SSE",
                    "SZ": "SZSE",
                    "BJ": "BSE",
                }.get(provider_symbol.rsplit(".", maxsplit=1)[-1].upper())
            rows.append(
                {
                    "symbol": symbol,
                    "asset_class": AssetClass.STOCK.value,
                    "display_name": _clean_stock_master_text(row.get("name")),
                    "list_date": _clean_stock_master_text(row.get("list_date")),
                    "list_status": _clean_stock_master_text(row.get("list_status")),
                    "delist_date": _clean_stock_master_text(row.get("delist_date")),
                    "provider_symbol": provider_symbol,
                    "exchange": exchange,
                    "provider_name": "tushare",
                    "market": "cn",
                    "source": "stock_master",
                }
            )
        return rows

    def _fetch_realtime_quote_with_timeout(self, ts_code: str) -> dict | None:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tushare-rtq")
        future = executor.submit(self._fetch_realtime_quote, ts_code)
        try:
            return future.result(timeout=self._realtime_timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            logger.warning(
                "TuShare realtime quote timed out for %s after %.3fs; falling back to daily",
                ts_code,
                self._realtime_timeout_seconds,
            )
            return None
        except Exception:
            logger.warning(
                "TuShare realtime quote failed for %s; falling back to daily",
                ts_code,
                exc_info=True,
            )
            return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _normalize_latest_quote(
        symbol: Symbol,
        asset_class: AssetClass,
        payload: dict | None,
        provider_symbol: str,
    ) -> dict | None:
        quote = normalize_provider_quote(
            symbol,
            asset_class,
            payload,
            provider_name="tushare",
            provider_symbol=provider_symbol,
        )
        return None if quote is None else quote.to_payload()

    def _fetch_realtime_quote(self, ts_code: str) -> dict | None:
        return fetch_eastmoney_realtime_quote_via_tushare(ts_code)

    def _fetch_daily_latest(self, ts_code: str) -> dict | None:
        pro = self._get_pro()
        end = datetime.now()
        start = end - timedelta(days=14)
        df = fetch_tushare_pro_daily_range(
            pro,
            ts_code=ts_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return None
        df = df.sort_values("trade_date", ascending=False)
        row = df.iloc[0].to_dict()
        trade_date = self._format_trade_date(self._row_value(row, "trade_date"))
        return {
            "price": self._row_float(row, "close"),
            "volume": self._row_float(row, "vol", "volume"),
            "turnover": self._row_float(row, "amount"),
            "timestamp": trade_date,
            "source": "tushare",
            "quote_source": "tushare_daily",
            "previous_close": self._row_float(row, "pre_close"),
            "change": self._row_float(row, "change"),
            "change_percent": self._optional_percent(
                self._row_float(row, "pct_chg", "pct_change")
            ),
            "previous_close_date": trade_date,
        }

    def _fetch_fund_nav_latest(self, ts_code: str) -> dict | None:
        if getattr(self, "_fund_nav_forbidden", False):
            return None
        pro = self._get_pro()
        end = datetime.now()
        start = end - timedelta(days=30)
        try:
            df = fetch_tushare_pro_fund_nav(
                pro,
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as exc:
            if "没有接口(fund_nav)访问权限" in str(exc):
                self._fund_nav_forbidden = True
                logger.info(
                    "TuShare 账号缺少 fund_nav 接口权限（需 2000+ 积分），已停用 TuShare 基金接口并由备用源处理"
                )
            else:
                logger.warning("TuShare pro fund_nav failed for %s: %s", ts_code, exc)
            return None
        if df is None or df.empty:
            return None
        df = df.sort_values("nav_date", ascending=False)
        latest = df.iloc[0].to_dict()
        previous = df.iloc[1].to_dict() if len(df) > 1 else {}
        price = self._row_float(latest, "unit_nav", "nav")
        nav_date = self._format_trade_date(self._row_value(latest, "nav_date"))
        try:
            published_date = datetime.strptime(str(nav_date), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None
        if price is None or not math.isfinite(price) or price <= 0:
            return None

        previous_close = self._row_float(previous, "unit_nav", "nav")
        previous_close_date = self._format_trade_date(
            self._row_value(previous, "nav_date")
        )
        day_change_value = (
            price - previous_close if previous_close not in {None, 0} else None
        )
        day_change_pct = (
            day_change_value / previous_close
            if day_change_value is not None and previous_close not in {None, 0}
            else None
        )
        return {
            "price": price,
            "volume": None,
            "turnover": None,
            "timestamp": datetime(
                published_date.year,
                published_date.month,
                published_date.day,
                15,
                tzinfo=_CHINA_MARKET_TZ,
            ).isoformat(),
            "source": "tushare",
            "quote_source": "tushare_fund_nav",
            "nav_date": published_date.isoformat(),
            "previous_close": previous_close,
            "previous_close_date": previous_close_date,
            "day_change_value": day_change_value,
            "day_change_pct": day_change_pct,
        }

    @staticmethod
    def _stock_ts_code(symbol: Symbol) -> str:
        raw = str(symbol)
        if "." in raw:
            return raw
        if raw.startswith("6"):
            return f"{raw}.SH"
        if raw.startswith(("4", "8", "92")):
            return f"{raw}.BJ"
        return f"{raw}.SZ"

    @staticmethod
    def _fund_ts_code(symbol: Symbol) -> str:
        raw = str(symbol)
        if "." in raw:
            return raw
        return f"{raw}.OF"

    @staticmethod
    def _row_value(row: dict[str, Any], *names: str) -> Any:
        for name in names:
            if name in row and pd.notna(row[name]):
                return row[name]
        return None

    @classmethod
    def _row_float(cls, row: dict[str, Any], *names: str) -> float | None:
        value = cls._row_value(row, *names)
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_percent(value: float | None) -> float | None:
        if value is None:
            return None
        return value / 100

    @staticmethod
    def _format_trade_date(value: Any) -> str | None:
        if value in {None, ""}:
            return None
        raw = str(value)
        if len(raw) == 8 and raw.isdigit():
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        return raw

    @staticmethod
    def _normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
        """将 Tushare 返回的列名映射到统一格式。"""
        column_map = {
            "trade_date": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
            "amount": "amount",
        }
        df = df.rename(columns=column_map)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        # daily reports lots and thousand CNY; all consumers use shares and CNY.
        df = normalize_tushare_daily_units(df)
        return df
