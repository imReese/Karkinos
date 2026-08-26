"""Typed aggregate command for one atomic paper-shadow simulation run."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from server.contracts.content_identity import content_fingerprint
from server.contracts.order_state import OmsOrderCommand, OmsTransitionCommand

JsonObject = dict[str, Any]
PAPER_SHADOW_MODE = "paper_shadow"
PAPER_SHADOW_SOURCE = "paper_shadow_daily"


def _required(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _positive_decimal(value: float, *, field_name: str) -> None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite and positive") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field_name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class PaperShadowOrderFact:
    """Immutable shared-order projection and its complete OMS history."""

    order_id: str
    timestamp: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float | None
    asset_class: str
    intent_id: str
    risk_decision_id: str | None
    status: str
    source_ref: str
    payload: JsonObject
    oms_create: OmsOrderCommand
    oms_transitions: tuple[OmsTransitionCommand, ...]
    execution_mode: str = PAPER_SHADOW_MODE
    source: str = PAPER_SHADOW_SOURCE

    def __post_init__(self) -> None:
        _required(self.order_id, field_name="order_id")
        _required(self.timestamp, field_name="timestamp")
        _required(self.symbol, field_name="symbol")
        _required(self.intent_id, field_name="intent_id")
        _required(self.source_ref, field_name="source_ref")
        _required(self.status, field_name="status")
        _positive_decimal(self.quantity, field_name="order quantity")
        if self.execution_mode != PAPER_SHADOW_MODE:
            raise ValueError("paper-shadow order must remain simulation-only")
        if self.source != PAPER_SHADOW_SOURCE:
            raise ValueError("paper-shadow order source is immutable")
        if self.oms_create.order_id != self.order_id:
            raise ValueError("paper-shadow OMS identity must match its order")
        if self.oms_create.broker_submission_enabled:
            raise ValueError("paper-shadow OMS must not authorize broker submission")
        if self.oms_create.source_ref != self.source_ref:
            raise ValueError("paper-shadow OMS must reference its aggregate run")
        expected_from = self.oms_create.initial_status
        for transition in self.oms_transitions:
            if transition.order_id != self.order_id:
                raise ValueError("paper-shadow OMS transition identity drifted")
            if transition.expected_from != expected_from:
                raise ValueError("paper-shadow OMS history is not contiguous")
            expected_from = transition.to_status
        projected_terminal = "rejected" if self.status == "failed" else self.status
        if expected_from != projected_terminal:
            raise ValueError("paper-shadow order and OMS terminal states differ")
        if self.payload.get("does_not_submit_broker_order") is not True:
            raise ValueError("paper-shadow order must deny broker submission")
        if self.payload.get("does_not_mutate_production_ledger") is not True:
            raise ValueError("paper-shadow order must deny production-ledger writes")

    def identity_payload(self) -> JsonObject:
        return {
            "order_id": self.order_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": str(Decimal(str(self.quantity)).normalize()),
            "price": (
                str(Decimal(str(self.price)).normalize())
                if self.price is not None
                else None
            ),
            "asset_class": self.asset_class,
            "intent_id": self.intent_id,
            "risk_decision_id": self.risk_decision_id,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "source": self.source,
            "source_ref": self.source_ref,
            "payload": self.payload,
            "oms_create": self.oms_create.identity_payload(),
            "oms_transitions": [
                command.identity_payload() for command in self.oms_transitions
            ],
        }


@dataclass(frozen=True, slots=True)
class PaperShadowFillFact:
    """Immutable simulated fill projection owned by one shadow run."""

    fill_id: str
    order_id: str
    timestamp: str
    symbol: str
    side: str
    fill_price: float
    fill_quantity: float
    commission: float
    slippage: float
    asset_class: str
    provider_name: str
    broker_order_id: str
    source_ref: str
    metadata: JsonObject
    execution_mode: str = PAPER_SHADOW_MODE
    source: str = PAPER_SHADOW_SOURCE

    def __post_init__(self) -> None:
        _required(self.fill_id, field_name="fill_id")
        _required(self.order_id, field_name="order_id")
        _required(self.timestamp, field_name="timestamp")
        _positive_decimal(self.fill_price, field_name="fill price")
        _positive_decimal(self.fill_quantity, field_name="fill quantity")
        if self.execution_mode != PAPER_SHADOW_MODE:
            raise ValueError("paper-shadow fill must remain simulation-only")
        if self.source != PAPER_SHADOW_SOURCE:
            raise ValueError("paper-shadow fill source is immutable")
        if self.broker_order_id != self.order_id:
            raise ValueError("simulated broker-order identity must match its order")
        if self.metadata.get("does_not_submit_broker_order") is not True:
            raise ValueError("paper-shadow fill must deny broker submission")
        if self.metadata.get("does_not_mutate_production_ledger") is not True:
            raise ValueError("paper-shadow fill must deny production-ledger writes")

    def identity_payload(self) -> JsonObject:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "side": self.side,
            "fill_price": str(Decimal(str(self.fill_price)).normalize()),
            "fill_quantity": str(Decimal(str(self.fill_quantity)).normalize()),
            "commission": str(Decimal(str(self.commission)).normalize()),
            "slippage": str(Decimal(str(self.slippage)).normalize()),
            "asset_class": self.asset_class,
            "execution_mode": self.execution_mode,
            "provider_name": self.provider_name,
            "broker_order_id": self.broker_order_id,
            "source": self.source,
            "source_ref": self.source_ref,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class PaperShadowRunCommand:
    """Persist a run, all order/fill facts, OMS history, claims, and events once."""

    run_id: str
    plan_date: str
    input_fingerprint: str
    status: str
    order_intent_count: int
    divergence_status: str
    next_manual_review_step: str
    limitations: tuple[str, ...]
    payload: JsonObject
    orders: tuple[PaperShadowOrderFact, ...] = field(default_factory=tuple)
    fills: tuple[PaperShadowFillFact, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _required(self.run_id, field_name="run_id")
        _required(self.plan_date, field_name="plan_date")
        _required(self.input_fingerprint, field_name="input_fingerprint")
        _required(self.status, field_name="status")
        _required(self.divergence_status, field_name="divergence_status")
        _required(self.next_manual_review_step, field_name="next_manual_review_step")
        if self.order_intent_count < 0:
            raise ValueError("order_intent_count must not be negative")
        order_ids = [order.order_id for order in self.orders]
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("paper-shadow order IDs must be unique")
        fill_ids = [fill.fill_id for fill in self.fills]
        if len(fill_ids) != len(set(fill_ids)):
            raise ValueError("paper-shadow fill IDs must be unique")
        if any(order.source_ref != self.run_id for order in self.orders):
            raise ValueError("every paper-shadow order must belong to its run")
        if any(fill.source_ref != self.run_id for fill in self.fills):
            raise ValueError("every paper-shadow fill must belong to its run")
        if any(fill.order_id not in set(order_ids) for fill in self.fills):
            raise ValueError("paper-shadow fill must reference an aggregate order")
        if self.payload.get("run_id") != self.run_id:
            raise ValueError("paper-shadow payload run identity drifted")
        if self.payload.get("input_fingerprint") != self.input_fingerprint:
            raise ValueError("paper-shadow payload input identity drifted")
        if self.payload.get("does_not_submit_broker_order") is not True:
            raise ValueError("paper-shadow run must deny broker submission")
        if self.payload.get("does_not_mutate_production_ledger") is not True:
            raise ValueError("paper-shadow run must deny production-ledger writes")

    @property
    def simulated_order_count(self) -> int:
        return len(self.orders)

    @property
    def simulated_fill_count(self) -> int:
        return len(self.fills)

    def identity_payload(self) -> JsonObject:
        return {
            "run_id": self.run_id,
            "plan_date": self.plan_date,
            "input_fingerprint": self.input_fingerprint,
            "status": self.status,
            "order_intent_count": self.order_intent_count,
            "divergence_status": self.divergence_status,
            "next_manual_review_step": self.next_manual_review_step,
            "limitations": list(self.limitations),
            "payload": self.payload,
            "orders": [order.identity_payload() for order in self.orders],
            "fills": [fill.identity_payload() for fill in self.fills],
        }

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.identity_payload())


class PaperShadowRunPersistence(Protocol):
    """Minimal application-service port for paper-shadow run persistence."""

    def latest_paper_shadow_run_sync(
        self,
        *,
        plan_date: str | None = None,
    ) -> JsonObject | None: ...

    def record_paper_shadow_run_sync(
        self,
        command: PaperShadowRunCommand,
    ) -> JsonObject: ...


__all__ = [
    "PAPER_SHADOW_MODE",
    "PAPER_SHADOW_SOURCE",
    "PaperShadowFillFact",
    "PaperShadowOrderFact",
    "PaperShadowRunCommand",
    "PaperShadowRunPersistence",
]
