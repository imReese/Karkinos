"""Paper broker evidence primitives for simulation and review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from core.types import AssetClass, OrderSide, OrderType, Symbol
from execution.commission import CommissionCalculator, StockACommission

PAPER_BROKER_SCHEMA_VERSION = "karkinos.paper_broker.v1"


class PaperOrderStatus(Enum):
    """OMS states for paper-only order evidence."""

    STAGED = "staged"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    RECONCILED = "reconciled"


class PaperOmsInvalidTransitionError(ValueError):
    """Raised when a paper order attempts an invalid OMS transition."""

    def __init__(
        self,
        *,
        order_id: str,
        from_status: PaperOrderStatus,
        to_status: PaperOrderStatus,
    ) -> None:
        super().__init__(
            "Invalid paper OMS transition for "
            f"{order_id}: {from_status.value} -> {to_status.value}"
        )
        self.order_id = order_id
        self.from_status = from_status
        self.to_status = to_status


@dataclass(frozen=True)
class PaperOmsTransition:
    """One deterministic state transition in a paper OMS history."""

    order_id: str
    sequence: int
    from_status: PaperOrderStatus | None
    to_status: PaperOrderStatus
    filled_quantity: Decimal = Decimal("0")
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "sequence": self.sequence,
            "from_status": (
                self.from_status.value if self.from_status is not None else None
            ),
            "to_status": self.to_status.value,
            "filled_quantity": str(self.filled_quantity),
            "reason": self.reason,
        }


class PaperOmsStateMachine:
    """Deterministic OMS state machine for paper-only order evidence."""

    _ALLOWED_TRANSITIONS: dict[PaperOrderStatus, frozenset[PaperOrderStatus]] = {
        PaperOrderStatus.STAGED: frozenset(
            {
                PaperOrderStatus.SUBMITTED,
                PaperOrderStatus.CANCELLED,
                PaperOrderStatus.EXPIRED,
            }
        ),
        PaperOrderStatus.SUBMITTED: frozenset(
            {
                PaperOrderStatus.ACCEPTED,
                PaperOrderStatus.REJECTED,
                PaperOrderStatus.CANCELLED,
                PaperOrderStatus.EXPIRED,
            }
        ),
        PaperOrderStatus.ACCEPTED: frozenset(
            {
                PaperOrderStatus.PARTIALLY_FILLED,
                PaperOrderStatus.FILLED,
                PaperOrderStatus.REJECTED,
                PaperOrderStatus.CANCELLED,
                PaperOrderStatus.EXPIRED,
            }
        ),
        PaperOrderStatus.PARTIALLY_FILLED: frozenset(
            {
                PaperOrderStatus.PARTIALLY_FILLED,
                PaperOrderStatus.FILLED,
                PaperOrderStatus.CANCELLED,
                PaperOrderStatus.EXPIRED,
            }
        ),
        PaperOrderStatus.FILLED: frozenset({PaperOrderStatus.RECONCILED}),
        PaperOrderStatus.REJECTED: frozenset({PaperOrderStatus.RECONCILED}),
        PaperOrderStatus.CANCELLED: frozenset({PaperOrderStatus.RECONCILED}),
        PaperOrderStatus.EXPIRED: frozenset({PaperOrderStatus.RECONCILED}),
        PaperOrderStatus.RECONCILED: frozenset(),
    }

    def __init__(self, *, order_id: str) -> None:
        self.order_id = order_id
        self.filled_quantity = Decimal("0")
        self._transitions: list[PaperOmsTransition] = [
            PaperOmsTransition(
                order_id=order_id,
                sequence=1,
                from_status=None,
                to_status=PaperOrderStatus.STAGED,
            )
        ]

    @property
    def current_status(self) -> PaperOrderStatus:
        return self._transitions[-1].to_status

    @property
    def transitions(self) -> tuple[PaperOmsTransition, ...]:
        return tuple(self._transitions)

    @property
    def status_history(self) -> tuple[PaperOrderStatus, ...]:
        return tuple(transition.to_status for transition in self._transitions)

    def mark_submitted(self, reason: str = "") -> PaperOmsTransition:
        return self._transition(PaperOrderStatus.SUBMITTED, reason=reason)

    def mark_accepted(self, reason: str = "") -> PaperOmsTransition:
        return self._transition(PaperOrderStatus.ACCEPTED, reason=reason)

    def mark_partially_filled(
        self,
        *,
        filled_quantity: Decimal,
        reason: str = "",
    ) -> PaperOmsTransition:
        return self._transition(
            PaperOrderStatus.PARTIALLY_FILLED,
            filled_quantity=filled_quantity,
            reason=reason,
        )

    def mark_filled(
        self,
        *,
        filled_quantity: Decimal,
        reason: str = "",
    ) -> PaperOmsTransition:
        return self._transition(
            PaperOrderStatus.FILLED,
            filled_quantity=filled_quantity,
            reason=reason,
        )

    def mark_rejected(self, reason: str = "") -> PaperOmsTransition:
        return self._transition(PaperOrderStatus.REJECTED, reason=reason)

    def mark_cancelled(self, reason: str = "") -> PaperOmsTransition:
        return self._transition(PaperOrderStatus.CANCELLED, reason=reason)

    def mark_expired(self, reason: str = "") -> PaperOmsTransition:
        return self._transition(PaperOrderStatus.EXPIRED, reason=reason)

    def mark_reconciled(self, reason: str = "") -> PaperOmsTransition:
        return self._transition(PaperOrderStatus.RECONCILED, reason=reason)

    def _transition(
        self,
        to_status: PaperOrderStatus,
        *,
        filled_quantity: Decimal | None = None,
        reason: str = "",
    ) -> PaperOmsTransition:
        if self.current_status is to_status:
            return self._transitions[-1]

        if to_status not in self._ALLOWED_TRANSITIONS[self.current_status]:
            raise PaperOmsInvalidTransitionError(
                order_id=self.order_id,
                from_status=self.current_status,
                to_status=to_status,
            )

        if filled_quantity is not None:
            if filled_quantity < self.filled_quantity:
                raise ValueError("Paper filled quantity cannot decrease.")
            self.filled_quantity = filled_quantity

        transition = PaperOmsTransition(
            order_id=self.order_id,
            sequence=len(self._transitions) + 1,
            from_status=self.current_status,
            to_status=to_status,
            filled_quantity=self.filled_quantity,
            reason=reason,
        )
        self._transitions.append(transition)
        return transition


@dataclass(frozen=True)
class PaperOrderContext:
    """Optional evidence references attached to a paper order."""

    strategy_id: str | None = None
    signal_id: str | None = None
    risk_decision_id: str | None = None
    dataset_id: str | None = None
    cost_model_id: str | None = None
    account_truth_version: str | None = None

    def to_payload(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "strategy_id": self.strategy_id,
                "signal_id": self.signal_id,
                "risk_decision_id": self.risk_decision_id,
                "dataset_id": self.dataset_id,
                "cost_model_id": self.cost_model_id,
                "account_truth_version": self.account_truth_version,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class PaperOrderRequest:
    """Paper-only order request accepted by the local paper broker."""

    timestamp: datetime
    order_id: str
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    asset_class: AssetClass = AssetClass.STOCK
    context: PaperOrderContext = PaperOrderContext()


@dataclass(frozen=True)
class PaperOrderEvidence:
    """Persistable paper order evidence, separated from production ledger."""

    order_id: str
    timestamp: datetime
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None
    asset_class: AssetClass
    status: PaperOrderStatus
    filled_quantity: Decimal
    remaining_quantity: Decimal
    status_history: tuple[PaperOrderStatus, ...]
    oms_transitions: tuple[PaperOmsTransition, ...]
    context: PaperOrderContext
    schema_version: str = PAPER_BROKER_SCHEMA_VERSION
    execution_mode: str = "paper"
    source: str = "paper_broker"
    does_not_mutate_production_ledger: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "order_id": self.order_id,
            "symbol": str(self.symbol),
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": str(self.quantity),
            "price": str(self.price) if self.price is not None else None,
            "asset_class": self.asset_class.value,
            "status": self.status.value,
            "filled_quantity": str(self.filled_quantity),
            "remaining_quantity": str(self.remaining_quantity),
            "status_history": [status.value for status in self.status_history],
            "oms_transitions": [
                transition.to_payload() for transition in self.oms_transitions
            ],
            "context": self.context.to_payload(),
            "execution_mode": self.execution_mode,
            "source": self.source,
            "does_not_mutate_production_ledger": (
                self.does_not_mutate_production_ledger
            ),
        }


@dataclass(frozen=True)
class PaperFillEvidence:
    """Persistable paper fill evidence, separated from production ledger."""

    fill_id: str
    order_id: str
    timestamp: datetime
    symbol: Symbol
    side: OrderSide
    fill_price: Decimal
    fill_quantity: Decimal
    commission: Decimal
    slippage: Decimal
    asset_class: AssetClass
    context: PaperOrderContext
    reference_price: Decimal | None = None
    schema_version: str = PAPER_BROKER_SCHEMA_VERSION
    execution_mode: str = "paper"
    provider_name: str = "simulated"
    source: str = "paper_broker"
    does_not_mutate_production_ledger: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "symbol": str(self.symbol),
            "side": self.side.value,
            "fill_price": str(self.fill_price),
            "fill_quantity": str(self.fill_quantity),
            "commission": str(self.commission),
            "slippage": str(self.slippage),
            "asset_class": self.asset_class.value,
            "cost_modeling": {
                "model_id": self.context.cost_model_id or "default_commission_model",
                "total_fee_tax_cost": str(self.commission),
                "slippage_cost": str(self.slippage),
                "commission_field_includes_fees_and_taxes": True,
                "reference_price": (
                    str(self.reference_price)
                    if self.reference_price is not None
                    else None
                ),
            },
            "context": self.context.to_payload(),
            "execution_mode": self.execution_mode,
            "provider_name": self.provider_name,
            "source": self.source,
            "does_not_mutate_production_ledger": (
                self.does_not_mutate_production_ledger
            ),
        }


@dataclass(frozen=True)
class PaperBrokerResult:
    """Result of one paper broker order simulation."""

    order: PaperOrderEvidence
    fill: PaperFillEvidence | None = None


class PaperBroker:
    """Local paper broker that stores simulation evidence only."""

    SOURCE = "paper_broker"

    def __init__(
        self,
        *,
        db=None,
        provider_name: str = "simulated",
        commission_calc: CommissionCalculator | None = None,
    ) -> None:
        self.db = db
        self.provider_name = provider_name
        self.commission_calc = commission_calc or StockACommission()

    def submit_order(
        self,
        request: PaperOrderRequest,
        *,
        fill_id: str | None = None,
        fill_quantity: Decimal | None = None,
        fill_price: Decimal | None = None,
    ) -> PaperBrokerResult:
        """Simulate one paper order and persist order/fill evidence."""
        quantity = fill_quantity if fill_quantity is not None else request.quantity
        if quantity <= Decimal("0"):
            raise ValueError("Paper fill quantity must be positive.")
        if quantity > request.quantity:
            raise ValueError("Paper fill quantity cannot exceed order quantity.")

        effective_price = fill_price if fill_price is not None else request.price
        if effective_price is None:
            raise ValueError("Paper fill price is required when order price is absent.")

        oms = PaperOmsStateMachine(order_id=request.order_id)
        oms.mark_submitted()
        oms.mark_accepted()
        if quantity == request.quantity:
            oms.mark_filled(filled_quantity=quantity)
        else:
            oms.mark_partially_filled(filled_quantity=quantity)
        order = PaperOrderEvidence(
            order_id=request.order_id,
            timestamp=request.timestamp,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            asset_class=request.asset_class,
            status=oms.current_status,
            filled_quantity=oms.filled_quantity,
            remaining_quantity=request.quantity - quantity,
            status_history=oms.status_history,
            oms_transitions=oms.transitions,
            context=request.context,
        )
        fill = PaperFillEvidence(
            fill_id=fill_id or f"{request.order_id}-FILL-1",
            order_id=request.order_id,
            timestamp=request.timestamp,
            symbol=request.symbol,
            side=request.side,
            fill_price=effective_price,
            fill_quantity=quantity,
            commission=self.commission_calc.calculate(
                request.side,
                effective_price,
                quantity,
            ),
            slippage=_calculate_slippage(
                reference_price=request.price,
                fill_price=effective_price,
                quantity=quantity,
            ),
            asset_class=request.asset_class,
            context=request.context,
            reference_price=request.price,
            provider_name=self.provider_name,
        )

        self._record_order(order)
        self._record_fill(fill)
        return PaperBrokerResult(order=order, fill=fill)

    def cancel_order(
        self,
        request: PaperOrderRequest,
        *,
        reason: str = "",
    ) -> PaperBrokerResult:
        """Persist paper-only cancellation evidence without creating fills."""
        oms = PaperOmsStateMachine(order_id=request.order_id)
        oms.mark_submitted()
        oms.mark_cancelled(reason=reason)
        order = self._build_terminal_order(request, oms)
        self._record_order(order)
        return PaperBrokerResult(order=order, fill=None)

    def reject_order(
        self,
        request: PaperOrderRequest,
        *,
        reason: str = "",
    ) -> PaperBrokerResult:
        """Persist paper-only rejection evidence without creating fills."""
        oms = PaperOmsStateMachine(order_id=request.order_id)
        oms.mark_submitted()
        oms.mark_accepted()
        oms.mark_rejected(reason=reason)
        order = self._build_terminal_order(request, oms)
        self._record_order(order)
        return PaperBrokerResult(order=order, fill=None)

    def _build_terminal_order(
        self,
        request: PaperOrderRequest,
        oms: PaperOmsStateMachine,
    ) -> PaperOrderEvidence:
        return PaperOrderEvidence(
            order_id=request.order_id,
            timestamp=request.timestamp,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            asset_class=request.asset_class,
            status=oms.current_status,
            filled_quantity=oms.filled_quantity,
            remaining_quantity=request.quantity - oms.filled_quantity,
            status_history=oms.status_history,
            oms_transitions=oms.transitions,
            context=request.context,
        )

    def _record_order(self, order: PaperOrderEvidence) -> None:
        if self.db is None or not hasattr(self.db, "record_order_sync"):
            return
        self.db.record_order_sync(
            order_id=order.order_id,
            timestamp=order.timestamp.isoformat(),
            symbol=str(order.symbol),
            side=order.side.value,
            order_type=order.order_type.value,
            quantity=float(order.quantity),
            price=float(order.price) if order.price is not None else None,
            asset_class=order.asset_class.value,
            intent_id=order.context.signal_id,
            risk_decision_id=order.context.risk_decision_id,
            execution_mode=order.execution_mode,
            status=order.status.value,
            source=order.source,
            source_ref=order.order_id,
            payload=order.to_payload(),
        )

    def _record_fill(self, fill: PaperFillEvidence) -> None:
        if self.db is None or not hasattr(self.db, "record_fill_sync"):
            return
        self.db.record_fill_sync(
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            timestamp=fill.timestamp.isoformat(),
            symbol=str(fill.symbol),
            side=fill.side.value,
            fill_price=float(fill.fill_price),
            fill_quantity=float(fill.fill_quantity),
            commission=float(fill.commission),
            slippage=float(fill.slippage),
            asset_class=fill.asset_class.value,
            execution_mode=fill.execution_mode,
            provider_name=fill.provider_name,
            broker_order_id=fill.order_id,
            source=fill.source,
            source_ref=fill.fill_id,
            metadata=fill.to_payload(),
        )


def _calculate_slippage(
    *,
    reference_price: Decimal | None,
    fill_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if reference_price is None:
        return Decimal("0")
    return abs(fill_price - reference_price) * quantity
