"""时钟抽象：模拟时钟与实盘时钟。"""

from __future__ import annotations

from datetime import datetime


class Clock:
    """时钟抽象基类。"""

    def now(self) -> datetime:
        raise NotImplementedError


class SimulatedClock(Clock):
    """回测用模拟时钟，由外部设置当前时间。"""

    def __init__(self) -> None:
        self._current_time: datetime | None = None

    def now(self) -> datetime:
        if self._current_time is None:
            raise RuntimeError("SimulatedClock has not been set")
        return self._current_time

    def set_time(self, dt: datetime) -> None:
        self._current_time = dt

    def advance_to(self, dt: datetime) -> None:
        """前进到指定时间（不允许倒退）。"""
        if self._current_time is not None and dt < self._current_time:
            raise ValueError(f"Cannot advance backwards: {dt} < {self._current_time}")
        self._current_time = dt


class LiveClock(Clock):
    """实盘用真实时钟。"""

    def now(self) -> datetime:
        return datetime.now()
