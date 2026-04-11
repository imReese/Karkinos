"""Signal — 信号类型与数据模型。"""

from __future__ import annotations

from enum import Enum


class SignalType(Enum):
    """信号类型。"""

    LONG = "long"  # 看多
    SHORT = "short"  # 看空
    EXIT_LONG = "exit_long"  # 平多
    EXIT_SHORT = "exit_short"  # 平空


class Signal:
    """策略信号数据模型。

    在事件驱动架构中，信号通过 SignalEvent 传递。
    此类用于策略内部逻辑中的信号表示。
    """

    def __init__(
        self,
        signal_type: SignalType,
        symbol: str,
        strength: float = 1.0,
    ) -> None:
        self.signal_type = signal_type
        self.symbol = symbol
        self.strength = strength

    def __repr__(self) -> str:
        return (
            f"Signal({self.signal_type.value}, {self.symbol}, strength={self.strength})"
        )
