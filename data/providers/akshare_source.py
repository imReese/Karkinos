"""AKShare 数据适配器。"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.types import BarFrequency, Symbol
from data.source import DataSource


class AKShareSource(DataSource):
    """AKShare 数据源适配器。

    将 AKShare 返回的 DataFrame 列名映射到统一格式。
    """

    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> pd.DataFrame:
        import akshare as ak

        if frequency == BarFrequency.DAILY:
            df = ak.stock_zh_a_hist(
                symbol=str(symbol),
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
        else:
            raise NotImplementedError(
                f"AKShare does not support frequency: {frequency}"
            )

        return self._normalize_bars(df)

    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        raise NotImplementedError("AKShare tick data not supported")

    def list_symbols(self) -> list[Symbol]:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        return [Symbol(str(code)) for code in df["代码"].tolist()]

    @staticmethod
    def _normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
        """将 AKShare 返回的列名映射到统一格式。"""
        column_map = {
            "日期": "timestamp",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=column_map)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
