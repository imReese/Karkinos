"""Pre-trade risk gate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from core.event_bus import EventBus
from core.events import OrderEvent, OrderIntentEvent, RiskAlertEvent, RiskDecisionEvent
from core.types import ZERO, OrderSide, OrderType, Symbol
from domain.instrument import Instrument
from domain.position import Position


@dataclass(frozen=True)
class PreTradePolicy:
    """Configuration for pre-trade checks."""

    execution_mode: str = "manual"


@dataclass(frozen=True)
class PreTradeContext:
    """Point-in-time account and control state for pre-trade checks."""

    cash: Decimal
    total_equity: Decimal
    peak_equity: Decimal
    positions: dict[Symbol, Position]
    instruments: dict[Symbol, Instrument]
    blacklist: set[str]
    st_symbols: set[str]
    kill_switch_enabled: bool = False


class ContextProvider(Protocol):
    def snapshot(self) -> PreTradeContext:
        """Return the latest pre-trade context."""


class PreTradeRiskManager:
    """Mandatory gate from OrderIntentEvent to OrderEvent."""

    def __init__(
        self,
        event_bus: EventBus,
        context_provider: ContextProvider,
        policy: PreTradePolicy | None = None,
        db=None,
    ) -> None:
        self.event_bus = event_bus
        self.context_provider = context_provider
        self.policy = policy or PreTradePolicy()
        self.db = db
        event_bus.subscribe(OrderIntentEvent, self.on_intent, priority=-10)

    def on_intent(self, intent: OrderIntentEvent) -> None:
        """Validate intent, audit the decision, and publish the next event."""
        ctx = self.context_provider.snapshot()
        reasons = self._check(intent, ctx)
        passed = not reasons

        decision_id = f"RISK-{uuid.uuid4().hex[:10]}"
        order_id = f"ORD-{uuid.uuid4().hex[:10]}" if passed else None
        decision = RiskDecisionEvent(
            timestamp=intent.timestamp,
            decision_id=decision_id,
            intent_id=intent.intent_id,
            passed=passed,
            symbol=intent.symbol,
            side=intent.side,
            reasons=reasons or ["approved"],
            resulting_order_id=order_id,
            severity="info" if passed else "warning",
            metadata={
                "quantity": str(intent.quantity),
                "reference_price": str(intent.reference_price),
                "target_weight": str(intent.target_weight),
            },
        )

        if self.db is not None:
            self.db.save_risk_decision_sync(intent=intent, decision=decision)

        self.event_bus.publish(decision)

        if not passed:
            self.event_bus.publish(
                RiskAlertEvent(
                    timestamp=intent.timestamp,
                    alert_id=decision_id,
                    rule_name="pre_trade",
                    severity="warning",
                    message="; ".join(reasons),
                    symbol=intent.symbol,
                    order_id=None,
                )
            )
            return

        self.event_bus.publish(
            OrderEvent(
                timestamp=intent.timestamp,
                order_id=order_id or f"ORD-{uuid.uuid4().hex[:10]}",
                symbol=intent.symbol,
                side=intent.side,
                order_type=OrderType.MARKET,
                quantity=intent.quantity,
                price=intent.reference_price,
                intent_id=intent.intent_id,
                risk_decision_id=decision_id,
                execution_mode=self.policy.execution_mode,
            )
        )

    def _check(self, intent: OrderIntentEvent, ctx: PreTradeContext) -> list[str]:
        reasons: list[str] = []

        if intent.quantity <= ZERO:
            reasons.append("order quantity must be positive")
        if intent.reference_price <= ZERO:
            reasons.append("reference price must be positive")
        if intent.quantity * intent.reference_price <= ZERO:
            reasons.append("order value must be positive")

        symbol = str(intent.symbol)
        if symbol in ctx.blacklist:
            reasons.append(f"{symbol} is blacklisted")
        if symbol in ctx.st_symbols:
            reasons.append(f"{symbol} is marked as ST")

        if ctx.kill_switch_enabled and intent.side == OrderSide.BUY:
            reasons.append("kill switch is enabled: buy orders are blocked")

        return reasons
