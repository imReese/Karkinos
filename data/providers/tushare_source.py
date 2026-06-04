"""Tushare 数据适配器。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.source import DataSource


class TushareSource(DataSource):
    """Tushare 数据源适配器。

    需要 Tushare token，通过环境变量 TUSHARE_TOKEN 或构造参数传入。
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def _get_pro(self):
        import tushare as ts

        if self._token:
            return ts.pro_api(self._token)
        return ts.pro_api()

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
                ts_code=(
                    f"{symbol}.SH" if str(symbol).startswith("6") else f"{symbol}.SZ"
                ),
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        else:
            raise NotImplementedError(
                f"Tushare does not support frequency: {frequency}"
            )

        return self._normalize_bars(df)

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
        if asset_class != AssetClass.STOCK:
            return None

        ts_code = self._stock_ts_code(symbol)
        realtime = self._fetch_realtime_quote(ts_code)
        if realtime is not None:
            return realtime
        return self._fetch_daily_latest(ts_code)

    def list_symbols(self) -> list[Symbol]:
        pro = self._get_pro()
        df = pro.stock_basic(exchange="", list_status="L")
        return [Symbol(str(code)) for code in df["ts_code"].str[:6].tolist()]

    def _fetch_realtime_quote(self, ts_code: str) -> dict | None:
        import tushare as ts

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
            "previous_close_date": trade_date,
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

    @staticmethod
    def _stock_ts_code(symbol: Symbol) -> str:
        raw = str(symbol)
        if "." in raw:
            return raw
        if raw.startswith("6"):
            return f"{raw}.SH"
        if raw.startswith(("4", "8")):
            return f"{raw}.BJ"
        return f"{raw}.SZ"

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
        return f"{trade_date}T{time_value}"

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
