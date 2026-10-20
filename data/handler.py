"""DataHandler — K 线回放，发射 MarketEvent。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any

import pandas as pd

from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol


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
        instrument_type: InstrumentType | None = None,
    ) -> None:
        self._df = df.reset_index(drop=True)
        self._symbol = symbol
        self._frequency = frequency
        self._asset_class = asset_class
        self._instrument_type = instrument_type
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
        return self._values_to_event(ts, row)

    def _values_to_event(
        self, ts: Any, row: pd.Series | Mapping[str, Any]
    ) -> MarketEvent:
        """Keep time and Decimal conversion identical for both row iterators."""
        if isinstance(ts, str):
            ts = pd.Timestamp(ts).to_pydatetime()

        available_at = row.get("available_at")
        if available_at is None or pd.isna(available_at):
            available_at = None
        else:
            available_at = pd.Timestamp(available_at).to_pydatetime()

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
            instrument_type=self._instrument_type,
            available_at=available_at,
        )

    def _iter_replay_events(self) -> Iterator[MarketEvent]:
        """Opt-in tuple iteration for the exact immutable Dataset frame shape."""
        columns = (
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "available_at",
            "captured_at",
        )
        if (
            type(self) is DataHandler
            and type(self._df) is pd.DataFrame
            and tuple(self._df.columns) == columns
        ):
            dtypes = self._df.dtypes
            canonical = all(dtypes[name] == object for name in columns[1:7]) and all(
                isinstance(dtypes[name], pd.DatetimeTZDtype)
                for name in ("timestamp", "available_at", "captured_at")
            )
            if canonical:
                for values in self._df.itertuples(index=False, name=None):
                    ts, opening, high, low, close, volume, _, available_at, _ = values
                    yield self._values_to_event(
                        ts,
                        {
                            "open": opening,
                            "high": high,
                            "low": low,
                            "close": close,
                            "volume": volume,
                            "available_at": available_at,
                        },
                    )
                return
        yield from self

    def stream(self):
        """别名：返回迭代器。"""
        return iter(self)

    @property
    def total_bars(self) -> int:
        return len(self._df)

    @property
    def instrument_type(self) -> InstrumentType | None:
        return self._instrument_type
