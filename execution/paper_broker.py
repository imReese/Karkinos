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

        status = (
            PaperOrderStatus.FILLED
            if quantity == request.quantity
            else PaperOrderStatus.PARTIALLY_FILLED
        )
        status_history = (
            PaperOrderStatus.STAGED,
            PaperOrderStatus.SUBMITTED,
            PaperOrderStatus.ACCEPTED,
            status,
        )
        order = PaperOrderEvidence(
            order_id=request.order_id,
            timestamp=request.timestamp,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            asset_class=request.asset_class,
            status=status,
            filled_quantity=quantity,
            remaining_quantity=request.quantity - quantity,
            status_history=status_history,
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
            provider_name=self.provider_name,
        )

        self._record_order(order)
        self._record_fill(fill)
        return PaperBrokerResult(order=order, fill=fill)

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
