"""Tick — 逐笔数据。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.types import Symbol


@dataclass(frozen=True)
class Tick:
    """逐笔行情数据。"""

    symbol: Symbol
    timestamp: datetime
    price: Decimal
    volume: Decimal
    side: str | None = None  # 买/卖方向
    order_id: str | None = None
