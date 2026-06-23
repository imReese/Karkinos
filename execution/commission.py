"""Commission — 佣金模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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


@dataclass(frozen=True)
class FeeBreakdown:
    """Structured fee/tax breakdown for audit and reconciliation."""

    gross_amount: Decimal
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    other_fees: Decimal
    total_fee: Decimal
    fee_rule_id: str
    limitations: tuple[str, ...] = ()


class CommissionCalculator(ABC):
    """佣金计算抽象基类。"""

    @abstractmethod
    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        """计算佣金。"""

    def breakdown(
        self, side: OrderSide, price: Decimal, quantity: Decimal
    ) -> FeeBreakdown:
        """Return a structured breakdown while preserving legacy calculators."""
        total_fee = self.calculate(side, price, quantity)
        return FeeBreakdown(
            gross_amount=price * quantity,
            commission=total_fee,
            stamp_tax=ZERO,
            transfer_fee=ZERO,
            other_fees=ZERO,
            total_fee=total_fee,
            fee_rule_id=self.__class__.__name__,
            limitations=("legacy_total_fee_only",),
        )


class StockACommission(CommissionCalculator):
    """A 股佣金模型。

    佣金 = max(金额 × 佣金率, 5) + 印花税(卖0.05%) + 过户费(0.001%)
    """

    def __init__(
        self,
        commission_rate: Decimal = DEFAULT_STOCK_COMMISSION_RATE,
        min_commission: Decimal = MIN_STOCK_COMMISSION,
        stamp_tax_rate: Decimal = STAMP_TAX_RATE,
        transfer_fee_rate: Decimal = TRANSFER_FEE_RATE,
        other_fee_rate: Decimal = ZERO,
        fee_rule_id: str = "cn_stock_a_default_v1",
        limitations: tuple[str, ...] = (
            "transfer_fee_exchange_not_split",
            "broker_regulatory_fees_assumed_absorbed",
        ),
    ) -> None:
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate
        self.transfer_fee_rate = transfer_fee_rate
        self.other_fee_rate = other_fee_rate
        self.fee_rule_id = fee_rule_id
        self.limitations = limitations

    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        return self.breakdown(side, price, quantity).total_fee

    def breakdown(
        self, side: OrderSide, price: Decimal, quantity: Decimal
    ) -> FeeBreakdown:
        amount = price * quantity
        # 券商佣金
        commission = max(amount * self.commission_rate, self.min_commission)
        # 印花税（仅卖出）
        stamp_tax = ZERO
        if side == OrderSide.SELL:
            stamp_tax = amount * self.stamp_tax_rate
        # 过户费
        transfer_fee = amount * self.transfer_fee_rate
        other_fees = amount * self.other_fee_rate
        total_fee = commission + stamp_tax + transfer_fee + other_fees
        return FeeBreakdown(
            gross_amount=amount,
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            other_fees=other_fees,
            total_fee=total_fee,
            fee_rule_id=self.fee_rule_id,
            limitations=self.limitations,
        )


class ETFCommission(CommissionCalculator):
    """ETF 佣金模型。

    佣金 = max(金额 × 佣金率, 5)
    无印花税，有过户费。
    """

    def __init__(
        self,
        commission_rate: Decimal = DEFAULT_ETF_COMMISSION_RATE,
        min_commission: Decimal = MIN_ETF_COMMISSION,
        transfer_fee_rate: Decimal = TRANSFER_FEE_RATE,
        other_fee_rate: Decimal = ZERO,
        fee_rule_id: str = "cn_fund_etf_default_v1",
        limitations: tuple[str, ...] = ("broker_regulatory_fees_assumed_absorbed",),
    ) -> None:
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.transfer_fee_rate = transfer_fee_rate
        self.other_fee_rate = other_fee_rate
        self.fee_rule_id = fee_rule_id
        self.limitations = limitations

    def calculate(self, side: OrderSide, price: Decimal, quantity: Decimal) -> Decimal:
        return self.breakdown(side, price, quantity).total_fee

    def breakdown(
        self, side: OrderSide, price: Decimal, quantity: Decimal
    ) -> FeeBreakdown:
        amount = price * quantity
        commission = max(amount * self.commission_rate, self.min_commission)
        # ETF 无印花税，有过户费
        transfer_fee = amount * self.transfer_fee_rate
        other_fees = amount * self.other_fee_rate
        total_fee = commission + transfer_fee + other_fees
        return FeeBreakdown(
            gross_amount=amount,
            commission=commission,
            stamp_tax=ZERO,
            transfer_fee=transfer_fee,
            other_fees=other_fees,
            total_fee=total_fee,
            fee_rule_id=self.fee_rule_id,
            limitations=self.limitations,
        )


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

    def breakdown_for(
        self,
        commission_type: CommissionType,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> FeeBreakdown:
        calc = self._calculators.get(commission_type, self._default)
        return calc.breakdown(side, price, quantity)
