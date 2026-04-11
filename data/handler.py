"""DataHandler — K 线回放，发射 MarketEvent。"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, Symbol


class DataHandler:
    """K 线数据回放处理器。

    实现 Iterable 协议，逐根 yield MarketEvent。
    用于回测时模拟行情推送。
    """

    def __init__(
        self,
        df: pd.DataFrame,
        symbol: Symbol,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass | None = None,
    ) -> None:
        self._df = df.reset_index(drop=True)
        self._symbol = symbol
        self._frequency = frequency
        self._asset_class = asset_class
        self._index = 0

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self) -> MarketEvent:
        if self._index >= len(self._df):
            raise StopIteration

        row = self._df.iloc[self._index]
        self._index += 1

        return self._row_to_event(row)

    def _row_to_event(self, row: pd.Series) -> MarketEvent:
        """将 DataFrame 行转为 MarketEvent。"""
        ts = row.get("timestamp", row.get("日期", row.name))
        if isinstance(ts, str):
            ts = pd.Timestamp(ts).to_pydatetime()

        return MarketEvent(
            timestamp=ts,
            symbol=self._symbol,
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row["volume"])),
            frequency=self._frequency,
            asset_class=self._asset_class,
        )

    def stream(self):
        """别名：返回迭代器。"""
        return iter(self)

    @property
    def total_bars(self) -> int:
        return len(self._df)
