"""Strategy — 策略抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import FillEvent, MarketEvent, SignalEvent
from core.types import Symbol


class Strategy(ABC):
    """策略抽象基类。

    子类实现 on_init/on_data/on_fill 三个生命周期方法。
    持有 event_bus 引用，通过 event_bus.publish(SignalEvent(...)) 发射信号。
    """

    def __init__(self, strategy_id: str, event_bus: EventBus) -> None:
        self.strategy_id = strategy_id
        self.event_bus = event_bus
        self._last_timestamp: datetime | None = None

    @abstractmethod
    def on_init(self, symbols: list[Symbol]) -> None:
        """初始化策略，传入关注的标的列表。"""

    @abstractmethod
    def on_data(self, event: MarketEvent) -> None:
        """收到行情事件时触发。"""

    def on_fill(self, event: FillEvent) -> None:
        """收到成交回报时触发（可选覆盖）。"""

    def emit_signal(
        self,
        symbol: Symbol,
        target_weight: float,
        price: float | None = None,
    ) -> None:
        """发射目标权重信号。"""
        ts = self._last_timestamp or datetime.now()
        self.event_bus.publish(
            SignalEvent(
                timestamp=ts,
                strategy_id=self.strategy_id,
                symbol=symbol,
                target_weight=Decimal(str(target_weight)),
                price=Decimal(str(price)) if price is not None else None,
            )
        )
