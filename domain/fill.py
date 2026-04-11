"""Fill — 成交记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.types import OrderSide, Symbol


@dataclass(frozen=True)
class Fill:
    """成交记录。"""

    fill_id: str
    order_id: str
    symbol: Symbol
    side: OrderSide
    fill_price: Decimal
    fill_quantity: Decimal
    commission: Decimal
    slippage: Decimal
    timestamp: datetime
