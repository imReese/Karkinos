"""Pre-trade risk gate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
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
    max_order_notional: Decimal | None = None
    min_cash_reserve: Decimal = ZERO
    max_position_weight: Decimal | None = None


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
    data_quality_issues: dict[Symbol, list[str]] = field(default_factory=dict)


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
        risk_inputs = self._risk_inputs(intent, ctx)
        reasons = self._check(intent, ctx, risk_inputs)
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
                **risk_inputs,
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

    def _check(
        self,
        intent: OrderIntentEvent,
        ctx: PreTradeContext,
        risk_inputs: dict,
    ) -> list[str]:
        reasons: list[str] = []
        order_value = Decimal(risk_inputs["order_value"])

        if intent.quantity <= ZERO:
            reasons.append("order quantity must be positive")
        if intent.reference_price <= ZERO:
            reasons.append("reference price must be positive")
        if order_value <= ZERO:
            reasons.append("order value must be positive")

        symbol = str(intent.symbol)
        if symbol in ctx.blacklist:
            reasons.append(f"{symbol} is blacklisted")
        if symbol in ctx.st_symbols:
            reasons.append(f"{symbol} is marked as ST")

        if ctx.kill_switch_enabled and intent.side == OrderSide.BUY:
            reasons.append("kill switch is enabled: buy orders are blocked")

        if (
            self.policy.max_order_notional is not None
            and order_value > self.policy.max_order_notional
        ):
            reasons.append("order notional exceeds max_order_notional")

        if (
            intent.side == OrderSide.BUY
            and Decimal(risk_inputs["projected_cash"]) < self.policy.min_cash_reserve
        ):
            reasons.append("cash reserve would fall below min_cash_reserve")

        if (
            self.policy.max_position_weight is not None
            and Decimal(risk_inputs["projected_position_weight"])
            > self.policy.max_position_weight
        ):
            reasons.append("projected position weight exceeds max_position_weight")

        for issue in ctx.data_quality_issues.get(intent.symbol, []):
            reasons.append(f"data quality issue: {issue}")

        for issue in intent.metadata.get("data_quality_issues", []):
            reasons.append(f"data quality issue: {issue}")

        return reasons

    def _risk_inputs(self, intent: OrderIntentEvent, ctx: PreTradeContext) -> dict:
        order_value = intent.quantity * intent.reference_price
        current_position_value = _position_market_value(
            ctx.positions.get(intent.symbol)
        )
        if intent.side == OrderSide.BUY:
            projected_cash = ctx.cash - order_value
            projected_position_value = current_position_value + order_value
        else:
            projected_cash = ctx.cash
            projected_position_value = max(ZERO, current_position_value - order_value)

        if ctx.total_equity > ZERO:
            projected_position_weight = projected_position_value / ctx.total_equity
        else:
            projected_position_weight = ZERO

        return {
            "cash": str(ctx.cash),
            "total_equity": str(ctx.total_equity),
            "order_value": str(order_value),
            "projected_cash": str(projected_cash),
            "current_position_value": str(current_position_value),
            "projected_position_value": str(projected_position_value),
            "projected_position_weight": str(projected_position_weight),
            "policy": _policy_metadata(self.policy),
        }


def _position_market_value(position: Position | None) -> Decimal:
    if position is None:
        return ZERO
    return Decimal(str(getattr(position, "market_value", ZERO)))


def _policy_metadata(policy: PreTradePolicy) -> dict[str, str | None]:
    return {
        "execution_mode": policy.execution_mode,
        "max_order_notional": (
            str(policy.max_order_notional)
            if policy.max_order_notional is not None
            else None
        ),
        "min_cash_reserve": str(policy.min_cash_reserve),
        "max_position_weight": (
            str(policy.max_position_weight)
            if policy.max_position_weight is not None
            else None
        ),
    }
