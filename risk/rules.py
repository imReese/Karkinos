"""RiskRule — 风控规则抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.events import OrderEvent
from core.types import Symbol
from domain.position import Position


@dataclass
class RiskCheckResult:
    """风控检查结果。"""

    passed: bool
    message: str | None = None
    modified_order: OrderEvent | None = None  # 修改后的订单（如需调整）


class RiskRule(ABC):
    """风控规则抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """规则名称。"""

    @abstractmethod
    def check(
        self,
        order: OrderEvent,
        positions: dict[Symbol, Position],
        portfolio_value: dict[str, float],
    ) -> RiskCheckResult:
        """检查订单是否通过风控规则。"""
