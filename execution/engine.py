"""ExecutionEngine — 执行引擎抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from core.events import FillEvent, OrderEvent
from core.types import Symbol


class ExecutionEngine(ABC):
    """执行引擎抽象基类。

    回测用 SimulatedExecution，实盘用 LiveExecution。
    """

    @abstractmethod
    def execute(self, order: OrderEvent) -> FillEvent | None:
        """执行委托单，返回 FillEvent 或 None（失败时）。"""
