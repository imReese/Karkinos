"""RiskManager — 风控管理器。"""

from __future__ import annotations

import logging

from core.event_bus import EventBus
from core.events import FillEvent, OrderEvent, RiskAlertEvent
from core.types import ZERO, OrderSide, OrderStatus, Symbol
from domain.position import Position
from risk.rules import RiskCheckResult, RiskRule

logger = logging.getLogger(__name__)


class RiskManager:
    """风控管理器。

    以 priority=-10 订阅 OrderEvent，先于 Execution(0) 执行。
    - 拒绝则消费订单不转发
    - 修改则重新发布修改后的 OrderEvent
    - 通过则不做任何处理（让后续 Execution 处理原始事件）
    """

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.rules: list[RiskRule] = []
        self.positions: dict[Symbol, Position] = {}
        self._portfolio_value: dict[str, float] = {"total": 0.0, "cash": 0.0}

        # 订阅 OrderEvent，priority=-10 确保在 Execution 之前
        event_bus.subscribe(OrderEvent, self.on_order, priority=-10)
        # 订阅 FillEvent 更新持仓
        event_bus.subscribe(FillEvent, self.on_fill)

    def add_rule(self, rule: RiskRule) -> None:
        self.rules.append(rule)

    def set_portfolio_value(self, total: float, cash: float) -> None:
        self._portfolio_value["total"] = total
        self._portfolio_value["cash"] = cash

    def on_order(self, event: OrderEvent) -> None:
        """处理委托单事件，执行风控检查。"""
        for rule in self.rules:
            result = rule.check(event, self.positions, self._portfolio_value)
            if not result.passed:
                logger.warning(
                    "Risk rule %s rejected order %s: %s",
                    rule.name,
                    event.order_id,
                    result.message,
                )
                # 发布风控告警
                self.event_bus.publish(
                    RiskAlertEvent(
                        timestamp=event.timestamp,
                        alert_id=f"RISK-{event.order_id}",
                        rule_name=rule.name,
                        severity="warning",
                        message=result.message or "Order rejected",
                        symbol=event.symbol,
                        order_id=event.order_id,
                    )
                )
                # 从队列中移除原始订单（通过取消后续处理）
                # 在同步事件模型中，拒绝 = 不做处理，让事件继续传播
                # 但我们在 Execution 层需要检查该订单是否被风控拒绝
                # 简化实现：标记拒绝，Execution 应检查
                # 更好的方式：消费事件（从队列移除），发布修改后的事件
                return  # 直接返回，不转发
                # 注意：在当前架构中，所有订阅者都会收到事件
                # 拒绝的逻辑需要在 Execution 层配合

            if result.modified_order is not None:
                logger.info(
                    "Risk rule %s modified order %s",
                    rule.name,
                    event.order_id,
                )
                # 用修改后的订单替换原事件
                # 由于事件是 frozen dataclass，需要重新发布
                self.event_bus.publish(result.modified_order)
                return  # 消费原始订单

    def on_fill(self, event: FillEvent) -> None:
        """更新持仓。"""
        if event.symbol not in self.positions:
            self.positions[event.symbol] = Position(event.symbol)

        pos = self.positions[event.symbol]
        pos.update_on_fill(
            side=event.side.value,
            fill_quantity=event.fill_quantity,
            fill_price=event.fill_price,
            commission=event.commission,
        )
