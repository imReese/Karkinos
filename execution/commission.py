"""Commission — 佣金模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from core.types import OrderSide, ZERO
from core.types import (
    DEFAULT_STOCK_COMMISSION_RATE,
    MIN_STOCK_COMMISSION,
    STAMP_TAX_RATE,
    TRANSFER_FEE_RATE,
    DEFAULT_ETF_COMMISSION_RATE,
    MIN_ETF_COMMISSION,
    GOLD_SPOT_COMMISSION_RATE,
    BOND_COMMISSION_RATE,
    MIN_BOND_COMMISSION,
)


class CommissionCalculator(ABC):
    """佣金计算抽象基类。"""

    @abstractmethod
    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        """计算佣金。"""


class StockACommission(CommissionCalculator):
    """A 股佣金模型。

    佣金 = max(金额 × 佣金率, 5) + 印花税(卖0.05%) + 过户费(0.001%)
    """

    def __init__(
        self,
        commission_rate: Decimal = DEFAULT_STOCK_COMMISSION_RATE,
        min_commission: Decimal = MIN_STOCK_COMMISSION,
    ) -> None:
        self.commission_rate = commission_rate
        self.min_commission = min_commission

    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        amount = price * quantity
        # 券商佣金
        commission = max(amount * self.commission_rate, self.min_commission)
        # 印花税（仅卖出）
        stamp_tax = ZERO
        if side == OrderSide.SELL:
            stamp_tax = amount * STAMP_TAX_RATE
        # 过户费
        transfer_fee = amount * TRANSFER_FEE_RATE
        return commission + stamp_tax + transfer_fee


class ETFCommission(CommissionCalculator):
    """ETF 佣金模型。

    佣金 = max(金额 × 佣金率, 5)
    无印花税，有过户费。
    """

    def __init__(
        self,
        commission_rate: Decimal = DEFAULT_ETF_COMMISSION_RATE,
        min_commission: Decimal = MIN_ETF_COMMISSION,
    ) -> None:
        self.commission_rate = commission_rate
        self.min_commission = min_commission

    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        amount = price * quantity
        commission = max(amount * self.commission_rate, self.min_commission)
        # ETF 无印花税，有过户费
        transfer_fee = amount * TRANSFER_FEE_RATE
        return commission + transfer_fee


class GoldSpotCommission(CommissionCalculator):
    """黄金现货佣金模型。

    佣金 ≈ 金额 × 0.08%
    """

    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        amount = price * quantity
        return amount * GOLD_SPOT_COMMISSION_RATE


class BondExchangeCommission(CommissionCalculator):
    """交易所债券佣金模型。

    佣金 = max(金额 × 万0.4, 1元)
    """

    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        amount = price * quantity
        return max(amount * BOND_COMMISSION_RATE, MIN_BOND_COMMISSION)
