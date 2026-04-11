"""DataSource — 数据源抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from core.types import BarFrequency, Symbol


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
    ) -> pd.DataFrame:
        """获取 K 线数据，返回 DataFrame。

        列名约定：open, high, low, close, volume, amount, timestamp
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
