"""事件总线：发布/订阅/优先级。"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from core.events import Event

logger = logging.getLogger(__name__)

# 回调签名
Handler = Callable[[Event], None]


class EventBus:
    """同步事件总线。

    - 订阅者可设优先级，数值越小越先执行
    - 支持 drain 一次性处理队列中所有事件
    - 回测用同步模式，保证确定性
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[tuple[int, Handler]]] = defaultdict(list)
        self._queue: list[Event] = []

    # ---------- 订阅 ----------

    def subscribe(
        self,
        event_type: type[Event],
        handler: Handler,
        priority: int = 0,
    ) -> None:
        """订阅事件。priority 越小越先执行。"""
        self._handlers[event_type].append((priority, handler))
        self._handlers[event_type].sort(key=lambda x: x[0])

    def unsubscribe(
        self,
        event_type: type[Event],
        handler: Handler,
    ) -> None:
        """取消订阅。"""
        entries = self._handlers.get(event_type, [])
        self._handlers[event_type] = [(p, h) for p, h in entries if h != handler]

    # ---------- 发布 ----------

    def publish(self, event: Event) -> None:
        """将事件入队。"""
        self._queue.append(event)

    def publish_and_process(self, event: Event) -> None:
        """立即发布并处理单个事件（不经过队列）。"""
        self._dispatch(event)

    # ---------- 处理 ----------

    def drain(self) -> int:
        """处理队列中所有事件，返回处理数量。

        处理过程中新发布的事件也会被处理（直到队列为空）。
        """
        count = 0
        while self._queue:
            event = self._queue.pop(0)
            self._dispatch(event)
            count += 1
        return count

    # ---------- 内部 ----------

    def _dispatch(self, event: Event) -> None:
        """将事件分发给所有订阅者。"""
        event_type = type(event)
        # 同时匹配具体类型及其基类
        for registered_type, entries in self._handlers.items():
            if isinstance(event, registered_type):
                for _priority, handler in entries:
                    try:
                        handler(event)
                    except Exception:
                        logger.exception(
                            "Handler %s failed for event %s",
                            handler.__name__,
                            event_type.__name__,
                        )

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def clear(self) -> None:
        """清空队列和所有订阅。"""
        self._queue.clear()
        self._handlers.clear()
