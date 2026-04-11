"""Bar — K 线数据。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.types import BarFrequency, Symbol


@dataclass(frozen=True)
class Bar:
    """K 线数据（OHLCV + symbol + frequency + timestamp）。"""

    symbol: Symbol
    timestamp: datetime
    frequency: BarFrequency
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal | None = None  # 成交额
