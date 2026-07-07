"""Production-facing OMS lifecycle foundation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

OMS_SCHEMA_VERSION = "karkinos.oms_order.v1"
INITIAL_STATUS = "awaiting_manual_confirmation"
PAPER_SHADOW_INITIAL_STATUS = "staged"
PAPER_SHADOW_EXECUTION_MODE = "paper_shadow"
PAPER_SHADOW_SOURCE = "paper_shadow_daily"

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "awaiting_manual_confirmation": {"manually_confirmed", "cancelled"},
    "manually_confirmed": {
        "broker_submission_blocked",
        "manual_ticket_created",
        "cancelled",
    },
    "broker_submission_blocked": {"cancelled"},
    "manual_ticket_created": {"cancelled"},
    "staged": {"submitted", "cancelled", "expired"},
    "submitted": {"accepted", "rejected", "cancelled", "expired"},
    "accepted": {
        "partially_filled",
        "filled",
        "rejected",
        "cancelled",
        "expired",
    },
    "partially_filled": {
        "partially_filled",
        "filled",
        "cancelled",
        "expired",
    },
    "filled": {"reconciled"},
    "rejected": {"reconciled"},
    "cancelled": {"reconciled"},
    "expired": {"reconciled"},
    "reconciled": set(),
}


class OmsService:
    """Manage order facts before any broker submission boundary."""

    def __init__(self, *, db: Any) -> None:
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
    ) -> dict[str, Any]:
        existing = self._db.get_oms_order_by_intent_key_sync(intent_key)
        if existing is not None:
            return self._normalize_order(existing)
        self._validate_order_inputs(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
        )
        order = self._db.upsert_oms_order_sync(
            {
                "order_id": _order_id(intent_key),
                "intent_key": intent_key,
                "symbol": symbol,
                "side": side.lower(),
                "asset_class": asset_class,
                "quantity": quantity,
                "order_type": order_type.lower(),
                "limit_price": limit_price,
                "status": INITIAL_STATUS,
                "broker_submission_enabled": False,
                "source": source,
                "source_ref": source_ref,
                "payload": {
                    "schema_version": OMS_SCHEMA_VERSION,
                    "manual_confirmation_required": True,
                    "does_not_submit_broker_order": True,
                },
            }
        )
        self._db.record_oms_transition_sync(
            order_id=order["order_id"],
            from_status="created",
            to_status=INITIAL_STATUS,
            reason="created from order intent",
            actor="system",
            payload={"intent_key": intent_key},
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
        existing = self._db.get_oms_order_by_intent_key_sync(intent_key)
        if existing is not None:
            return self._normalize_order(existing)
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
        order = self._db.upsert_oms_order_sync(
            {
                "order_id": order_id or _order_id(f"paper-shadow:{intent_key}"),
                "intent_key": intent_key,
                "symbol": symbol,
                "side": side.lower(),
                "asset_class": asset_class,
                "quantity": quantity,
                "order_type": order_type.lower(),
                "limit_price": limit_price,
                "status": PAPER_SHADOW_INITIAL_STATUS,
                "broker_submission_enabled": False,
                "source": source,
                "source_ref": run_id,
                "payload": payload,
            }
        )
        self._db.record_oms_transition_sync(
            order_id=order["order_id"],
            from_status="created",
            to_status=PAPER_SHADOW_INITIAL_STATUS,
            reason="created from paper/shadow order intent",
            actor="system",
            payload={
                **payload,
                "intent_key": intent_key,
                "source": source,
            },
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
    ) -> dict[str, Any]:
        order = self._db.get_oms_order_sync(order_id)
        if order is None:
            raise KeyError(f"OMS order not found: {order_id}")
        order = self._normalize_order(order)
        from_status = str(order["status"])
        to_status = str(to_status).lower()
        if to_status == from_status:
            return order
        if (
            to_status == "submitted"
            and not order["broker_submission_enabled"]
            and not _is_paper_shadow_order(order)
        ):
            raise ValueError("broker submission is disabled")
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ValueError(f"invalid OMS transition: {from_status} -> {to_status}")
        updated = self._db.update_oms_order_status_sync(
            order_id=order_id,
            status=to_status,
        )
        self._db.record_oms_transition_sync(
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
            payload=_transition_payload(
                order,
                source=source,
                evidence=evidence,
            ),
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
