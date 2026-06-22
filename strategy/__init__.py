"""策略框架层。"""

from strategy.base import Strategy
from strategy.registry import StrategyRegistry, register_strategy
from strategy.runtime import (
    STRATEGY_RUNTIME_LIFECYCLE_HOOKS,
    StrategyLifecycleHook,
    StrategyRuntimeAuditRecord,
    StrategyRuntimeContext,
    StrategyRuntimeOutput,
    StrategyRuntimeOutputType,
    StrategyRuntimeResult,
    StrategyRuntimeRunner,
    StrategyRuntimeTraceRecord,
)
from strategy.signals import Signal, SignalType

__all__ = [
    "STRATEGY_RUNTIME_LIFECYCLE_HOOKS",
    "Signal",
    "SignalType",
    "Strategy",
    "StrategyLifecycleHook",
    "StrategyRegistry",
    "StrategyRuntimeAuditRecord",
    "StrategyRuntimeContext",
    "StrategyRuntimeOutput",
    "StrategyRuntimeOutputType",
    "StrategyRuntimeResult",
    "StrategyRuntimeRunner",
    "StrategyRuntimeTraceRecord",
    "register_strategy",
]
