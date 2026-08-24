"""Human-reviewed manual-ticket commands for the broker gateway boundary."""

from __future__ import annotations

import json
from typing import Any

from server.contracts.broker_gateway import BROKER_GATEWAY_SCHEMA_VERSION
from server.services.broker_gateway_values import (
    REQUIRED_GATEWAY_EVIDENCE as _REQUIRED_GATEWAY_EVIDENCE,
)
from server.services.broker_gateway_values import (
    cash_impact_preview as _cash_impact_preview,
)
from server.services.broker_gateway_values import clean_number as _clean_number
from server.services.broker_gateway_values import (
    fee_tax_assumptions as _fee_tax_assumptions,
)
from server.services.broker_gateway_values import (
    operator_account_alias as _operator_account_alias,
)
from server.services.broker_gateway_values import (
    position_cost_preview as _position_cost_preview,
)
from server.services.broker_gateway_values import (
    trading_session_constraints as _trading_session_constraints,
)


class BrokerGatewayManualTicketMixin:
    """Preview, export, validate, and record manual broker tickets."""

    def preview_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order, evidence = self._require_gateway_ready_order(order_id)
        self._require_kill_switch_clear()
        return self._preview_payload(
            order,
            gateway_evidence=evidence,
            status="preview_ready",
            dry_run=True,
            actor=actor,
        )

    def export_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order, evidence = self._require_gateway_ready_order(order_id)
        self._require_kill_switch_clear()
        ticket = self._manual_ticket(order)
        policy_snapshot = self._controlled_bridge_policy_snapshot()
        required_gate_summary = self._required_gate_summary(
            order,
            gateway_evidence=evidence,
        )
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "export_ready",
            "dry_run": True,
            "submitted_to_broker": False,
            "order_id": order["order_id"],
            "actor": actor,
            "ticket": ticket,
            "export": self._manual_ticket_export(
                order,
                ticket=ticket,
                gateway_evidence=evidence,
                controlled_bridge_policy=policy_snapshot,
                actor=actor,
            ),
            "validation": {
                "manual_confirmation_status": "pass",
                "gateway_evidence_status": "pass",
                "gateway_evidence": evidence,
                "controlled_bridge_policy": policy_snapshot,
                "broker_submission_enabled": bool(order["broker_submission_enabled"]),
                "requires_human_broker_entry": True,
                "required_gate_summary": required_gate_summary,
            },
            "limitations": [
                "This prepares a copyable manual-ticket export only.",
                "It does not submit to a broker, record an event, or change OMS status.",
            ],
        }

    def dry_run_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order = self._require_order(order_id)
        policy_snapshot = self._controlled_bridge_policy_snapshot()
        try:
            if order["status"] != "manually_confirmed":
                raise ValueError(
                    "OMS order must be manually_confirmed before ticketing"
                )
            evidence = self._require_gateway_evidence(order)
            self._require_kill_switch_clear()
        except ValueError as exc:
            event = self._record_manual_ticket_dry_run_event(
                order,
                status="rejected",
                actor=actor,
                payload={
                    "validation_result": "rejected",
                    "rejection_reason": str(exc),
                    "controlled_bridge_policy": policy_snapshot,
                },
            )
            exc.add_note(f"broker_gateway_event_id={event['id']}")
            raise

        ticket = self._manual_ticket(order)
        required_gate_summary = self._required_gate_summary(
            order,
            gateway_evidence=evidence,
        )
        result = {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "dry_run_accepted",
            "dry_run": True,
            "submitted_to_broker": False,
            "order_id": order["order_id"],
            "actor": actor,
            "ticket": ticket,
            "validation": {
                "manual_confirmation_status": "pass",
                "gateway_evidence_status": "pass",
                "gateway_evidence": evidence,
                "controlled_bridge_policy": policy_snapshot,
                "broker_submission_enabled": bool(order["broker_submission_enabled"]),
                "requires_human_broker_entry": True,
                "required_gate_summary": required_gate_summary,
            },
            "limitations": [
                "This records a dry-run validation event only.",
                "It does not submit to a broker or change OMS status.",
            ],
        }
        event = self._record_manual_ticket_dry_run_event(
            order,
            status="accepted",
            actor=actor,
            payload={
                "validation_result": "accepted",
                "ticket": ticket,
                "gateway_evidence": evidence,
                "controlled_bridge_policy": policy_snapshot,
                "required_gate_summary": required_gate_summary,
            },
        )
        return {**result, "event_id": event["id"]}

    def create_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        order, evidence = self._require_gateway_ready_order(order_id)
        self._require_kill_switch_clear()
        ticket = self._manual_ticket(order)
        policy_snapshot = self._controlled_bridge_policy_snapshot()
        updated = self._oms.transition_order(
            order_id,
            to_status="manual_ticket_created",
            reason="manual broker ticket created",
            actor=actor,
        )
        required_gate_summary = self._required_gate_summary(
            updated,
            gateway_evidence=evidence,
        )
        validation = {
            "manual_confirmation_status": "pass",
            "gateway_evidence_status": "pass",
            "gateway_evidence": evidence,
            "controlled_bridge_policy": policy_snapshot,
            "broker_submission_enabled": bool(updated["broker_submission_enabled"]),
            "requires_human_broker_entry": True,
            "required_gate_summary": required_gate_summary,
        }
        event = self._db.record_broker_gateway_event_sync(
            gateway_id="manual_ticket",
            event_type="manual_ticket_created",
            order_id=order_id,
            status="recorded",
            actor=actor,
            payload={
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "ticket": ticket,
                "gateway_evidence": evidence,
                "controlled_bridge_policy": policy_snapshot,
                "required_gate_summary": required_gate_summary,
                "submitted_to_broker": False,
            },
        )
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "manual_ticket_created",
            "submitted_to_broker": False,
            "controlled_bridge_policy": policy_snapshot,
            "validation": validation,
            "oms_order": updated,
            "ticket": ticket,
            "event_id": event["id"],
            "limitations": [
                "This is a manual broker ticket, not broker API submission.",
            ],
        }

    def _record_manual_ticket_dry_run_event(
        self,
        order: dict[str, Any],
        *,
        status: str,
        actor: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._db.record_broker_gateway_event_sync(
            gateway_id="manual_ticket",
            event_type=f"manual_ticket_dry_run_{status}",
            order_id=order["order_id"],
            status=status,
            actor=actor,
            payload={
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "order_status": order["status"],
                "dry_run": True,
                "submitted_to_broker": False,
                **payload,
            },
        )

    def _preview_payload(
        self,
        order: dict[str, Any],
        *,
        gateway_evidence: dict[str, Any],
        status: str,
        dry_run: bool,
        actor: str | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": status,
            "dry_run": dry_run,
            "submitted_to_broker": False,
            "order_id": order["order_id"],
            "actor": actor,
            "ticket": self._manual_ticket(order),
            "validation": {
                "manual_confirmation_status": "pass",
                "gateway_evidence_status": "pass",
                "gateway_evidence": gateway_evidence,
                "controlled_bridge_policy": self._controlled_bridge_policy_snapshot(),
                "broker_submission_enabled": bool(order["broker_submission_enabled"]),
                "requires_human_broker_entry": True,
                "required_gate_summary": self._required_gate_summary(
                    order,
                    gateway_evidence=gateway_evidence,
                ),
            },
            "limitations": [
                "This is a manual broker ticket preview, not broker API submission.",
            ],
        }

    def _manual_ticket(self, order: dict[str, Any]) -> dict[str, Any]:
        side = str(order["side"]).lower()
        quantity = _clean_number(order["quantity"])
        limit_price = (
            _clean_number(order["limit_price"])
            if order.get("limit_price") is not None
            else None
        )
        order_type = str(order["order_type"]).lower()
        parts = [
            side.upper(),
            str(order["symbol"]),
            str(quantity),
            order_type.upper(),
        ]
        if limit_price is not None:
            parts.append(str(limit_price))
        ticket = {
            "symbol": str(order["symbol"]),
            "side": side,
            "asset_class": str(order["asset_class"]),
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "copy_text": " ".join(parts),
        }
        return {
            **ticket,
            "operator_form": self._manual_ticket_operator_form(order, ticket=ticket),
        }

    def _manual_ticket_operator_form(
        self,
        order: dict[str, Any],
        *,
        ticket: dict[str, Any],
    ) -> dict[str, Any]:
        policy = self._controlled_bridge_policy_snapshot()
        account_alias = _operator_account_alias(policy)
        fields = [
            ("account_alias", "Account alias", account_alias),
            ("symbol", "Symbol", ticket["symbol"]),
            ("side", "Side", ticket["side"]),
            ("quantity", "Quantity", ticket["quantity"]),
            ("order_type", "Order type", ticket["order_type"]),
            ("limit_price", "Limit price", ticket["limit_price"]),
            ("copy_text", "Broker copy text", ticket["copy_text"]),
        ]
        return {
            "schema_version": "karkinos.manual_ticket_operator_form.v1",
            "account_alias": account_alias,
            "field_labels": {
                "account_alias": "Account alias",
                "symbol": "Symbol",
                "side": "Side",
                "quantity": "Quantity",
                "order_type": "Order type",
                "limit_price": "Limit price",
                "copy_text": "Broker copy text",
            },
            "fields": [
                {"key": key, "label": label, "value": value}
                for key, label, value in fields
                if value is not None
            ],
            "fee_tax_assumptions": _fee_tax_assumptions(order),
            "cash_impact_preview": _cash_impact_preview(order),
            "position_cost_preview": _position_cost_preview(order),
            "trading_session_constraints": _trading_session_constraints(order),
            "safety": {
                "broker_submission_enabled": False,
                "submitted_to_broker": False,
                "requires_human_broker_entry": True,
                "does_not_mutate_production_ledger": True,
            },
        }

    def _manual_ticket_export(
        self,
        order: dict[str, Any],
        *,
        ticket: dict[str, Any],
        gateway_evidence: dict[str, Any],
        controlled_bridge_policy: dict[str, Any],
        actor: str | None,
    ) -> dict[str, Any]:
        evidence_refs = {
            key: str(gateway_evidence[key].get("evidence_ref"))
            for key in _REQUIRED_GATEWAY_EVIDENCE
            if isinstance(gateway_evidence.get(key), dict)
            and gateway_evidence[key].get("evidence_ref")
        }
        content = {
            "schema_version": "karkinos.manual_ticket_export_payload.v1",
            "order_id": order["order_id"],
            "source": order.get("source"),
            "source_ref": order.get("source_ref"),
            "actor": actor,
            "ticket": ticket,
            "operator_form": ticket["operator_form"],
            "gateway_evidence_refs": dict(sorted(evidence_refs.items())),
            "account_truth_resolution": gateway_evidence.get(
                "account_truth_resolution"
            ),
            "current_per_order_confirmation": gateway_evidence.get(
                "current_per_order_confirmation"
            ),
            "controlled_bridge_policy": controlled_bridge_policy,
            "broker_submission_enabled": False,
            "submitted_to_broker": False,
            "requires_human_broker_entry": True,
        }
        return {
            "schema_version": "karkinos.manual_ticket_export.v1",
            "format": "json",
            "mime_type": "application/json",
            "file_name": f"karkinos-manual-ticket-{order['order_id']}.json",
            "copy_text": ticket["copy_text"],
            "content": content,
            "content_json": json.dumps(
                content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
