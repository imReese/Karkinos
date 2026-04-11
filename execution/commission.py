"""Commission — 佣金模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from core.types import (
    BOND_COMMISSION_RATE,
    DEFAULT_ETF_COMMISSION_RATE,
    DEFAULT_STOCK_COMMISSION_RATE,
    GOLD_SPOT_COMMISSION_RATE,
    MIN_BOND_COMMISSION,
    MIN_ETF_COMMISSION,
    MIN_STOCK_COMMISSION,
    STAMP_TAX_RATE,
    TRANSFER_FEE_RATE,
    ZERO,
    CommissionType,
    OrderSide,
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


class MultiAssetCommission(CommissionCalculator):
    """多资产佣金调度器。

    根据 CommissionType 路由到对应的佣金模型。
    """

    def __init__(self) -> None:
        self._calculators: dict[CommissionType, CommissionCalculator] = {
            CommissionType.STOCK_A: StockACommission(),
            CommissionType.FUND_ETF: ETFCommission(),
            CommissionType.GOLD_SPOT: GoldSpotCommission(),
            CommissionType.BOND_EXCHANGE: BondExchangeCommission(),
        }
        self._default = StockACommission()

    def set_commission(
        self, commission_type: CommissionType, calc: CommissionCalculator
    ) -> None:
        self._calculators[commission_type] = calc

    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        # 默认使用 A 股佣金
        return self._default.calculate(side, price, quantity)

    def calculate_for(
        self,
        commission_type: CommissionType,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        calc = self._calculators.get(commission_type, self._default)
        return calc.calculate(side, price, quantity)
