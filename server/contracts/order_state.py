"""Typed commands and content identities for manual-ticket and OMS writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from server.contracts.content_identity import content_fingerprint

JsonObject = dict[str, Any]

OMS_INITIAL_STATUSES = frozenset(
    {
        "awaiting_manual_confirmation",
        "staged",
    }
)
OMS_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "awaiting_manual_confirmation": frozenset({"manually_confirmed", "cancelled"}),
    "manually_confirmed": frozenset(
        {
            "broker_submission_blocked",
            "manual_ticket_created",
            "cancelled",
        }
    ),
    "broker_submission_blocked": frozenset({"cancelled"}),
    "manual_ticket_created": frozenset({"cancelled"}),
    "staged": frozenset({"submitted", "cancelled", "expired"}),
    "submitted": frozenset({"accepted", "rejected", "cancelled", "expired"}),
    "accepted": frozenset(
        {
            "partially_filled",
            "filled",
            "rejected",
            "cancelled",
            "expired",
        }
    ),
    "partially_filled": frozenset(
        {"partially_filled", "filled", "cancelled", "expired"}
    ),
    "filled": frozenset({"reconciled"}),
    "rejected": frozenset({"reconciled"}),
    "cancelled": frozenset({"reconciled"}),
    "expired": frozenset({"reconciled"}),
    "reconciled": frozenset(),
}


def _required(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _decimal_identity(value: float | int | str | Decimal | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("order numeric value must be finite") from exc
    if not parsed.is_finite():
        raise ValueError("order numeric value must be finite")
    return format(parsed.normalize(), "f")


@dataclass(frozen=True, slots=True)
class ManualOrderTicketCommand:
    """Create manual/shared order projections from an action or risk gate."""

    idempotency_key: str
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
    action_id: int | None = None
    expected_action_status: str | None = None
    payload: JsonObject = field(default_factory=dict)
    execution_mode: str = "manual"
    status: str = "pending_confirm"
    source: str = "manual_action"
    source_ref: str | None = None

    def __post_init__(self) -> None:
        _required(self.idempotency_key, field_name="idempotency_key")
        _required(self.order_id, field_name="order_id")
        _required(self.timestamp, field_name="timestamp")
        _required(self.symbol, field_name="symbol")
        if str(self.side).lower() not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if str(self.order_type).lower() not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        quantity = _decimal_identity(self.quantity)
        if quantity is None or Decimal(quantity) <= 0:
            raise ValueError("quantity must be positive")
        price = _decimal_identity(self.price)
        if price is not None and Decimal(price) <= 0:
            raise ValueError("price must be positive when provided")
        if self.order_type.lower() == "limit" and price is None:
            raise ValueError("limit manual ticket requires a price")
        _required(self.asset_class, field_name="asset_class")
        _required(self.intent_id, field_name="intent_id")
        if self.execution_mode != "manual" or self.status != "pending_confirm":
            raise ValueError("manual ticket must start pending manual confirmation")
        action_fields = (self.action_id, self.expected_action_status)
        if any(value is not None for value in action_fields) and not all(
            value is not None for value in action_fields
        ):
            raise ValueError("manual ticket action fields must be provided together")
        if self.action_id is not None:
            if self.action_id <= 0:
                raise ValueError("action_id must be positive")
            _required(
                self.expected_action_status or "",
                field_name="expected_action_status",
            )
            if self.source != "manual_action":
                raise ValueError(
                    "action-bound manual ticket source must be manual_action"
                )
            if self.source_ref != str(self.action_id):
                raise ValueError(
                    "manual ticket source_ref must identify its action task"
                )
        else:
            if self.source != "risk_gate":
                raise ValueError("runtime manual ticket source must be risk_gate")
            risk_decision_id = _required(
                self.risk_decision_id or "",
                field_name="risk_decision_id",
            )
            if self.source_ref != risk_decision_id:
                raise ValueError(
                    "runtime manual ticket source_ref must identify its risk decision"
                )

    def identity_payload(self) -> JsonObject:
        """Return semantic input only; the server-generated timestamp is excluded."""

        return {
            "action_id": self.action_id,
            "expected_action_status": self.expected_action_status,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.lower(),
            "order_type": self.order_type.lower(),
            "quantity": _decimal_identity(self.quantity),
            "price": _decimal_identity(self.price),
            "asset_class": self.asset_class,
            "intent_id": self.intent_id,
            "risk_decision_id": self.risk_decision_id,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "source": self.source,
            "source_ref": self.source_ref,
            "payload": self.payload,
        }

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.identity_payload())


@dataclass(frozen=True, slots=True)
class ManualOrderStateCommand:
    """Move all manual-order projections through one compare-and-set edge."""

    idempotency_key: str
    order_id: str
    expected_from: str
    to_status: str
    note: str = ""
    action_id: int | None = None
    expected_action_status: str | None = None
    action_to_status: str | None = None

    def __post_init__(self) -> None:
        _required(self.idempotency_key, field_name="idempotency_key")
        _required(self.order_id, field_name="order_id")
        _required(self.expected_from, field_name="expected_from")
        _required(self.to_status, field_name="to_status")
        action_fields = (
            self.action_id,
            self.expected_action_status,
            self.action_to_status,
        )
        if any(value is not None for value in action_fields) and not all(
            value is not None for value in action_fields
        ):
            raise ValueError("manual order action CAS fields must be provided together")
        if self.action_id is not None and self.action_id <= 0:
            raise ValueError("action_id must be positive")
        if self.expected_from != "pending_confirm" or self.to_status not in {
            "confirmed",
            "rejected",
        }:
            raise ValueError(
                "manual order transition must confirm or reject pending confirmation"
            )
        if self.to_status == "confirmed" and self.action_id is None:
            raise ValueError("manual confirmation requires its action task CAS")
        if self.action_id is not None:
            expected_action_to = {
                "confirmed": "acted",
                "rejected": "ignored",
            }[self.to_status]
            if self.expected_action_status != "pending_manual_confirmation":
                raise ValueError("manual order action must await manual confirmation")
            if self.action_to_status != expected_action_to:
                raise ValueError(
                    "manual order action target does not match order disposition"
                )

    def identity_payload(self) -> JsonObject:
        return {
            "order_id": self.order_id,
            "expected_from": self.expected_from,
            "to_status": self.to_status,
            "note": self.note,
            "action_id": self.action_id,
            "expected_action_status": self.expected_action_status,
            "action_to_status": self.action_to_status,
        }

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.identity_payload())


@dataclass(frozen=True, slots=True)
class OmsOrderCommand:
    """Create one immutable OMS intent and its initial transition."""

    idempotency_key: str
    order_id: str
    symbol: str
    side: str
    asset_class: str
    quantity: float
    order_type: str
    limit_price: float | None
    initial_status: str
    broker_submission_enabled: bool
    source: str
    source_ref: str | None
    payload: JsonObject = field(default_factory=dict)
    transition_reason: str = "created from order intent"
    transition_actor: str | None = "system"
    transition_payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.idempotency_key, field_name="idempotency_key")
        _required(self.order_id, field_name="order_id")
        _required(self.symbol, field_name="symbol")
        _required(self.asset_class, field_name="asset_class")
        _required(self.initial_status, field_name="initial_status")
        _required(self.source, field_name="source")
        if str(self.side).lower() not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if str(self.order_type).lower() not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        quantity = _decimal_identity(self.quantity)
        if quantity is None or Decimal(quantity) <= 0:
            raise ValueError("quantity must be positive")
        limit_price = _decimal_identity(self.limit_price)
        if limit_price is not None and Decimal(limit_price) <= 0:
            raise ValueError("limit_price must be positive when provided")
        if self.order_type.lower() == "limit" and limit_price is None:
            raise ValueError("limit OMS order requires a price")
        if self.initial_status not in OMS_INITIAL_STATUSES:
            raise ValueError("OMS order must start at a non-authorizing initial status")
        if self.broker_submission_enabled:
            raise ValueError("OMS order creation cannot enable broker submission")

    def identity_payload(self) -> JsonObject:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.lower(),
            "asset_class": self.asset_class,
            "quantity": _decimal_identity(self.quantity),
            "order_type": self.order_type.lower(),
            "limit_price": _decimal_identity(self.limit_price),
            "initial_status": self.initial_status,
            "broker_submission_enabled": self.broker_submission_enabled,
            "source": self.source,
            "source_ref": self.source_ref,
            "payload": self.payload,
            "transition_reason": self.transition_reason,
            "transition_actor": self.transition_actor,
            "transition_payload": self.transition_payload,
        }

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.identity_payload())


@dataclass(frozen=True, slots=True)
class OmsTransitionCommand:
    """Compare-and-set one OMS lifecycle transition."""

    idempotency_key: str
    order_id: str
    expected_from: str
    to_status: str
    reason: str
    actor: str | None = None
    payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.idempotency_key, field_name="idempotency_key")
        _required(self.order_id, field_name="order_id")
        _required(self.expected_from, field_name="expected_from")
        _required(self.to_status, field_name="to_status")
        _required(self.reason, field_name="reason")
        allowed = OMS_ALLOWED_TRANSITIONS.get(self.expected_from, frozenset())
        if self.to_status not in allowed:
            raise ValueError(
                f"invalid OMS transition: {self.expected_from} -> {self.to_status}"
            )
        if self.to_status == "manually_confirmed":
            _required(str(self.actor or ""), field_name="actor")

    def identity_payload(self) -> JsonObject:
        return {
            "order_id": self.order_id,
            "expected_from": self.expected_from,
            "to_status": self.to_status,
            "reason": self.reason,
            "actor": self.actor,
            "payload": self.payload,
        }

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.identity_payload())


def command_identity(
    *,
    command_type: str,
    idempotency_key: str,
    fingerprint: str,
) -> JsonObject:
    return {
        "command_type": command_type,
        "idempotency_key": idempotency_key,
        "fingerprint": fingerprint,
    }


__all__ = [
    "ManualOrderStateCommand",
    "ManualOrderTicketCommand",
    "OMS_ALLOWED_TRANSITIONS",
    "OMS_INITIAL_STATUSES",
    "OmsOrderCommand",
    "OmsTransitionCommand",
    "command_identity",
]
