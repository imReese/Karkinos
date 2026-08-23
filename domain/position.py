"""Position — 持仓管理，核心：T+1 冻结/解冻/盯市/盈亏计算。"""

from __future__ import annotations

from decimal import Decimal

from core.types import ZERO, Money, Symbol
from domain.portfolio_accounting import (
    moving_average_cost_after_buy,
    realized_pnl_after_sell,
)


class Position:
    """持仓管理。

    核心职责：
    - 买入/卖出更新持仓
    - T+1 冻结/解冻（A 股买入当日不可卖）
    - 盯市（mark_to_market）计算浮动盈亏
    - 持仓成本与均价计算
    """

    def __init__(self, symbol: Symbol) -> None:
        self.symbol = symbol
        self.quantity: Decimal = ZERO  # 总持仓
        self.frozen_qty: Decimal = ZERO  # T+1 冻结数量（当日买入）
        self.avg_cost: Decimal = ZERO  # 持仓均价（含全部已记录交易费用）
        self.realized_pnl: Decimal = ZERO  # 已实现盈亏
        self.unrealized_pnl: Decimal = ZERO  # 未实现盈亏
        # Legacy public field name; value is the cumulative complete trade fee.
        self.commission_paid: Decimal = ZERO
        self.market_value: Decimal = ZERO  # 当前市值

    @property
    def available_qty(self) -> Decimal:
        """可卖数量 = 总持仓 - 冻结数量。"""
        return self.quantity - self.frozen_qty

    @property
    def cost_basis(self) -> Decimal:
        """持仓成本 = 总持仓 × 均价。"""
        return self.quantity * self.avg_cost

    def update_on_fill(
        self,
        side: str,
        fill_quantity: Decimal,
        fill_price: Decimal,
        commission: Decimal = ZERO,
    ) -> None:
        """根据成交更新持仓。

        买入：加仓或新建，当日买入部分冻结（T+1）。
        卖出：减仓或清仓，按移动加权平均计算已实现盈亏。

        ``commission`` is retained for API compatibility and represents the
        fill's already-resolved total fee at this domain boundary.
        """
        if side == "buy":
            self._handle_buy(fill_quantity, fill_price, commission)
        elif side == "sell":
            self._handle_sell(fill_quantity, fill_price, commission)
        else:
            raise ValueError(f"Unknown side: {side}")

    def _handle_buy(self, qty: Decimal, price: Decimal, commission: Decimal) -> None:
        """买入更新：加权平均计算新均价，冻结 T+1 数量。"""
        self.avg_cost = moving_average_cost_after_buy(
            current_quantity=self.quantity,
            current_average_cost=self.avg_cost,
            fill_quantity=qty,
            fill_price=price,
            total_fee=commission,
        )

        self.quantity += qty
        self.frozen_qty += qty  # 当日买入冻结
        self.commission_paid += commission

    def _handle_sell(self, qty: Decimal, price: Decimal, commission: Decimal) -> None:
        """卖出更新：计算已实现盈亏，减少持仓。"""
        if qty > self.quantity:
            raise ValueError(
                f"Sell quantity {qty} exceeds position {self.quantity} for {self.symbol}"
            )

        pnl = realized_pnl_after_sell(
            average_cost=self.avg_cost,
            fill_quantity=qty,
            fill_price=price,
            total_fee=commission,
        )
        self.realized_pnl += pnl
        self.commission_paid += commission
        self.quantity -= qty

        # 清仓时重置均价
        if self.quantity == ZERO:
            self.avg_cost = ZERO

    def advance_settlement_day(self) -> None:
        """结算日推进：将冻结数量解冻到可卖数量。"""
        self.frozen_qty = ZERO

    def mark_to_market(self, current_price: Decimal) -> None:
        """盯市：按当前价格计算市值和未实现盈亏。"""
        self.market_value = self.quantity * current_price
        self.unrealized_pnl = self.market_value - self.cost_basis

    def __repr__(self) -> str:
        return (
            f"Position(symbol={self.symbol}, qty={self.quantity}, "
            f"available={self.available_qty}, frozen={self.frozen_qty}, "
            f"avg_cost={self.avg_cost}, unrealized={self.unrealized_pnl})"
        )
