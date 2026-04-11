"""DataSource — 数据源抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol


class DataSource(ABC):
    """数据源抽象基类。

    定义统一接口，AKShare/Tushare 等具体适配器实现此接口。
    """

    @abstractmethod
    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        """获取 K 线数据，返回 DataFrame。

        列名约定：open, high, low, close, volume, amount, timestamp
        asset_class 决定调用哪个底层 API（股票/ETF/黄金/债券）。
        """

    @abstractmethod
    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """获取逐笔数据。"""

    @abstractmethod
    def list_symbols(self) -> list[Symbol]:
        """列出可用的标的代码。"""

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict | None:
        """获取最新行情快照（实时模式用）。

        返回统一格式: {"price": float, "volume": float|None, "timestamp": str}
        默认返回 None，子类按需覆盖。
        """
        return None
