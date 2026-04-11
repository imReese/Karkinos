"""Tushare 数据适配器。"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.types import BarFrequency, Symbol
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
            ts.set_token(self._token)
        return ts.pro_api()

    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> pd.DataFrame:
        pro = self._get_pro()

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

    def list_symbols(self) -> list[Symbol]:
        pro = self._get_pro()
        df = pro.stock_basic(exchange="", list_status="L")
        return [Symbol(str(code)) for code in df["ts_code"].str[:6].tolist()]

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
