"""LiveExecution — 实盘执行（预留空壳）。"""

from __future__ import annotations

from core.events import FillEvent, OrderEvent
from execution.engine import ExecutionEngine


class LiveExecution(ExecutionEngine):
    """实盘执行引擎（预留空壳）。

    实际对接券商 API 时实现。
    """

    def execute(self, order: OrderEvent) -> FillEvent | None:
        raise NotImplementedError("LiveExecution not implemented yet")
