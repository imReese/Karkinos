"""Capability-based strategy runtime lifecycle contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from core.events import FillEvent, MarketEvent, OrderEvent
from core.types import Symbol
from data.market_calendar import MarketCalendar


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


class StrategyRuntimeOutputType(Enum):
    """Standard strategy output types before downstream gates."""

    OBSERVATION_SIGNAL = "observation_signal"
    BUY_CANDIDATE = "buy_candidate"
    SELL_CANDIDATE = "sell_candidate"
    REBALANCE_CANDIDATE = "rebalance_candidate"
    RISK_WARNING = "risk_warning"
    NO_ACTION = "no_action"


_CANDIDATE_OUTPUT_TYPES = {
    StrategyRuntimeOutputType.BUY_CANDIDATE,
    StrategyRuntimeOutputType.SELL_CANDIDATE,
    StrategyRuntimeOutputType.REBALANCE_CANDIDATE,
}


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
    market_calendar: MarketCalendar = field(default_factory=MarketCalendar)
    broker_order_submission_enabled: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))
        object.__setattr__(self, "account_facts", _freeze_mapping(self.account_facts))
        object.__setattr__(self, "positions", _freeze_mapping(self.positions))
        object.__setattr__(self, "risk_limits", _freeze_mapping(self.risk_limits))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True)
class StrategyRuntimeOutput:
    """A strategy-provided output before risk/account/review gates."""

    output_type: StrategyRuntimeOutputType
    reason: str
    symbol: Symbol | None = None
    confidence: Decimal | None = None
    target_weight: Decimal | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    evidence: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _freeze_mapping(self.evidence))

    @classmethod
    def observation_signal(
        cls,
        *,
        reason: str,
        symbol: Symbol | None = None,
        confidence: Decimal | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> StrategyRuntimeOutput:
        return cls(
            output_type=StrategyRuntimeOutputType.OBSERVATION_SIGNAL,
            reason=reason,
            symbol=symbol,
            confidence=confidence,
            evidence=evidence or {},
        )

    @classmethod
    def buy_candidate(
        cls,
        *,
        reason: str,
        symbol: Symbol,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        confidence: Decimal | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> StrategyRuntimeOutput:
        return cls(
            output_type=StrategyRuntimeOutputType.BUY_CANDIDATE,
            reason=reason,
            symbol=symbol,
            quantity=quantity,
            price=price,
            confidence=confidence,
            evidence=evidence or {},
        )

    @classmethod
    def sell_candidate(
        cls,
        *,
        reason: str,
        symbol: Symbol,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        confidence: Decimal | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> StrategyRuntimeOutput:
        return cls(
            output_type=StrategyRuntimeOutputType.SELL_CANDIDATE,
            reason=reason,
            symbol=symbol,
            quantity=quantity,
            price=price,
            confidence=confidence,
            evidence=evidence or {},
        )

    @classmethod
    def rebalance_candidate(
        cls,
        *,
        reason: str,
        symbol: Symbol | None = None,
        target_weight: Decimal | None = None,
        confidence: Decimal | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> StrategyRuntimeOutput:
        return cls(
            output_type=StrategyRuntimeOutputType.REBALANCE_CANDIDATE,
            reason=reason,
            symbol=symbol,
            target_weight=target_weight,
            confidence=confidence,
            evidence=evidence or {},
        )

    @classmethod
    def risk_warning(
        cls,
        *,
        reason: str,
        symbol: Symbol | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> StrategyRuntimeOutput:
        return cls(
            output_type=StrategyRuntimeOutputType.RISK_WARNING,
            reason=reason,
            symbol=symbol,
            evidence=evidence or {},
        )

    @classmethod
    def no_action(
        cls,
        *,
        reason: str,
        symbol: Symbol | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> StrategyRuntimeOutput:
        return cls(
            output_type=StrategyRuntimeOutputType.NO_ACTION,
            reason=reason,
            symbol=symbol,
            evidence=evidence or {},
        )


StrategyRuntimeOutputReturn = (
    StrategyRuntimeOutput | Iterable[StrategyRuntimeOutput] | None
)


@dataclass(frozen=True)
class StrategyRuntimeAuditRecord:
    """Auditable runtime output record for downstream gates and review."""

    output_id: str
    strategy_id: str
    run_id: str
    hook: str
    output_type: StrategyRuntimeOutputType
    record_kind: str
    action: str
    reason: str
    schema_version: str = "karkinos.strategy_runtime_output.v1"
    source_event_id: str | None = None
    symbol: Symbol | None = None
    confidence: Decimal | None = None
    target_weight: Decimal | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    evidence: Mapping[str, Any] = MappingProxyType({})
    requires_risk_gate: bool = False
    requires_account_truth_gate: bool = False
    requires_paper_shadow_review: bool = False
    requires_manual_review: bool = False
    does_not_enable_execution: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _freeze_mapping(self.evidence))


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

    def initialize(
        self, context: StrategyRuntimeContext
    ) -> StrategyRuntimeOutputReturn: ...

    def before_market_open(
        self, context: StrategyRuntimeContext
    ) -> StrategyRuntimeOutputReturn: ...

    def on_bar(
        self, context: StrategyRuntimeContext, event: MarketEvent
    ) -> StrategyRuntimeOutputReturn: ...

    def on_tick(
        self, context: StrategyRuntimeContext, event: MarketEvent
    ) -> StrategyRuntimeOutputReturn: ...

    def after_market_close(
        self, context: StrategyRuntimeContext
    ) -> StrategyRuntimeOutputReturn: ...

    def on_order_update(
        self,
        context: StrategyRuntimeContext,
        event: OrderEvent,
    ) -> StrategyRuntimeOutputReturn: ...

    def on_fill_update(
        self,
        context: StrategyRuntimeContext,
        event: FillEvent,
    ) -> StrategyRuntimeOutputReturn: ...


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
    outputs: tuple[StrategyRuntimeAuditRecord, ...] = ()


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
        outputs: list[StrategyRuntimeAuditRecord] = []

        initialize_outputs = strategy.initialize(context)
        records.append(StrategyRuntimeTraceRecord(StrategyLifecycleHook.INITIALIZE))
        _append_audit_records(
            outputs=outputs,
            context=context,
            hook=StrategyLifecycleHook.INITIALIZE,
            source_event_id=None,
            hook_outputs=initialize_outputs,
        )

        before_market_outputs = strategy.before_market_open(context)
        records.append(
            StrategyRuntimeTraceRecord(StrategyLifecycleHook.BEFORE_MARKET_OPEN)
        )
        _append_audit_records(
            outputs=outputs,
            context=context,
            hook=StrategyLifecycleHook.BEFORE_MARKET_OPEN,
            source_event_id=None,
            hook_outputs=before_market_outputs,
        )

        for event in bars:
            hook_outputs = strategy.on_bar(context, event)
            event_id = _market_event_id(event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_BAR,
                    event_id=event_id,
                )
            )
            _append_audit_records(
                outputs=outputs,
                context=context,
                hook=StrategyLifecycleHook.ON_BAR,
                source_event_id=event_id,
                hook_outputs=hook_outputs,
            )

        for event in ticks:
            hook_outputs = strategy.on_tick(context, event)
            event_id = _market_event_id(event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_TICK,
                    event_id=event_id,
                )
            )
            _append_audit_records(
                outputs=outputs,
                context=context,
                hook=StrategyLifecycleHook.ON_TICK,
                source_event_id=event_id,
                hook_outputs=hook_outputs,
            )

        after_market_outputs = strategy.after_market_close(context)
        records.append(
            StrategyRuntimeTraceRecord(StrategyLifecycleHook.AFTER_MARKET_CLOSE)
        )
        _append_audit_records(
            outputs=outputs,
            context=context,
            hook=StrategyLifecycleHook.AFTER_MARKET_CLOSE,
            source_event_id=None,
            hook_outputs=after_market_outputs,
        )

        for event in order_updates:
            hook_outputs = strategy.on_order_update(context, event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_ORDER_UPDATE,
                    event_id=event.order_id,
                )
            )
            _append_audit_records(
                outputs=outputs,
                context=context,
                hook=StrategyLifecycleHook.ON_ORDER_UPDATE,
                source_event_id=event.order_id,
                hook_outputs=hook_outputs,
            )

        for event in fill_updates:
            hook_outputs = strategy.on_fill_update(context, event)
            records.append(
                StrategyRuntimeTraceRecord(
                    StrategyLifecycleHook.ON_FILL_UPDATE,
                    event_id=event.fill_id,
                )
            )
            _append_audit_records(
                outputs=outputs,
                context=context,
                hook=StrategyLifecycleHook.ON_FILL_UPDATE,
                source_event_id=event.fill_id,
                hook_outputs=hook_outputs,
            )

        return StrategyRuntimeResult(
            strategy_id=context.strategy_id,
            run_id=context.run_id,
            records=tuple(records),
            outputs=tuple(outputs),
        )


def _append_audit_records(
    *,
    outputs: list[StrategyRuntimeAuditRecord],
    context: StrategyRuntimeContext,
    hook: StrategyLifecycleHook,
    source_event_id: str | None,
    hook_outputs: StrategyRuntimeOutputReturn,
) -> None:
    for output in _coerce_strategy_outputs(hook_outputs):
        sequence = len(outputs) + 1
        requires_downstream_gates = output.output_type in _CANDIDATE_OUTPUT_TYPES
        outputs.append(
            StrategyRuntimeAuditRecord(
                output_id=(
                    f"{context.run_id}:{sequence:04d}:{output.output_type.value}"
                ),
                strategy_id=context.strategy_id,
                run_id=context.run_id,
                hook=hook.value,
                source_event_id=source_event_id,
                output_type=output.output_type,
                record_kind=_record_kind_for_output(output.output_type),
                action=_action_for_output(output.output_type),
                symbol=output.symbol,
                reason=output.reason,
                confidence=output.confidence,
                target_weight=output.target_weight,
                quantity=output.quantity,
                price=output.price,
                evidence=output.evidence,
                requires_risk_gate=requires_downstream_gates,
                requires_account_truth_gate=requires_downstream_gates,
                requires_paper_shadow_review=requires_downstream_gates,
                requires_manual_review=requires_downstream_gates,
            )
        )


def _coerce_strategy_outputs(
    hook_outputs: StrategyRuntimeOutputReturn,
) -> tuple[StrategyRuntimeOutput, ...]:
    if hook_outputs is None:
        return ()
    if isinstance(hook_outputs, StrategyRuntimeOutput):
        return (hook_outputs,)

    outputs = tuple(hook_outputs)
    for output in outputs:
        if not isinstance(output, StrategyRuntimeOutput):
            raise TypeError(
                "Strategy runtime hooks must return StrategyRuntimeOutput "
                "instances, an iterable of them, or None."
            )
    return outputs


def _record_kind_for_output(output_type: StrategyRuntimeOutputType) -> str:
    if output_type == StrategyRuntimeOutputType.OBSERVATION_SIGNAL:
        return "signal"
    if output_type in _CANDIDATE_OUTPUT_TYPES:
        return "candidate_action"
    if output_type == StrategyRuntimeOutputType.RISK_WARNING:
        return "risk_warning"
    return "explanation"


def _action_for_output(output_type: StrategyRuntimeOutputType) -> str:
    return {
        StrategyRuntimeOutputType.OBSERVATION_SIGNAL: "observe",
        StrategyRuntimeOutputType.BUY_CANDIDATE: "buy",
        StrategyRuntimeOutputType.SELL_CANDIDATE: "sell",
        StrategyRuntimeOutputType.REBALANCE_CANDIDATE: "rebalance",
        StrategyRuntimeOutputType.RISK_WARNING: "review_risk",
        StrategyRuntimeOutputType.NO_ACTION: "no_action",
    }[output_type]


def _market_event_id(event: MarketEvent) -> str:
    return f"{event.symbol}:{event.timestamp.isoformat()}"
