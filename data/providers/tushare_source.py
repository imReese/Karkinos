"""Tushare 数据适配器。"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.source import DataSource, normalize_provider_quote

logger = logging.getLogger(__name__)

_DEFAULT_REALTIME_TIMEOUT_SECONDS = 2.0
_CHINA_MARKET_TZ = ZoneInfo("Asia/Shanghai")


def _clean_stock_master_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized or None


class TushareSource(DataSource):
    """Tushare 数据源适配器。

    需要 Tushare token，通过环境变量 TUSHARE_TOKEN 或构造参数传入。
    """

    def __init__(
        self,
        token: str | None = None,
        realtime_timeout_seconds: float = _DEFAULT_REALTIME_TIMEOUT_SECONDS,
    ) -> None:
        self._token = token
        self._realtime_timeout_seconds = max(float(realtime_timeout_seconds), 0.001)

    def _get_pro(self):
        import tushare as ts

        if self._token:
            return ts.pro_api(self._token)
        return ts.pro_api()

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
            df = pro.daily(
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
        frame = self._get_pro().daily(trade_date=normalized_date.strftime("%Y%m%d"))
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
        """Fetch the latest A-share quote from TuShare.

        TuShare's realtime quote endpoint is preferred for current prices. When
        it returns no row, fall back to the latest daily bar so non-trading
        periods still materialize an authoritative local snapshot.
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
        df = pro.stock_basic(exchange="", list_status="L")
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
        price = self._row_float(row, "PRICE", "price")
        if price is None or price <= 0:
            return None

        previous_close = self._row_float(row, "PRE_CLOSE", "pre_close")
        change = self._row_float(row, "CHANGE", "change")
        if change is None and previous_close not in {None, 0}:
            change = price - float(previous_close)
        change_percent = self._row_float(row, "PCT_CHG", "pct_chg")
        if change_percent is None and previous_close not in {None, 0}:
            change_percent = (price - float(previous_close)) / float(previous_close)
        elif change_percent is not None:
            change_percent = change_percent / 100

        trade_date = self._format_trade_date(self._row_value(row, "DATE", "date"))
        timestamp = self._format_quote_timestamp(
            trade_date, self._row_value(row, "TIME", "time")
        )
        # DATE identifies the current quote session, not the session that owns
        # PRE_CLOSE.  Leave that date unclaimed until calendar-backed evidence
        # is available so ingestion cannot persist yesterday's close as today.
        return {
            "price": price,
            "volume": self._row_float(row, "VOLUME", "volume", "VOL", "vol"),
            "turnover": self._row_float(row, "AMOUNT", "amount"),
            "timestamp": timestamp or trade_date,
            "source": "tushare",
            "quote_source": "tushare_realtime_quote",
            "display_name": self._row_str(row, "NAME", "name"),
            "previous_close": previous_close,
            "change": change,
            "change_percent": change_percent,
        }

    def _fetch_daily_latest(self, ts_code: str) -> dict | None:
        pro = self._get_pro()
        end = datetime.now()
        start = end - timedelta(days=14)
        df = pro.daily(
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
        pro = self._get_pro()
        end = datetime.now()
        start = end - timedelta(days=30)
        df = pro.fund_nav(
            ts_code=ts_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
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

    @classmethod
    def _row_str(cls, row: dict[str, Any], *names: str) -> str | None:
        value = cls._row_value(row, *names)
        if value in {None, ""}:
            return None
        return str(value)

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
    def _format_quote_timestamp(trade_date: str | None, time_value: Any) -> str | None:
        if not trade_date:
            return None
        if time_value in {None, ""}:
            return trade_date
        formatted_time = str(time_value).strip()
        if not formatted_time:
            return trade_date
        return f"{trade_date}T{formatted_time}"

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
        return df
