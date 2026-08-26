"""Production-facing OMS lifecycle foundation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from server.contracts.content_identity import content_fingerprint
from server.contracts.order_state import (
    OMS_ALLOWED_TRANSITIONS,
    OmsOrderCommand,
    OmsTransitionCommand,
)

OMS_SCHEMA_VERSION = "karkinos.oms_order.v1"
INITIAL_STATUS = "awaiting_manual_confirmation"
PAPER_SHADOW_INITIAL_STATUS = "staged"
PAPER_SHADOW_EXECUTION_MODE = "paper_shadow"
PAPER_SHADOW_SOURCE = "paper_shadow_daily"


class OmsPersistence(Protocol):
    def create_oms_order_sync(self, command: OmsOrderCommand) -> dict[str, Any]: ...

    def transition_oms_order_sync(
        self,
        command: OmsTransitionCommand,
    ) -> dict[str, Any]: ...

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None: ...

    def list_oms_transitions_sync(self, order_id: str) -> list[dict[str, Any]]: ...


class OmsService:
    """Manage order facts before any broker submission boundary."""

    def __init__(self, *, db: OmsPersistence) -> None:
        self._db = db

    def create_order_intent(
        self,
        *,
        intent_key: str,
        symbol: str,
        side: str,
        asset_class: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
        source: str,
        source_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_order_inputs(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
        )
        order = self._db.create_oms_order_sync(
            OmsOrderCommand(
                idempotency_key=intent_key,
                order_id=_order_id(intent_key),
                symbol=symbol,
                side=side,
                asset_class=asset_class,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                initial_status=INITIAL_STATUS,
                broker_submission_enabled=False,
                source=source,
                source_ref=source_ref,
                payload={
                    **dict(payload or {}),
                    "schema_version": OMS_SCHEMA_VERSION,
                    "manual_confirmation_required": True,
                    "does_not_submit_broker_order": True,
                },
                transition_payload={"intent_key": intent_key},
            )
        )
        return self._normalize_order(order)

    def create_paper_shadow_order(
        self,
        *,
        intent_key: str,
        order_id: str | None = None,
        run_id: str,
        symbol: str,
        side: str,
        asset_class: str,
        quantity: float,
        order_type: str,
        limit_price: float | None,
        source_ref: str | None = None,
        evidence_refs: list[str] | None = None,
        source: str = PAPER_SHADOW_SOURCE,
    ) -> dict[str, Any]:
        self._validate_order_inputs(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
        )
        payload = {
            "schema_version": OMS_SCHEMA_VERSION,
            "execution_mode": PAPER_SHADOW_EXECUTION_MODE,
            "run_id": run_id,
            "source_ref": source_ref,
            "evidence_refs": [str(item) for item in evidence_refs or []],
            "manual_confirmation_required": False,
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
        order = self._db.create_oms_order_sync(
            OmsOrderCommand(
                idempotency_key=intent_key,
                order_id=order_id or _order_id(f"paper-shadow:{intent_key}"),
                symbol=symbol,
                side=side,
                asset_class=asset_class,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                initial_status=PAPER_SHADOW_INITIAL_STATUS,
                broker_submission_enabled=False,
                source=source,
                source_ref=run_id,
                payload=payload,
                transition_reason="created from paper/shadow order intent",
                transition_payload={
                    **payload,
                    "intent_key": intent_key,
                    "source": source,
                },
            )
        )
        return self._normalize_order(order)

    def transition_order(
        self,
        order_id: str,
        *,
        to_status: str,
        reason: str,
        actor: str | None = None,
        source: str | None = None,
        evidence: dict[str, Any] | None = None,
        expected_from: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        order = self._db.get_oms_order_sync(order_id)
        if order is None:
            raise KeyError(f"OMS order not found: {order_id}")
        order = self._normalize_order(order)
        current_status = str(order["status"])
        from_status = str(expected_from or current_status).lower()
        to_status = str(to_status).lower()
        if to_status == current_status and idempotency_key is None:
            return order
        if (
            to_status == "submitted"
            and not order["broker_submission_enabled"]
            and not _is_paper_shadow_order(order)
        ):
            raise ValueError("broker submission is disabled")
        allowed = OMS_ALLOWED_TRANSITIONS.get(from_status, frozenset())
        if to_status not in allowed:
            raise ValueError(f"invalid OMS transition: {from_status} -> {to_status}")
        transition_payload = _transition_payload(
            order,
            source=source,
            evidence=evidence,
        )
        command_key = idempotency_key or _transition_idempotency_key(
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
            payload=transition_payload,
        )
        updated = self._db.transition_oms_order_sync(
            OmsTransitionCommand(
                idempotency_key=command_key,
                order_id=order_id,
                expected_from=from_status,
                to_status=to_status,
                reason=reason,
                actor=actor,
                payload=transition_payload,
            )
        )
        return self._normalize_order(updated)

    def list_transitions(self, order_id: str) -> list[dict[str, Any]]:
        return self._db.list_oms_transitions_sync(order_id)

    def _normalize_order(self, order: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(order)
        normalized["broker_submission_enabled"] = bool(
            normalized.get("broker_submission_enabled")
        )
        normalized["payload"] = _payload(normalized)
        return normalized

    def _validate_order_inputs(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
    ) -> None:
        if not str(symbol).strip():
            raise ValueError("symbol is required")
        if str(side).lower() not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if float(quantity) <= 0:
            raise ValueError("quantity must be positive")
        if str(order_type).lower() not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")


def _order_id(intent_key: str) -> str:
    digest = hashlib.sha256(intent_key.encode("utf-8")).hexdigest()[:16]
    return f"OMS-{digest}"


def _payload(order: dict[str, Any]) -> dict[str, Any]:
    value = order.get("payload")
    if isinstance(value, dict):
        return value
    raw = order.get("payload_json")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_paper_shadow_order(order: dict[str, Any]) -> bool:
    return str(_payload(order).get("execution_mode") or "").lower() == (
        PAPER_SHADOW_EXECUTION_MODE
    )


def _transition_payload(
    order: dict[str, Any],
    *,
    source: str | None,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    order_payload = _payload(order)
    payload: dict[str, Any] = {
        "broker_submission_enabled": bool(order["broker_submission_enabled"]),
    }
    for key in (
        "execution_mode",
        "run_id",
        "does_not_submit_broker_order",
        "does_not_mutate_production_ledger",
    ):
        if key in order_payload:
            payload[key] = order_payload[key]
    if source is not None:
        payload["source"] = source
    if evidence:
        payload.update(evidence)
    return payload


def _transition_idempotency_key(
    *,
    order_id: str,
    from_status: str,
    to_status: str,
    reason: str,
    actor: str | None,
    payload: dict[str, Any],
) -> str:
    fingerprint = content_fingerprint(
        {
            "reason": reason,
            "actor": actor,
            "payload": payload,
        }
    )
    return f"oms-transition:{order_id}:{from_status}:{to_status}:{fingerprint}"
