"""Order — 委托单，关联 OrderEvent 扩展状态跟踪。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from core.types import OrderSide, OrderStatus, OrderType, Symbol


@dataclass
class Order:
    """委托单。

    关联 OrderEvent，扩展状态跟踪（从 PENDING 到 FILLED/REJECTED）。
    """

    order_id: str
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def is_fully_filled(self) -> bool:
        return self.filled_quantity >= self.quantity
