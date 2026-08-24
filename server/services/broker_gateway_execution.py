"""Manual execution evidence commands for the broker gateway boundary."""

from __future__ import annotations

from typing import Any

from server.contracts.broker_gateway import (
    BROKER_GATEWAY_SCHEMA_VERSION,
    MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCOPE,
)
from server.services.broker_gateway_values import (
    fingerprint_payload as _fingerprint_payload,
)
from server.services.broker_gateway_values import (
    manual_execution_ledger_draft as _manual_execution_ledger_draft,
)
from server.services.broker_gateway_values import (
    manual_execution_preview as _manual_execution_preview,
)
from server.services.broker_gateway_values import (
    position_cost_preview as _position_cost_preview,
)


class BrokerGatewayExecutionEvidenceMixin:
    """Preview and persist non-authorizing manual execution evidence."""

    def preview_manual_execution_record(
        self,
        order_id: str,
        *,
        fill_price: Any,
        quantity: Any,
        fee: Any = None,
        tax: Any = None,
        transfer_fee: Any = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order = self._require_order(order_id)
        if order["status"] != "manual_ticket_created":
            raise ValueError(
                "OMS order must be manual_ticket_created before manual execution preview"
            )
        gateway_evidence = self._require_gateway_evidence(order)
        execution_preview = _manual_execution_preview(
            order,
            fill_price=fill_price,
            quantity=quantity,
            fee=fee,
            tax=tax,
            transfer_fee=transfer_fee,
        )
        ledger_entry_draft = _manual_execution_ledger_draft(
            order,
            execution_preview=execution_preview,
        )
        position_cost_preview = _position_cost_preview(order)
        controlled_bridge_policy = self._controlled_bridge_policy_snapshot()
        validation = self._manual_execution_validation(
            order,
            gateway_evidence=gateway_evidence,
            controlled_bridge_policy=controlled_bridge_policy,
        )
        preview_fingerprint = _fingerprint_payload(
            {
                "schema_version": "karkinos.manual_execution_preview_fingerprint.v1",
                "order_id": order["order_id"],
                "execution_preview": execution_preview,
                "ledger_entry_draft": ledger_entry_draft,
                "position_cost_preview": position_cost_preview,
                "controlled_bridge_policy": controlled_bridge_policy,
                "current_per_order_confirmation": gateway_evidence[
                    "current_per_order_confirmation"
                ],
            }
        )
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "manual_execution_preview_ready",
            "dry_run": True,
            "submitted_to_broker": False,
            "does_not_mutate_production_ledger": True,
            "order_id": order["order_id"],
            "actor": actor,
            "preview_fingerprint": preview_fingerprint,
            "fingerprint_scope": MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCOPE,
            "execution_preview": execution_preview,
            "ledger_entry_draft": ledger_entry_draft,
            "position_cost_preview": position_cost_preview,
            "controlled_bridge_policy": controlled_bridge_policy,
            "validation": validation,
            "safety": {
                "broker_submission_enabled": False,
                "submitted_to_broker": False,
                "requires_human_broker_entry": True,
                "requires_operator_save": True,
                "does_not_mutate_oms": True,
                "does_not_mutate_production_ledger": True,
            },
            "limitations": [
                "This previews a manual execution record only.",
                "It does not submit to a broker, create gateway events, change OMS status, or write ledger entries.",
                "The operator must review broker-side fills and explicitly save any production ledger record.",
            ],
        }

    def record_manual_execution_evidence(
        self,
        order_id: str,
        *,
        preview_fingerprint: str,
        fill_price: Any,
        quantity: Any,
        fee: Any = None,
        tax: Any = None,
        transfer_fee: Any = None,
        actor: str | None = None,
        operator_note: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview_manual_execution_record(
            order_id,
            fill_price=fill_price,
            quantity=quantity,
            fee=fee,
            tax=tax,
            transfer_fee=transfer_fee,
            actor=actor,
        )
        expected_fingerprint = preview["preview_fingerprint"]
        if str(preview_fingerprint) != str(expected_fingerprint):
            raise ValueError(
                "preview_fingerprint does not match manual execution preview"
            )
        event_payload = {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "order_id": preview["order_id"],
            "preview_fingerprint": expected_fingerprint,
            "fingerprint_scope": preview["fingerprint_scope"],
            "execution_preview": preview["execution_preview"],
            "ledger_entry_draft": preview["ledger_entry_draft"],
            "position_cost_preview": preview["position_cost_preview"],
            "controlled_bridge_policy": preview["controlled_bridge_policy"],
            "validation": preview["validation"],
            "operator_note": operator_note,
            "submitted_to_broker": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "requires_operator_ledger_save": True,
        }
        event = self._db.record_broker_gateway_event_sync(
            gateway_id="manual_ticket",
            event_type="manual_execution_recorded",
            order_id=order_id,
            status="recorded",
            actor=actor,
            payload=event_payload,
        )
        return {
            **preview,
            "status": "manual_execution_recorded",
            "event_id": event["id"],
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "submitted_to_broker": False,
            "operator_note": operator_note,
            "limitations": [
                "This records manual execution evidence for audit only.",
                "It does not submit to a broker, create fills, change OMS status, or write ledger entries.",
                "The operator must explicitly save any production ledger record in a later reviewed workflow.",
            ],
        }

    def submit_live_disabled(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order = self._require_order(order_id)
        self._db.record_broker_gateway_event_sync(
            gateway_id="live_disabled",
            event_type="live_submission_rejected",
            order_id=order_id,
            status="rejected",
            actor=actor,
            payload={
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "order_status": order["status"],
                "submitted_to_broker": False,
            },
        )
        raise ValueError("live broker submission is disabled")

    def cancel_live_disabled(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order = self._require_order(order_id)
        self._db.record_broker_gateway_event_sync(
            gateway_id="live_disabled",
            event_type="live_cancel_rejected",
            order_id=order_id,
            status="rejected",
            actor=actor,
            payload={
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "order_status": order["status"],
                "submitted_to_broker": False,
                "cancelled_at_broker": False,
            },
        )
        raise ValueError("live broker cancellation is disabled")

    def _manual_execution_validation(
        self,
        order: dict[str, Any],
        *,
        gateway_evidence: dict[str, Any],
        controlled_bridge_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "manual_confirmation_status": "pass",
            "gateway_evidence_status": "pass",
            "gateway_evidence": gateway_evidence,
            "controlled_bridge_policy": controlled_bridge_policy,
            "broker_submission_enabled": bool(order["broker_submission_enabled"]),
            "requires_human_broker_entry": True,
            "required_gate_summary": self._required_gate_summary(
                order,
                gateway_evidence=gateway_evidence,
            ),
        }
