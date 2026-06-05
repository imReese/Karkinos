"""EventBusBridge — 订阅 EventBus 同步事件，推入 asyncio.Queue。"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from core.event_bus import EventBus, Handler
from core.events import (
    Event,
    FillEvent,
    MarketEvent,
    OrderEvent,
    RiskAlertEvent,
    SignalEvent,
)

logger = logging.getLogger(__name__)

# 所有需要订阅的事件类型
_EVENT_TYPES: list[type[Event]] = [
    MarketEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
    RiskAlertEvent,
]


class EventBusBridge:
    """桥接同步 EventBus → 异步 asyncio.Queue。

    在后台线程中订阅所有事件，通过 run_coroutine_threadsafe
    将序列化后的事件推入 asyncio.Queue，供 WebSocket 端点消费。
    """

    def __init__(self, event_bus: EventBus, loop: asyncio.AbstractEventLoop) -> None:
        self._event_bus = event_bus
        self._loop = loop
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._handlers: list[tuple[type[Event], Handler]] = []

    def start(self) -> None:
        """订阅所有事件类型。"""
        for event_type in _EVENT_TYPES:
            handler = self._make_handler(event_type)
            self._event_bus.subscribe(event_type, handler)
            self._handlers.append((event_type, handler))
        logger.info(
            "EventBusBridge started, subscribed to %d event types", len(_EVENT_TYPES)
        )

    def stop(self) -> None:
        """取消所有订阅。"""
        for event_type, handler in self._handlers:
            self._event_bus.unsubscribe(event_type, handler)
        self._handlers.clear()
        logger.info("EventBusBridge stopped")

    def rebind(self, new_bus: EventBus) -> None:
        """重新绑定到新的 EventBus，复用同一对象。

        先 stop 旧订阅，再绑定新 bus 并 start。
        保证 AppState.bridge 始终指向同一实例。
        """
        self.stop()
        self._event_bus = new_bus
        self.start()
        logger.info("EventBusBridge rebound to new EventBus")

    def _make_handler(self, event_type: type[Event]) -> Handler:
        """为每种事件类型创建 handler。"""

        def handler(event: Event) -> None:
            data = self._serialize(event)
            # 从后台线程安全推入 asyncio.Queue
            asyncio.run_coroutine_threadsafe(self._queue.put(data), self._loop)

        handler.__name__ = f"_bridge_handler_{event_type.__name__}"
        return handler

    async def get_event(self) -> dict[str, Any]:
        """异步消费事件。"""
        return await self._queue.get()

    def _serialize(self, event: Event) -> dict[str, Any]:
        """将 frozen dataclass 事件序列化为 JSON-safe dict。"""
        data = dataclasses.asdict(event)
        data["event_type"] = type(event).__name__
        return self._convert(data)

    def _convert(self, obj: Any) -> Any:
        """递归转换不可序列化的类型。"""
        if isinstance(obj, dict):
            return {k: self._convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._convert(v) for v in obj]
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj
