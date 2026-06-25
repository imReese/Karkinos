"""SimulatedExecution — 回测模拟执行引擎。"""

from __future__ import annotations

import uuid
from decimal import Decimal

from core.events import FillEvent, OrderEvent
from core.types import ZERO, Symbol
from execution.commission import CommissionCalculator, StockACommission
from execution.engine import ExecutionEngine
from execution.slippage import FixedSlippage, SlippageModel


class SimulatedExecution(ExecutionEngine):
    """回测模拟执行引擎。

    使用滑点模型模拟成交价格，使用佣金模型计算费用。
    """

    def __init__(
        self,
        slippage_model: SlippageModel | None = None,
        commission_calc: CommissionCalculator | None = None,
    ) -> None:
        self.slippage_model = slippage_model or FixedSlippage(Decimal("0"))
        self.commission_calc = commission_calc or StockACommission()

    def execute(self, order: OrderEvent) -> FillEvent | None:
        """模拟执行委托单。

        对于市价单，以 order.price（参考价格）+ 滑点成交。
        """
        fill_price = self._apply_slippage(order)
        fill_quantity = order.quantity
        fee_breakdown = self.commission_calc.breakdown(
            order.side, fill_price, fill_quantity
        )
        commission = fee_breakdown.total_fee
        slippage = abs(fill_price - (order.price or fill_price)) * fill_quantity

        return FillEvent(
            timestamp=order.timestamp,
            fill_id=f"FILL-{uuid.uuid4().hex[:8]}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            fill_price=fill_price,
            fill_quantity=fill_quantity,
            commission=commission,
            slippage=slippage,
            fee_breakdown=fee_breakdown.to_json_dict(),
            fee_rule_id=fee_breakdown.fee_rule_id,
            fee_rule_version="backtest_commission_model",
        )

    def _apply_slippage(self, order: OrderEvent) -> Decimal:
        """应用滑点模型。"""
        base_price = order.price or Decimal("0")
        return self.slippage_model.apply(base_price, order.side, order.quantity)
