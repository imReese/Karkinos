"""风控限制规则实现。"""

from __future__ import annotations

from decimal import Decimal

from core.events import OrderEvent
from core.types import OrderSide, Symbol
from domain.position import Position
from risk.rules import RiskCheckResult, RiskRule


class PositionLimitRule(RiskRule):
    """仓位上限规则。

    限制单个标的的最大持仓数量。
    """

    def __init__(self, max_quantity: Decimal) -> None:
        self._max_quantity = max_quantity

    @property
    def name(self) -> str:
        return "position_limit"

    def check(
        self,
        order: OrderEvent,
        positions: dict[Symbol, Position],
        portfolio_value: dict[str, float],
    ) -> RiskCheckResult:
        if order.side != OrderSide.BUY:
            return RiskCheckResult(passed=True)

        current_pos = positions.get(order.symbol)
        current_qty = current_pos.quantity if current_pos else Decimal("0")

        if current_qty + order.quantity > self._max_quantity:
            return RiskCheckResult(
                passed=False,
                message=(
                    f"Position limit exceeded: {current_qty + order.quantity} > "
                    f"{self._max_quantity} for {order.symbol}"
                ),
            )

        return RiskCheckResult(passed=True)


class MaxDrawdownRule(RiskRule):
    """最大回撤规则。

    当组合回撤超过阈值时拒绝所有新买入。
    """

    def __init__(self, max_drawdown_pct: Decimal = Decimal("0.15")) -> None:
        self._max_drawdown_pct = max_drawdown_pct
        self._peak_value: float = 0.0

    @property
    def name(self) -> str:
        return "max_drawdown"

    def check(
        self,
        order: OrderEvent,
        positions: dict[Symbol, Position],
        portfolio_value: dict[str, float],
    ) -> RiskCheckResult:
        total = portfolio_value.get("total", 0.0)
        if total <= 0:
            return RiskCheckResult(passed=True)

        if total > self._peak_value:
            self._peak_value = total

        if self._peak_value <= 0:
            return RiskCheckResult(passed=True)

        drawdown = (self._peak_value - total) / self._peak_value
        if Decimal(str(drawdown)) > self._max_drawdown_pct:
            if order.side == OrderSide.BUY:
                return RiskCheckResult(
                    passed=False,
                    message=f"Max drawdown exceeded: {drawdown:.2%} > {self._max_drawdown_pct:.2%}",
                )

        return RiskCheckResult(passed=True)


class ConcentrationRule(RiskRule):
    """集中度规则。

    限制单个标的占总资产的最大比例。
    """

    def __init__(self, max_concentration: Decimal = Decimal("0.30")) -> None:
        self._max_concentration = max_concentration

    @property
    def name(self) -> str:
        return "concentration"

    def check(
        self,
        order: OrderEvent,
        positions: dict[Symbol, Position],
        portfolio_value: dict[str, float],
    ) -> RiskCheckResult:
        if order.side != OrderSide.BUY:
            return RiskCheckResult(passed=True)

        total = portfolio_value.get("total", 0.0)
        if total <= 0:
            return RiskCheckResult(passed=True)

        order_value = float(order.quantity) * float(order.price or 0)
        current_pos = positions.get(order.symbol)
        current_value = float(current_pos.market_value) if current_pos else 0.0

        concentration = (current_value + order_value) / total
        if Decimal(str(concentration)) > self._max_concentration:
            return RiskCheckResult(
                passed=False,
                message=(
                    f"Concentration limit exceeded for {order.symbol}: "
                    f"{concentration:.2%} > {self._max_concentration:.2%}"
                ),
            )

        return RiskCheckResult(passed=True)
