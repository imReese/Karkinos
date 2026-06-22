"""Capability-based strategy runtime lifecycle contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from core.events import FillEvent, MarketEvent, OrderEvent
from core.types import Symbol


class StrategyLifecycleHook(Enum):
    """Supported strategy runtime lifecycle hooks."""

    INITIALIZE = "initialize"
    BEFORE_MARKET_OPEN = "before_market_open"
    ON_BAR = "on_bar"
    ON_TICK = "on_tick"
    AFTER_MARKET_CLOSE = "after_market_close"
    ON_ORDER_UPDATE = "on_order_update"
    ON_FILL_UPDATE = "on_fill_update"


STRATEGY_RUNTIME_LIFECYCLE_HOOKS: tuple[StrategyLifecycleHook, ...] = (
    StrategyLifecycleHook.INITIALIZE,
    StrategyLifecycleHook.BEFORE_MARKET_OPEN,
    StrategyLifecycleHook.ON_BAR,
    StrategyLifecycleHook.ON_TICK,
    StrategyLifecycleHook.AFTER_MARKET_CLOSE,
    StrategyLifecycleHook.ON_ORDER_UPDATE,
    StrategyLifecycleHook.ON_FILL_UPDATE,
)


@dataclass(frozen=True)
class StrategyRuntimeContext:
    """Read-oriented metadata passed to strategy lifecycle hooks."""

    strategy_id: str
    run_id: str
    symbols: tuple[Symbol, ...] = ()
    parameters: Mapping[str, Any] = MappingProxyType({})
    account_facts: Mapping[str, Any] = MappingProxyType({})
    positions: Mapping[str, Any] = MappingProxyType({})
    risk_limits: Mapping[str, Any] = MappingProxyType({})
    metadata: Mapping[str, Any] = MappingProxyType({})
    broker_order_submission_enabled: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))
        object.__setattr__(self, "account_facts", _freeze_mapping(self.account_facts))
        object.__setattr__(self, "positions", _freeze_mapping(self.positions))
        object.__setattr__(self, "risk_limits", _freeze_mapping(self.risk_limits))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value


class StrategyRuntimeStrategy(Protocol):
    """Protocol implemented by lifecycle-capable strategies."""

    def initialize(self, context: StrategyRuntimeContext) -> None: ...

    def before_market_open(self, context: StrategyRuntimeContext) -> None: ...

    def on_bar(self, context: StrategyRuntimeContext, event: MarketEvent) -> None: ...

    def on_tick(self, context: StrategyRuntimeContext, event: MarketEvent) -> None: ...

    def after_market_close(self, context: StrategyRuntimeContext) -> None: ...

    def on_order_update(
        self,
        context: StrategyRuntimeContext,
        event: OrderEvent,
    ) -> None: ...

    def on_fill_update(
        self,
        context: StrategyRuntimeContext,
        event: FillEvent,
    ) -> None: ...


@dataclass(frozen=True)
class StrategyRuntimeTraceRecord:
    """One lifecycle hook invocation recorded for audit/replay."""

    hook: StrategyLifecycleHook
    event_id: str | None = None


@dataclass(frozen=True)
class StrategyRuntimeResult:
    """Deterministic runtime execution trace."""

    strategy_id: str
    run_id: str
    records: tuple[StrategyRuntimeTraceRecord, ...]


class StrategyRuntimeRunner:
    """Invoke strategy lifecycle hooks in a deterministic session order."""

    def run_session(
        self,
        *,
        strategy: StrategyRuntimeStrategy,
        context: StrategyRuntimeContext,
        bars: Iterable[MarketEvent] = (),
        ticks: Iterable[MarketEvent] = (),
        order_updates: Iterable[OrderEvent] = (),
        fill_updates: Iterable[FillEvent] = (),
    ) -> StrategyRuntimeResult:
        records: list[StrategyRuntimeTraceRecord] = []

        strategy.initialize(context)
        records.append(StrategyRuntimeTraceRecord(StrategyLifecycleHook.INITIALIZE))

        strategy.before_market_open(context)
        records.append(
            StrategyRuntimeTraceRecord(StrategyLifecycleHook.BEFORE_MARKET_OPEN)
        )

        for event in bars:
            strategy.on_bar(context, event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_BAR,
                    event_id=f"{event.symbol}:{event.timestamp.isoformat()}",
                )
            )

        for event in ticks:
            strategy.on_tick(context, event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_TICK,
                    event_id=f"{event.symbol}:{event.timestamp.isoformat()}",
                )
            )

        strategy.after_market_close(context)
        records.append(
            StrategyRuntimeTraceRecord(StrategyLifecycleHook.AFTER_MARKET_CLOSE)
        )

        for event in order_updates:
            strategy.on_order_update(context, event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_ORDER_UPDATE,
                    event_id=event.order_id,
                )
            )

        for event in fill_updates:
            strategy.on_fill_update(context, event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_FILL_UPDATE,
                    event_id=event.fill_id,
                )
            )

        return StrategyRuntimeResult(
            strategy_id=context.strategy_id,
            run_id=context.run_id,
            records=tuple(records),
        )
