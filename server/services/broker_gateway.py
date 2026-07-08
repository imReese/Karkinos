"""Server-side broker gateway boundary for OMS orders."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from account_truth.broker_evidence import BrokerEvidenceRepository
from server.services.oms import OmsService

BROKER_GATEWAY_SCHEMA_VERSION = "karkinos.broker_gateway.v1"
CONTROLLED_BRIDGE_POLICY_SCHEMA_VERSION = "karkinos.controlled_broker_bridge_policy.v1"
MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCOPE = (
    "order_id, execution_preview, ledger_entry_draft, "
    "position_cost_preview, controlled_bridge_policy"
)
_CONTROLLED_BRIDGE_REQUIRED_GATES = (
    "account_truth",
    "research_evidence",
    "risk",
    "paper_shadow",
    "manual_confirmation",
    "kill_switch_clear",
    "connector_health",
    "execution_reconciliation",
)

_REQUIRED_GATEWAY_EVIDENCE: dict[str, tuple[str, set[str]]] = {
    "account_truth": ("gate_status", {"pass", "passed"}),
    "research_evidence": ("gate_status", {"pass", "passed"}),
    "risk": ("gate_status", {"pass", "passed"}),
    "paper_shadow": ("divergence_status", {"within_expectations"}),
}


class BrokerGatewayService:
    """Expose safe broker gateway capabilities and manual-ticket execution."""

    def __init__(
        self,
        *,
        db: Any,
        broker_connectors: list[Any] | None = None,
        controlled_bridge_policy: Any | None = None,
        trading_controls: Any | None = None,
    ) -> None:
        self._db = db
        self._oms = OmsService(db=db)
        self._broker_connectors = broker_connectors or []
        self._controlled_bridge_policy = controlled_bridge_policy
        self._trading_controls = trading_controls

    def get_status(self) -> dict[str, Any]:
        kill_switch = self._kill_switch_snapshot()
        return {
            "schema_version": "karkinos.broker_gateway_status.v1",
            "broker_submission_enabled": False,
            "kill_switch_enabled": bool(kill_switch["enabled"]),
            "kill_switch_reason": kill_switch["reason"],
            "controlled_bridge_policy": self._controlled_bridge_policy_snapshot(),
            "gateways": self.list_gateways(),
        }

    def list_gateways(self) -> list[dict[str, Any]]:
        kill_switch = self._kill_switch_snapshot()
        manual_ticket_blocked = bool(kill_switch["enabled"])
        return [
            {
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "gateway_id": "manual_ticket",
                "display_name": "Manual broker ticket",
                "status": (
                    "blocked_by_kill_switch" if manual_ticket_blocked else "available"
                ),
                "is_live": False,
                "can_read_account_facts": False,
                "can_preview_orders": not manual_ticket_blocked,
                "can_export_tickets": not manual_ticket_blocked,
                "can_dry_run_orders": not manual_ticket_blocked,
                "can_submit_orders": False,
                "can_cancel_orders": False,
                "can_query_orders": True,
                "can_query_fills": True,
                "can_query_positions": False,
                "can_query_cash": False,
                "requires_human_broker_entry": True,
                "blockers": ["kill_switch"] if manual_ticket_blocked else [],
                "blocked_reason": (
                    kill_switch["reason"] if manual_ticket_blocked else ""
                ),
                "limitations": [
                    "Creates copyable manual broker tickets only.",
                    "Does not call a broker API or mutate ledger entries.",
                    "Queries local OMS, gateway audit, and staged broker evidence only.",
                ],
            },
            {
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "gateway_id": "staged_broker_evidence",
                "display_name": "Staged broker evidence",
                "status": "available",
                "is_live": False,
                "can_read_account_facts": True,
                "can_preview_orders": False,
                "can_export_tickets": False,
                "can_dry_run_orders": False,
                "can_submit_orders": False,
                "can_cancel_orders": False,
                "can_query_orders": True,
                "can_query_fills": True,
                "can_query_positions": True,
                "can_query_cash": True,
                "requires_human_broker_entry": False,
                "limitations": [
                    "Reads staged broker evidence already imported into Karkinos.",
                    "Does not call a broker API, store credentials, or mutate OMS.",
                    "Broker order submission remains disabled.",
                ],
            },
            {
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "gateway_id": "live_disabled",
                "display_name": "Live broker gateway",
                "status": "disabled",
                "is_live": True,
                "can_read_account_facts": False,
                "can_preview_orders": False,
                "can_export_tickets": False,
                "can_dry_run_orders": False,
                "can_submit_orders": False,
                "can_cancel_orders": False,
                "can_query_orders": False,
                "can_query_fills": False,
                "can_query_positions": False,
                "can_query_cash": False,
                "requires_human_broker_entry": False,
                "controlled_bridge_policy_status": (
                    self._controlled_bridge_policy_snapshot()["status"]
                ),
                "limitations": [
                    "Live broker submission is disabled until explicit gated enablement.",
                ],
            },
        ]

    def list_connector_health(self) -> list[dict[str, Any]]:
        """Return read-only connector health contracts without touching brokers."""
        return [
            _connector_health_payload(connector)
            for connector in self._broker_connectors
        ]

    def query_staged_account_facts(self) -> dict[str, Any]:
        import_runs, broker_events = self._staged_broker_events(limit=20)
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "staged_broker_evidence",
            "status": "available" if broker_events else "empty",
            "query_scope": "staged_broker_evidence",
            "submitted_to_broker": False,
            "can_submit_orders": False,
            "source_import_run_ids": [
                import_run.import_run_id for import_run in import_runs
            ],
            "broker_event_count": len(broker_events),
            "cash_balances": _cash_balance_payloads(broker_events),
            "positions": _position_payloads(broker_events),
            "fills": [
                _broker_account_fill_payload(event)
                for event in broker_events
                if str(getattr(event, "event_type", "")).startswith("trade_")
            ],
            "limitations": [
                "This query reads staged broker evidence only.",
                "It does not contact a broker, submit orders, or mutate OMS status.",
                "Staged facts must be reconciled before strategy promotion or live-like use.",
            ],
        }

    def query_connector_snapshot(self, connector_id: str) -> dict[str, Any]:
        normalized_connector_id = str(connector_id or "").strip()
        if not normalized_connector_id:
            raise KeyError("Connector id is required")
        for connector in self._broker_connectors:
            if not callable(getattr(connector, "read_account_snapshot", None)):
                continue
            snapshot = connector.read_account_snapshot()
            if (
                str(getattr(snapshot, "connector_id", "") or "")
                != normalized_connector_id
            ):
                continue
            return _runtime_connector_snapshot_payload(
                snapshot,
                capabilities=getattr(connector, "capabilities", None),
            )
        raise KeyError(f"Read-only connector snapshot not found: {connector_id}")

    def query_staged_fills(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").strip()
        safe_limit = max(1, min(int(limit), 500))
        import_runs, broker_events = self._staged_broker_events(limit=safe_limit)
        fills: list[dict[str, Any]] = []
        for event in broker_events:
            event_type = str(getattr(event, "event_type", "") or "")
            if not event_type.startswith("trade_"):
                continue
            if (
                normalized_symbol
                and str(getattr(event, "symbol", "")) != normalized_symbol
            ):
                continue
            fills.append(_broker_account_fill_payload(event))
            if len(fills) >= safe_limit:
                break
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "staged_broker_evidence",
            "status": "available" if fills else "empty",
            "query_scope": "staged_broker_fills",
            "submitted_to_broker": False,
            "can_submit_orders": False,
            "symbol": normalized_symbol or None,
            "source_import_run_ids": [
                import_run.import_run_id for import_run in import_runs
            ],
            "broker_event_count": len(broker_events),
            "fill_count": len(fills),
            "fills": fills,
            "limitations": [
                "This query reads staged broker fill evidence only.",
                "It does not contact a broker, submit orders, or mutate OMS status.",
                "Staged fills must be reconciled before any ledger update is suggested.",
            ],
        }

    def query_order(self, order_id: str) -> dict[str, Any]:
        order = self._require_order(order_id)
        gateway_events = self._db.list_broker_gateway_events_sync(order_id=order_id)
        staged_broker_fills = self._staged_broker_fills_for_order(order)
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "query_ready",
            "query_scope": "local_audit_and_staged_broker_evidence",
            "submitted_to_broker": False,
            "can_submit_orders": False,
            "oms_order": order,
            "gateway_event_count": len(gateway_events),
            "gateway_events": [
                _gateway_event_payload(event) for event in gateway_events
            ],
            "staged_broker_fill_count": len(staged_broker_fills),
            "staged_broker_fills": staged_broker_fills,
            "limitations": [
                "This query reads local Karkinos facts and staged broker evidence only.",
                "It does not contact a broker, submit orders, or mutate OMS status.",
            ],
        }

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

    def _require_order(self, order_id: str) -> dict[str, Any]:
        order = self._db.get_oms_order_sync(order_id)
        if order is None:
            raise KeyError(f"OMS order not found: {order_id}")
        return order

    def _require_manual_confirmed_order(self, order_id: str) -> dict[str, Any]:
        order = self._require_order(order_id)
        if order["status"] != "manually_confirmed":
            raise ValueError("OMS order must be manually_confirmed before ticketing")
        return order

    def _require_gateway_ready_order(
        self,
        order_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        order = self._require_manual_confirmed_order(order_id)
        evidence = self._require_gateway_evidence(order)
        return order, evidence

    def _require_gateway_evidence(self, order: dict[str, Any]) -> dict[str, Any]:
        payload = _order_payload(order)
        evidence = payload.get("gateway_evidence")
        if not isinstance(evidence, dict):
            evidence = {}

        missing: list[str] = []
        blocked: list[str] = []
        for key, (status_field, passing_values) in _REQUIRED_GATEWAY_EVIDENCE.items():
            item = evidence.get(key)
            if not isinstance(item, dict):
                missing.append(key)
                continue
            if not item.get("evidence_ref"):
                missing.append(key)
                continue
            status = str(item.get(status_field) or "").lower()
            if status not in passing_values:
                blocked.append(key)

        if missing:
            raise ValueError("missing gateway evidence: " + ", ".join(missing))
        if blocked:
            raise ValueError("gateway evidence not passing: " + ", ".join(blocked))
        return evidence

    def _require_kill_switch_clear(self) -> None:
        kill_switch = self._kill_switch_snapshot()
        if not bool(kill_switch["enabled"]):
            return
        reason = kill_switch["reason"]
        message = "kill switch is enabled"
        if reason:
            message = f"{message}: {reason}"
        raise ValueError(message)

    def _kill_switch_snapshot(self) -> dict[str, Any]:
        snapshot_getter = getattr(self._trading_controls, "snapshot", None)
        if not callable(snapshot_getter):
            return {"enabled": False, "reason": ""}
        snapshot = snapshot_getter()
        return {
            "enabled": bool(getattr(snapshot, "kill_switch_enabled", False)),
            "reason": str(getattr(snapshot, "reason", "") or "").strip(),
        }

    def _controlled_bridge_policy_snapshot(self) -> dict[str, Any]:
        policy = self._controlled_bridge_policy
        enabled = (
            bool(getattr(policy, "enabled", False)) if policy is not None else False
        )
        allowed_connector_ids = _string_list(
            getattr(policy, "allowed_connector_ids", ()) if policy is not None else ()
        )
        allowed_account_aliases = _string_list(
            getattr(policy, "allowed_account_aliases", ()) if policy is not None else ()
        )
        allowed_strategy_ids = _string_list(
            getattr(policy, "allowed_strategy_ids", ()) if policy is not None else ()
        )
        allowed_symbols = _string_list(
            getattr(policy, "allowed_symbols", ()) if policy is not None else ()
        )
        whitelist_empty = not any(
            (
                allowed_connector_ids,
                allowed_account_aliases,
                allowed_strategy_ids,
                allowed_symbols,
            )
        )
        blockers: list[str] = []
        if not enabled:
            blockers.append("controlled_bridge_policy_disabled")
        if whitelist_empty:
            blockers.append("controlled_bridge_whitelist_empty")
        blockers.append("live_gateway_not_implemented")
        status = "disabled"
        if enabled:
            status = (
                "incomplete_whitelist"
                if whitelist_empty
                else "configured_non_submitting"
            )
        per_order_confirmation_required = (
            bool(getattr(policy, "per_order_confirmation_required", True))
            if policy is not None
            else True
        )
        return {
            "schema_version": CONTROLLED_BRIDGE_POLICY_SCHEMA_VERSION,
            "policy_id": str(
                getattr(policy, "policy_id", "default-controlled-bridge-disabled")
                if policy is not None
                else "default-controlled-bridge-disabled"
            ),
            "status": status,
            "enabled": enabled,
            "broker_submission_enabled": False,
            "live_submission_available": False,
            "automation_allowed": False,
            "per_order_confirmation_required": (
                True if not enabled else per_order_confirmation_required
            ),
            "allowed_connector_ids": allowed_connector_ids,
            "allowed_account_aliases": allowed_account_aliases,
            "allowed_strategy_ids": allowed_strategy_ids,
            "allowed_symbols": allowed_symbols,
            "required_gates": list(_CONTROLLED_BRIDGE_REQUIRED_GATES),
            "blockers": blockers,
            "limitations": [
                "This is a non-submitting policy skeleton for future bridge review.",
                "It does not enable broker API submission or broker cancellation.",
                "Strategy code must not call broker adapters directly.",
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

    def _staged_broker_events(self, *, limit: int) -> tuple[list[Any], list[Any]]:
        db_path = getattr(self._db, "_path", None)
        if db_path is None:
            return [], []
        repository = BrokerEvidenceRepository(Path(db_path))
        import_runs = repository.list_import_runs(limit=limit)
        broker_events: list[Any] = []
        for import_run in import_runs:
            broker_events.extend(repository.list_events(import_run.import_run_id))
        return import_runs, broker_events

    def _staged_broker_fills_for_order(
        self, order: dict[str, Any]
    ) -> list[dict[str, Any]]:
        db_path = getattr(self._db, "_path", None)
        if db_path is None:
            return []
        expected_type = (
            "trade_buy" if str(order.get("side")).lower() == "buy" else "trade_sell"
        )
        symbol = str(order.get("symbol") or "")
        order_quantity = _decimal_value(order.get("quantity"))
        repository = BrokerEvidenceRepository(Path(db_path))
        fills: list[dict[str, Any]] = []
        for import_run in repository.list_import_runs(limit=20):
            for event in repository.list_events(import_run.import_run_id):
                if getattr(event, "event_type", "") != expected_type:
                    continue
                if str(getattr(event, "symbol", "")) != symbol:
                    continue
                fills.append(
                    _broker_fill_payload(
                        event,
                        order_quantity=order_quantity,
                    )
                )
        return fills

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

    def _required_gate_summary(
        self,
        order: dict[str, Any],
        *,
        gateway_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        kill_switch = self._kill_switch_snapshot()
        gates: dict[str, dict[str, Any]] = {}
        for gate in ("account_truth", "research_evidence", "risk", "paper_shadow"):
            evidence = gateway_evidence.get(gate)
            if isinstance(evidence, dict):
                status_field, passing_values = _REQUIRED_GATEWAY_EVIDENCE[gate]
                raw_status = str(evidence.get(status_field) or "").lower()
                status = "pass" if raw_status in passing_values else raw_status
                gates[gate] = {
                    "status": status or "missing",
                    "evidence_ref": str(evidence.get("evidence_ref") or ""),
                    "source": "oms_gateway_evidence",
                }
            else:
                gates[gate] = {
                    "status": "missing",
                    "evidence_ref": "",
                    "source": "oms_gateway_evidence",
                }
        gates["manual_confirmation"] = {
            "status": "pass",
            "evidence_ref": (
                f"oms_order:{order['order_id']}:{order.get('status') or 'unknown'}"
            ),
            "source": "oms_status",
        }
        gates["kill_switch_clear"] = {
            "status": "blocked" if kill_switch["enabled"] else "pass",
            "evidence_ref": (
                "trading_controls:kill_switch_enabled"
                if kill_switch["enabled"]
                else "trading_controls:kill_switch_clear"
            ),
            "source": "trading_controls_snapshot",
        }
        gates["connector_health"] = {
            "status": "not_applicable_manual_ticket",
            "evidence_ref": "manual_ticket:local_operator_entry",
            "source": "manual_ticket_gateway",
        }
        gates["execution_reconciliation"] = {
            "status": "pending_after_manual_execution",
            "evidence_ref": f"execution_reconciliation:pending:{order['order_id']}",
            "source": "execution_reconciliation_runbook",
        }
        blocking_statuses = {"missing", "blocked", "failed", "rejected"}
        status = (
            "blocked"
            if any(item["status"] in blocking_statuses for item in gates.values())
            else "pass"
        )
        return {
            "schema_version": "karkinos.controlled_bridge_gate_summary.v1",
            "status": status,
            "required_gates": list(_CONTROLLED_BRIDGE_REQUIRED_GATES),
            "gates": gates,
            "broker_submission_enabled": False,
            "submitted_to_broker": False,
            "does_not_authorize_execution": True,
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
            key: str(value.get("evidence_ref"))
            for key, value in gateway_evidence.items()
            if isinstance(value, dict) and value.get("evidence_ref")
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


def _manual_execution_preview(
    order: dict[str, Any],
    *,
    fill_price: Any,
    quantity: Any,
    fee: Any,
    tax: Any,
    transfer_fee: Any,
) -> dict[str, Any]:
    side = str(order.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError(f"unsupported OMS side for manual execution preview: {side}")
    price_value = _required_decimal(fill_price, "fill_price")
    quantity_value = _required_decimal(quantity, "quantity")
    if price_value <= 0:
        raise ValueError("fill_price must be positive")
    if quantity_value <= 0:
        raise ValueError("quantity must be positive")
    fee_value = _optional_decimal(fee)
    tax_value = _optional_decimal(tax)
    transfer_fee_value = _optional_decimal(transfer_fee)
    gross_amount = price_value * quantity_value
    total_cost = fee_value + tax_value + transfer_fee_value
    net_cash_impact = (
        -(gross_amount + total_cost) if side == "buy" else gross_amount - total_cost
    )
    return {
        "source": "manual_ticket_operator_entry",
        "symbol": str(order.get("symbol") or ""),
        "side": side,
        "asset_class": str(order.get("asset_class") or ""),
        "quantity": _quantity_string(quantity_value),
        "fill_price": _money_string(price_value),
        "gross_amount": _money_string(gross_amount),
        "fee": _money_string(fee_value),
        "tax": _money_string(tax_value),
        "transfer_fee": _money_string(transfer_fee_value),
        "total_cost": _money_string(total_cost),
        "net_cash_impact": _money_string(net_cash_impact),
        "currency": "CNY",
        "notes": [
            "Broker client fill and fee/tax statement remains authoritative.",
            "Preview is an operator review draft before any production ledger save.",
        ],
    }


def _manual_execution_ledger_draft(
    order: dict[str, Any],
    *,
    execution_preview: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.manual_execution_ledger_draft.v1",
        "entry_type": "trade",
        "symbol": execution_preview["symbol"],
        "side": execution_preview["side"],
        "asset_class": execution_preview["asset_class"],
        "quantity": execution_preview["quantity"],
        "price": execution_preview["fill_price"],
        "gross_amount": execution_preview["gross_amount"],
        "fee": execution_preview["fee"],
        "tax": execution_preview["tax"],
        "transfer_fee": execution_preview["transfer_fee"],
        "amount": execution_preview["net_cash_impact"],
        "source_order_id": order["order_id"],
        "source": "manual_ticket_execution_preview",
        "requires_operator_save": True,
        "does_not_mutate_production_ledger": True,
    }


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _required_decimal(value: Any, field_name: str) -> Decimal:
    parsed = _decimal_value(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be numeric")
    return parsed


def _optional_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    parsed = _decimal_value(value)
    if parsed is None:
        raise ValueError("fee, tax, and transfer_fee must be numeric when provided")
    return parsed


def _money_string(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _quantity_string(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _clean_number(value: Any) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, list | tuple | set):
        values = value
    else:
        values = ()
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _operator_account_alias(policy: dict[str, Any]) -> str:
    aliases = policy.get("allowed_account_aliases")
    if isinstance(aliases, list) and aliases:
        return str(aliases[0])
    return "manual-review"


def _fee_tax_assumptions(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = _order_intent_payload(order)
    fee_components = _mapping_value(
        source_payload.get("fee_breakdown"),
        source_payload.get("fee_components"),
    )
    return {
        "source": "oms_order_payload_or_fee_rule",
        "estimated_total_fee": _optional_clean_number(
            source_payload.get("estimated_total_fee")
        ),
        "estimated_net_cash_impact": _optional_clean_number(
            source_payload.get("estimated_net_cash_impact")
        ),
        "fee_rule_id": _optional_string(source_payload.get("fee_rule_id")),
        "fee_rule_version": _optional_string(source_payload.get("fee_rule_version")),
        "fee_components": dict(sorted(fee_components.items())),
        "notes": [
            "Broker client final fee and tax preview remains authoritative.",
            "Karkinos fee/tax values are execution-review assumptions only.",
        ],
    }


def _cash_impact_preview(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = _order_intent_payload(order)
    return {
        "source": "oms_order_payload_or_order_intent",
        "estimated_gross_amount": _optional_clean_number(
            source_payload.get("estimated_gross_amount")
        ),
        "estimated_total_fee": _optional_clean_number(
            source_payload.get("estimated_total_fee")
        ),
        "estimated_net_cash_impact": _optional_clean_number(
            source_payload.get("estimated_net_cash_impact")
        ),
        "available_cash_before": _optional_clean_number(
            source_payload.get("available_cash_before")
        ),
        "available_cash_after": _optional_clean_number(
            source_payload.get("available_cash_after")
        ),
        "cash_status": _optional_string(source_payload.get("cash_status")),
        "cash_shortfall": _optional_clean_number(source_payload.get("cash_shortfall")),
    }


def _position_cost_preview(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = _order_intent_payload(order)
    position_effect = _mapping_value(
        source_payload.get("position_effect"),
        source_payload.get("position_cost_preview"),
    )
    return {
        "source": "daily_trading_plan_position_effect",
        "current_quantity": _optional_clean_number(
            position_effect.get("current_quantity")
        ),
        "current_avg_cost": _optional_clean_number(
            position_effect.get("current_avg_cost")
        ),
        "current_market_value": _optional_clean_number(
            position_effect.get("current_market_value")
        ),
        "estimated_quantity_after": _optional_clean_number(
            position_effect.get("estimated_quantity_after")
        ),
        "estimated_avg_cost_after": _optional_clean_number(
            position_effect.get("estimated_avg_cost_after")
        ),
        "cost_basis_method": _optional_string(position_effect.get("cost_basis_method")),
    }


def _trading_session_constraints(order: dict[str, Any]) -> dict[str, Any]:
    asset_class = str(order.get("asset_class") or "").lower()
    notes = [
        "Operator must enter this ticket only while the broker client accepts regular-session orders.",
        "Broker client availability and exchange rules remain authoritative.",
    ]
    if asset_class == "stock" and str(order.get("side") or "").lower() == "sell":
        notes.append(
            "For A-share sells, verify broker available quantity and T+1 state."
        )
    return {
        "market": "China exchange session",
        "timezone": "Asia/Shanghai",
        "allowed_session": "regular_exchange_session_only",
        "asset_class": asset_class or "unknown",
        "notes": notes,
    }


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _mapping_value(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _optional_clean_number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        return _clean_number(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _order_intent_payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = _order_payload(order)
    return _first_mapping(
        payload.get("order_intent"),
        payload.get("daily_trading_plan_intent"),
        payload,
    )


def _order_payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = order.get("payload")
    if isinstance(payload, dict):
        return payload
    payload_json = order.get("payload_json")
    if not isinstance(payload_json, str) or not payload_json:
        return {}
    try:
        parsed = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _gateway_event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event["id"],
        "gateway_id": event["gateway_id"],
        "event_type": event["event_type"],
        "status": event["status"],
        "actor": event.get("actor"),
        "created_at": event["created_at"],
    }


def _broker_fill_payload(
    event: Any, *, order_quantity: Decimal | None
) -> dict[str, Any]:
    event_quantity = _decimal_value(getattr(event, "quantity", None))
    match_status = (
        "matched"
        if order_quantity is not None
        and event_quantity is not None
        and abs(order_quantity) == abs(event_quantity)
        else "quantity_mismatch"
    )
    return {
        "source": "staged_broker_evidence",
        "import_run_id": getattr(event, "import_run_id", ""),
        "event_id": getattr(event, "event_id", ""),
        "event_type": getattr(event, "event_type", ""),
        "symbol": getattr(event, "symbol", ""),
        "side": "buy" if getattr(event, "event_type", "") == "trade_buy" else "sell",
        "quantity": getattr(event, "quantity", ""),
        "price": getattr(event, "price", ""),
        "fee": getattr(event, "fee", ""),
        "tax": getattr(event, "tax", ""),
        "net_amount": getattr(event, "net_amount", ""),
        "occurred_at": getattr(event, "occurred_at", ""),
        "settled_at": getattr(event, "settled_at", ""),
        "match_status": match_status,
    }


def _cash_balance_payloads(events: list[Any]) -> list[dict[str, Any]]:
    by_currency: dict[str, dict[str, Any]] = {}
    for event in events:
        cash_balance = getattr(event, "cash_balance", None)
        currency = str(getattr(event, "currency", "") or "")
        if cash_balance is None or not currency or currency in by_currency:
            continue
        by_currency[currency] = {
            "source": "staged_broker_evidence",
            "import_run_id": getattr(event, "import_run_id", ""),
            "event_id": getattr(event, "event_id", ""),
            "currency": currency,
            "cash_balance": cash_balance,
            "occurred_at": getattr(event, "occurred_at", ""),
            "settled_at": getattr(event, "settled_at", ""),
        }
    return list(by_currency.values())


def _position_payloads(events: list[Any]) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for event in events:
        quantity = getattr(event, "position_quantity", None)
        symbol = str(getattr(event, "symbol", "") or "")
        if quantity is None or not symbol or symbol in by_symbol:
            continue
        by_symbol[symbol] = {
            "source": "staged_broker_evidence",
            "import_run_id": getattr(event, "import_run_id", ""),
            "event_id": getattr(event, "event_id", ""),
            "symbol": symbol,
            "instrument_name": getattr(event, "instrument_name", ""),
            "asset_class": getattr(event, "asset_class", ""),
            "currency": getattr(event, "currency", ""),
            "quantity": quantity,
            "cost_basis": getattr(event, "cost_basis", None),
            "cost_basis_method": getattr(event, "cost_basis_method", ""),
            "occurred_at": getattr(event, "occurred_at", ""),
            "settled_at": getattr(event, "settled_at", ""),
        }
    return list(by_symbol.values())


def _broker_account_fill_payload(event: Any) -> dict[str, Any]:
    event_type = str(getattr(event, "event_type", "") or "")
    if event_type == "trade_buy":
        side = "buy"
    elif event_type == "trade_sell":
        side = "sell"
    else:
        side = "unknown"
    return {
        "source": "staged_broker_evidence",
        "import_run_id": getattr(event, "import_run_id", ""),
        "event_id": getattr(event, "event_id", ""),
        "event_type": event_type,
        "symbol": getattr(event, "symbol", ""),
        "side": side,
        "quantity": getattr(event, "quantity", ""),
        "price": getattr(event, "price", ""),
        "gross_amount": getattr(event, "gross_amount", ""),
        "fee": getattr(event, "fee", ""),
        "tax": getattr(event, "tax", ""),
        "net_amount": getattr(event, "net_amount", ""),
        "occurred_at": getattr(event, "occurred_at", ""),
        "settled_at": getattr(event, "settled_at", ""),
    }


def _decimal_value(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _connector_health_payload(connector: Any) -> dict[str, Any]:
    if callable(getattr(connector, "read_account_snapshot", None)):
        return _runtime_connector_health_payload(connector)

    connector_id = str(getattr(connector, "connector_id", "") or "")
    connector_type = str(getattr(connector, "connector_type", "") or "readonly")
    enabled = bool(getattr(connector, "enabled", False))
    client_path = str(getattr(connector, "client_path", "") or "").strip()
    account_alias = str(getattr(connector, "account_alias", "") or "").strip()
    if not enabled:
        status = "disabled"
        message = "Connector is configured but disabled."
    elif not client_path or not account_alias:
        status = "configuration_incomplete"
        message = "Read-only connector requires local client path and account alias."
    else:
        status = "configured_readonly_unverified"
        message = (
            "Read-only connector is configured; live client health is not checked."
        )
    return {
        "schema_version": "karkinos.broker_connector_health.v1",
        "connector_id": connector_id,
        "connector_type": connector_type,
        "enabled": enabled,
        "status": status,
        "message": message,
        "account_alias": account_alias,
        "capability_scope": "local_readonly_connector_contract",
        "capabilities": {
            "can_read_health": enabled,
            "can_read_account": enabled,
            "can_read_cash": enabled,
            "can_read_positions": enabled,
            "can_read_orders": enabled,
            "can_read_fills": enabled,
            "can_preview_orders": False,
            "can_export_tickets": False,
            "can_dry_run_orders": False,
            "can_submit_orders": False,
            "can_cancel_orders": False,
        },
        "requires_credentials": False,
        "stores_credentials": False,
        "submitted_to_broker": False,
        "limitations": [
            "Connector health is a local configuration contract only.",
            "No broker client is contacted and no credentials are stored.",
            "Broker order submission remains disabled.",
        ],
    }


def _runtime_connector_health_payload(connector: Any) -> dict[str, Any]:
    capabilities = getattr(connector, "capabilities", None)
    try:
        snapshot = connector.read_account_snapshot()
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        connector_id = str(
            getattr(connector, "connector_id", "")
            or getattr(connector, "__class__", type(connector)).__name__
        )
        return {
            "schema_version": "karkinos.broker_connector_health.v1",
            "connector_id": connector_id,
            "connector_type": "read_only_snapshot",
            "enabled": True,
            "status": "runtime_unavailable",
            "message": "Read-only connector snapshot failed.",
            "account_alias": "",
            "capability_scope": "runtime_readonly_connector_snapshot",
            "last_heartbeat_at": None,
            "last_error": str(exc),
            "capabilities": _runtime_connector_capabilities_payload(capabilities),
            "requires_credentials": False,
            "stores_credentials": False,
            "submitted_to_broker": False,
            "limitations": [
                "Read-only connector snapshot is runtime evidence only.",
                "Connector snapshot failed; verify the local broker client manually.",
                "No broker order was submitted or cancelled.",
            ],
        }

    health = getattr(snapshot, "health", None)
    raw_status = str(getattr(health, "status", "") or "unknown")
    status = _runtime_connector_status(raw_status)
    message = str(getattr(health, "message", "") or raw_status)
    heartbeat = str(
        getattr(health, "checked_at", "") or getattr(snapshot, "captured_at", "") or ""
    )
    limitations = [
        "Read-only connector snapshot is runtime evidence only.",
        "It does not submit or cancel broker orders, create gateway events, or mutate ledger entries.",
    ]
    limitations.extend(_string_list(getattr(snapshot, "limitations", ())))
    limitations.extend(_string_list(getattr(health, "limitations", ())))
    return {
        "schema_version": "karkinos.broker_connector_health.v1",
        "connector_id": str(getattr(snapshot, "connector_id", "") or ""),
        "connector_type": "read_only_snapshot",
        "enabled": True,
        "status": status,
        "message": message,
        "account_alias": str(getattr(snapshot, "account_alias", "") or ""),
        "source_name": str(getattr(snapshot, "source_name", "") or ""),
        "capability_scope": "runtime_readonly_connector_snapshot",
        "last_heartbeat_at": heartbeat or None,
        "last_error": message if status != "runtime_healthy" and message else None,
        "capabilities": _runtime_connector_capabilities_payload(capabilities),
        "requires_credentials": False,
        "stores_credentials": False,
        "submitted_to_broker": False,
        "limitations": _string_list(limitations),
    }


def _runtime_connector_snapshot_payload(
    snapshot: Any,
    *,
    capabilities: Any,
) -> dict[str, Any]:
    health = getattr(snapshot, "health", None)
    raw_status = str(getattr(health, "status", "") or "unknown")
    runtime_status = _runtime_connector_status(raw_status)
    query_status = "snapshot_ready"
    if runtime_status == "runtime_unavailable":
        query_status = "snapshot_unavailable"
    elif runtime_status != "runtime_healthy":
        query_status = "snapshot_degraded"
    message = str(getattr(health, "message", "") or raw_status)
    limitations = [
        "Read-only connector snapshot query is runtime evidence only.",
        "It does not contact write APIs, submit or cancel broker orders, mutate OMS, or write ledger entries.",
    ]
    limitations.extend(_string_list(getattr(snapshot, "limitations", ())))
    limitations.extend(_string_list(getattr(health, "limitations", ())))
    positions = [
        _runtime_position_payload(position)
        for position in list(getattr(snapshot, "positions", []) or [])
    ]
    orders = [
        _runtime_order_payload(order)
        for order in list(getattr(snapshot, "orders", []) or [])
    ]
    fills = [
        _runtime_fill_payload(fill)
        for fill in list(getattr(snapshot, "fills", []) or [])
    ]
    return {
        "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
        "gateway_id": "read_only_connector",
        "status": query_status,
        "query_scope": "runtime_readonly_connector_snapshot",
        "connector_id": str(getattr(snapshot, "connector_id", "") or ""),
        "connector_type": "read_only_snapshot",
        "account_alias": str(getattr(snapshot, "account_alias", "") or ""),
        "source_name": str(getattr(snapshot, "source_name", "") or ""),
        "captured_at": str(getattr(snapshot, "captured_at", "") or ""),
        "connector_health": {
            "status": runtime_status,
            "raw_status": raw_status,
            "message": message,
            "checked_at": str(getattr(health, "checked_at", "") or ""),
        },
        "capability_scope": "runtime_readonly_connector_snapshot",
        "capabilities": _runtime_connector_capabilities_payload(capabilities),
        "submitted_to_broker": False,
        "can_submit_orders": False,
        "stores_credentials": False,
        "requires_credentials": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "cash_balance": _runtime_cash_payload(getattr(snapshot, "cash", None)),
        "position_count": len(positions),
        "positions": positions,
        "order_count": len(orders),
        "orders": orders,
        "fill_count": len(fills),
        "fills": fills,
        "limitations": _string_list(limitations),
    }


def _runtime_cash_payload(cash: Any) -> dict[str, Any]:
    if cash is None:
        return {}
    return {
        "currency": str(getattr(cash, "currency", "") or ""),
        "balance": _decimal_payload(getattr(cash, "balance", None)),
        "available": _decimal_payload(getattr(cash, "available", None)),
    }


def _runtime_position_payload(position: Any) -> dict[str, Any]:
    return {
        "symbol": str(getattr(position, "symbol", "") or ""),
        "instrument_name": str(getattr(position, "instrument_name", "") or ""),
        "asset_class": str(getattr(position, "asset_class", "") or ""),
        "quantity": _decimal_payload(getattr(position, "quantity", None)),
        "available_quantity": _decimal_payload(
            getattr(position, "available_quantity", None)
        ),
        "cost_basis": _decimal_payload(getattr(position, "cost_basis", None)),
        "market_price": _decimal_payload(getattr(position, "market_price", None)),
    }


def _runtime_order_payload(order: Any) -> dict[str, Any]:
    return {
        "order_id": str(getattr(order, "order_id", "") or ""),
        "symbol": str(getattr(order, "symbol", "") or ""),
        "side": str(getattr(order, "side", "") or ""),
        "status": str(getattr(order, "status", "") or ""),
        "quantity": _decimal_payload(getattr(order, "quantity", None)),
        "price": _decimal_payload(getattr(order, "price", None)),
        "submitted_at": str(getattr(order, "submitted_at", "") or ""),
    }


def _runtime_fill_payload(fill: Any) -> dict[str, Any]:
    return {
        "fill_id": str(getattr(fill, "fill_id", "") or ""),
        "order_id": str(getattr(fill, "order_id", "") or ""),
        "symbol": str(getattr(fill, "symbol", "") or ""),
        "side": str(getattr(fill, "side", "") or ""),
        "quantity": _decimal_payload(getattr(fill, "quantity", None)),
        "price": _decimal_payload(getattr(fill, "price", None)),
        "fee": _decimal_payload(getattr(fill, "fee", None)),
        "tax": _decimal_payload(getattr(fill, "tax", None)),
        "net_amount": _decimal_payload(getattr(fill, "net_amount", None)),
        "filled_at": str(getattr(fill, "filled_at", "") or ""),
    }


def _decimal_payload(value: Any) -> str | None:
    decimal = _decimal_value(value)
    if decimal is None:
        return None
    return str(decimal)


def _runtime_connector_status(raw_status: str) -> str:
    normalized = str(raw_status or "").lower()
    if normalized == "healthy":
        return "runtime_healthy"
    if normalized == "disconnected":
        return "runtime_unavailable"
    return "runtime_degraded"


def _runtime_connector_capabilities_payload(capabilities: Any) -> dict[str, bool]:
    return {
        "can_read_health": bool(getattr(capabilities, "can_read_health", True)),
        "can_read_account": bool(getattr(capabilities, "can_read_account", True)),
        "can_read_cash": bool(getattr(capabilities, "can_read_cash", True)),
        "can_read_positions": bool(getattr(capabilities, "can_read_positions", True)),
        "can_read_orders": bool(getattr(capabilities, "can_read_orders", True)),
        "can_read_fills": bool(getattr(capabilities, "can_read_fills", True)),
        "can_preview_orders": False,
        "can_export_tickets": False,
        "can_dry_run_orders": False,
        "can_submit_orders": False,
        "can_cancel_orders": False,
    }
