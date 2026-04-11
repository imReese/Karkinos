"""Slippage — 滑点模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from core.types import OrderSide


class SlippageModel(ABC):
    """滑点模型抽象基类。"""

    @abstractmethod
    def apply(self, price: Decimal, side: OrderSide, quantity: Decimal) -> Decimal:
        """应用滑点，返回滑点后的价格。"""


class FixedSlippage(SlippageModel):
    """固定滑点。"""

    def __init__(self, amount: Decimal) -> None:
        self.amount = amount

    def apply(self, price: Decimal, side: OrderSide, quantity: Decimal) -> Decimal:
        if side == OrderSide.BUY:
            return price + self.amount
        else:
            return price - self.amount


class PercentSlippage(SlippageModel):
    """百分比滑点。"""

    def __init__(self, pct: Decimal) -> None:
        self.pct = pct

    def apply(self, price: Decimal, side: OrderSide, quantity: Decimal) -> Decimal:
        slip = price * self.pct
        if side == OrderSide.BUY:
            return price + slip
        else:
            return price - slip


class VolumeSlippage(SlippageModel):
    """成交量滑点模型。

    成交量越大滑点越小（流动性越好）。
    """

    def __init__(self, base_slip: Decimal = Decimal("0.001")) -> None:
        self.base_slip = base_slip

    def apply(self, price: Decimal, side: OrderSide, quantity: Decimal) -> Decimal:
        # 简化模型：基础滑点与成交量成反比
        slip = price * self.base_slip
        if side == OrderSide.BUY:
            return price + slip
        else:
            return price - slip
