"""Application service managing manual broker tickets and manual execution evidence."""

from __future__ import annotations

from typing import Any, Callable

from domain.manual_trading import (
    MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCHEMA_VERSION,
    build_manual_execution_ledger_draft,
    clean_decimal,
    compute_execution_cash_impact,
    compute_preview_fingerprint,
    money_string,
    optional_decimal,
    quantity_string,
    verify_preview_fingerprint,
)
from server.contracts.broker_gateway import (
    BROKER_GATEWAY_SCHEMA_VERSION,
    MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCOPE,
)
from server.services.controlled_execution.oms import OmsService
from server.services.manual_trading.values import (
    FINGERPRINT_PATTERN,
    REQUIRED_GATEWAY_EVIDENCE,
    build_manual_ticket,
    build_manual_ticket_export,
    build_position_cost_preview,
    build_required_gate_summary,
    controlled_bridge_policy_snapshot,
    order_payload,
)
from server.services.risk.trading_controls import resolve_kill_switch_evidence


class ManualTradingService:
    """Orchestrates manual broker ticket workflows and manual execution evidence."""

    def __init__(
        self,
        *,
        db: Any,
        oms: Any | None = None,
        trading_controls: Any | None = None,
        current_per_order_confirmation_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        controlled_bridge_policy: Any | None = None,
        broker_evidence_repository_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._db = db
        self._oms = oms or OmsService(db=db)
        self._trading_controls = trading_controls
        self._current_per_order_confirmation_provider = (
            current_per_order_confirmation_provider
        )
        self._controlled_bridge_policy = controlled_bridge_policy
        self._broker_evidence_repository_factory = broker_evidence_repository_factory

    # -------------------------------------------------------------------------
    # Public Workflow Methods
    # -------------------------------------------------------------------------

    def query_order(self, order_id: str) -> dict[str, Any]:
        """Query OMS order facts, manual ticket events, and staged fills."""
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
                {
                    "id": event["id"],
                    "gateway_id": event["gateway_id"],
                    "event_type": event["event_type"],
                    "status": event["status"],
                    "actor": event.get("actor"),
                    "created_at": event["created_at"],
                }
                for event in gateway_events
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
        """Generate a dry-run ticket preview without mutating state or recording events."""
        order, evidence = self._require_gateway_ready_order(order_id)
        self._require_kill_switch_clear()
        policy = self._controlled_bridge_policy_snapshot()
        ticket = build_manual_ticket(order, policy=policy)
        required_gate_summary = build_required_gate_summary(
            order,
            gateway_evidence=evidence,
            kill_switch=self._kill_switch_snapshot(),
        )
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "preview_ready",
            "dry_run": True,
            "submitted_to_broker": False,
            "order_id": order["order_id"],
            "actor": actor,
            "ticket": ticket,
            "validation": {
                "manual_confirmation_status": "pass",
                "gateway_evidence_status": "pass",
                "gateway_evidence": evidence,
                "controlled_bridge_policy": policy,
                "broker_submission_enabled": bool(
                    order.get("broker_submission_enabled")
                ),
                "requires_human_broker_entry": True,
                "required_gate_summary": required_gate_summary,
            },
            "limitations": [
                "This is a manual broker ticket preview, not broker API submission.",
            ],
        }

    def dry_run_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Validate order and gates, recording an audit dry-run event."""
        order = self._require_order(order_id)
        policy = self._controlled_bridge_policy_snapshot()
        try:
            if order["status"] != "manually_confirmed":
                raise ValueError(
                    "OMS order must be manually_confirmed before ticketing"
                )
            evidence = self._require_gateway_evidence(order)
            self._require_kill_switch_clear()
        except ValueError as exc:
            event = self._db.record_broker_gateway_event_sync(
                gateway_id="manual_ticket",
                event_type="manual_ticket_dry_run_rejected",
                order_id=order["order_id"],
                status="rejected",
                actor=actor,
                payload={
                    "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                    "order_status": order["status"],
                    "dry_run": True,
                    "submitted_to_broker": False,
                    "validation_result": "rejected",
                    "rejection_reason": str(exc),
                    "controlled_bridge_policy": policy,
                },
            )
            exc.add_note(f"broker_gateway_event_id={event['id']}")
            raise

        ticket = build_manual_ticket(order, policy=policy)
        required_gate_summary = build_required_gate_summary(
            order,
            gateway_evidence=evidence,
            kill_switch=self._kill_switch_snapshot(),
        )
        event = self._db.record_broker_gateway_event_sync(
            gateway_id="manual_ticket",
            event_type="manual_ticket_dry_run_accepted",
            order_id=order["order_id"],
            status="accepted",
            actor=actor,
            payload={
                "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
                "order_status": order["status"],
                "dry_run": True,
                "submitted_to_broker": False,
                "validation_result": "accepted",
                "ticket": ticket,
                "gateway_evidence": evidence,
                "controlled_bridge_policy": policy,
                "required_gate_summary": required_gate_summary,
            },
        )
        return {
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
                "controlled_bridge_policy": policy,
                "broker_submission_enabled": bool(
                    order.get("broker_submission_enabled")
                ),
                "requires_human_broker_entry": True,
                "required_gate_summary": required_gate_summary,
            },
            "limitations": [
                "This records a dry-run validation event only.",
                "It does not submit to a broker or change OMS status.",
            ],
            "event_id": event["id"],
        }

    def export_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Export copyable and downloadable manual ticket without broker submission."""
        order, evidence = self._require_gateway_ready_order(order_id)
        self._require_kill_switch_clear()
        policy = self._controlled_bridge_policy_snapshot()
        ticket = build_manual_ticket(order, policy=policy)
        required_gate_summary = build_required_gate_summary(
            order,
            gateway_evidence=evidence,
            kill_switch=self._kill_switch_snapshot(),
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
            "export": build_manual_ticket_export(
                order,
                ticket=ticket,
                gateway_evidence=evidence,
                controlled_bridge_policy=policy,
                actor=actor,
            ),
            "validation": {
                "manual_confirmation_status": "pass",
                "gateway_evidence_status": "pass",
                "gateway_evidence": evidence,
                "controlled_bridge_policy": policy,
                "broker_submission_enabled": bool(
                    order.get("broker_submission_enabled")
                ),
                "requires_human_broker_entry": True,
                "required_gate_summary": required_gate_summary,
            },
            "limitations": [
                "This prepares a copyable manual-ticket export only.",
                "It does not submit to a broker, record an event, or change OMS status.",
            ],
        }

    def create_manual_ticket(
        self,
        order_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Create a manual broker ticket and transition OMS order to manual_ticket_created."""
        order, evidence = self._require_gateway_ready_order(order_id)
        self._require_kill_switch_clear()
        policy = self._controlled_bridge_policy_snapshot()
        ticket = build_manual_ticket(order, policy=policy)

        updated = self._oms.transition_order(
            order_id,
            to_status="manual_ticket_created",
            reason="manual broker ticket created",
            actor=actor,
        )
        required_gate_summary = build_required_gate_summary(
            updated,
            gateway_evidence=evidence,
            kill_switch=self._kill_switch_snapshot(),
        )
        validation = {
            "manual_confirmation_status": "pass",
            "gateway_evidence_status": "pass",
            "gateway_evidence": evidence,
            "controlled_bridge_policy": policy,
            "broker_submission_enabled": bool(updated.get("broker_submission_enabled")),
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
                "controlled_bridge_policy": policy,
                "required_gate_summary": required_gate_summary,
                "submitted_to_broker": False,
            },
        )
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "manual_ticket_created",
            "submitted_to_broker": False,
            "controlled_bridge_policy": policy,
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
        """Preview manual fill financial impact and generate tamper-proof fingerprint."""
        order = self._require_order(order_id)
        if order["status"] != "manual_ticket_created":
            raise ValueError(
                "OMS order must be manual_ticket_created before manual execution preview"
            )
        gateway_evidence = self._require_gateway_evidence(order)
        price_decimal = clean_decimal(fill_price, "fill_price")
        quantity_decimal = clean_decimal(quantity, "quantity")
        fee_decimal = optional_decimal(fee)
        tax_decimal = optional_decimal(tax)
        transfer_fee_decimal = optional_decimal(transfer_fee)

        gross_amount, total_cost, net_cash_impact = compute_execution_cash_impact(
            side=str(order.get("side") or ""),
            fill_price=price_decimal,
            quantity=quantity_decimal,
            fee=fee_decimal,
            tax=tax_decimal,
            transfer_fee=transfer_fee_decimal,
        )

        execution_preview = {
            "source": "manual_ticket_operator_entry",
            "symbol": str(order.get("symbol") or ""),
            "side": str(order.get("side") or "").lower(),
            "asset_class": str(order.get("asset_class") or ""),
            "quantity": quantity_string(quantity_decimal),
            "fill_price": money_string(price_decimal),
            "gross_amount": money_string(gross_amount),
            "fee": money_string(fee_decimal),
            "tax": money_string(tax_decimal),
            "transfer_fee": money_string(transfer_fee_decimal),
            "total_cost": money_string(total_cost),
            "net_cash_impact": money_string(net_cash_impact),
            "currency": "CNY",
            "notes": [
                "Broker client fill and fee/tax statement remains authoritative.",
                "Preview is an operator review draft before any production ledger save.",
            ],
        }

        ledger_entry_draft = build_manual_execution_ledger_draft(
            order_id=str(order["order_id"]),
            symbol=str(execution_preview["symbol"]),
            side=str(execution_preview["side"]),
            asset_class=str(execution_preview["asset_class"]),
            quantity=str(execution_preview["quantity"]),
            fill_price=str(execution_preview["fill_price"]),
            gross_amount=str(execution_preview["gross_amount"]),
            fee=str(execution_preview["fee"]),
            tax=str(execution_preview["tax"]),
            transfer_fee=str(execution_preview["transfer_fee"]),
            net_cash_impact=str(execution_preview["net_cash_impact"]),
        )
        pos_cost_preview = build_position_cost_preview(order)
        policy = self._controlled_bridge_policy_snapshot()

        validation = {
            "manual_confirmation_status": "pass",
            "gateway_evidence_status": "pass",
            "gateway_evidence": gateway_evidence,
            "controlled_bridge_policy": policy,
            "broker_submission_enabled": bool(order.get("broker_submission_enabled")),
            "requires_human_broker_entry": True,
            "required_gate_summary": build_required_gate_summary(
                order,
                gateway_evidence=gateway_evidence,
                kill_switch=self._kill_switch_snapshot(),
            ),
        }

        preview_fingerprint = compute_preview_fingerprint(
            {
                "schema_version": MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCHEMA_VERSION,
                "order_id": order["order_id"],
                "execution_preview": execution_preview,
                "ledger_entry_draft": ledger_entry_draft,
                "position_cost_preview": pos_cost_preview,
                "controlled_bridge_policy": policy,
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
            "position_cost_preview": pos_cost_preview,
            "controlled_bridge_policy": policy,
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
        """Verify fingerprint and record immutable manual execution audit evidence."""
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
        if not verify_preview_fingerprint(preview_fingerprint, expected_fingerprint):
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

    # -------------------------------------------------------------------------
    # Internal Validation & Gate Helpers
    # -------------------------------------------------------------------------

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
        payload = order_payload(order)
        evidence = payload.get("gateway_evidence")
        if not isinstance(evidence, dict):
            evidence = {}

        missing: list[str] = []
        blocked: list[str] = []
        for key, (status_field, passing_values) in REQUIRED_GATEWAY_EVIDENCE.items():
            item = evidence.get(key)
            if not isinstance(item, dict) or not item.get("evidence_ref"):
                missing.append(key)
                continue
            status = str(item.get(status_field) or "").lower()
            if status not in passing_values:
                blocked.append(key)

        if missing:
            raise ValueError("missing gateway evidence: " + ", ".join(missing))
        if blocked:
            raise ValueError("gateway evidence not passing: " + ", ".join(blocked))

        current_confirmation = self._resolve_current_per_order_confirmation(
            order,
            evidence=evidence,
        )
        return {
            **evidence,
            "account_truth_resolution": current_confirmation["gates"]["account_truth"],
            "current_per_order_confirmation": current_confirmation,
        }

    def _resolve_current_per_order_confirmation(
        self,
        order: dict[str, Any],
        *,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        provider = self._current_per_order_confirmation_provider
        if not callable(provider):
            raise ValueError(
                "current per-order confirmation not passing: "
                "current_per_order_confirmation_provider_unavailable"
            )
        try:
            raw = provider(str(order.get("order_id") or "")) or {}
        except Exception:
            raise ValueError(
                "current per-order confirmation not passing: "
                "current_per_order_confirmation_provider_failed"
            ) from None
        source = raw if isinstance(raw, dict) else {}
        blockers = [str(item) for item in source.get("blockers") or [] if str(item)]
        if source.get("status") != "current_verified_non_authorizing_confirmation":
            blockers.append("current_per_order_confirmation_not_verified")
        if str(source.get("order_id") or "") != str(order.get("order_id") or ""):
            blockers.append("current_per_order_confirmation_order_mismatch")
        confirmation_id = str(source.get("confirmation_id") or "").lower()
        dossier_fingerprint = str(source.get("dossier_fingerprint") or "").lower()
        if not FINGERPRINT_PATTERN.fullmatch(confirmation_id):
            blockers.append("current_per_order_confirmation_id_invalid")
        if not FINGERPRINT_PATTERN.fullmatch(dossier_fingerprint):
            blockers.append("current_per_order_dossier_fingerprint_invalid")
        if source.get("unexpected_hard_blockers"):
            blockers.append("current_per_order_confirmation_unexpected_hard_blockers")
        if (
            source.get("reads_persisted_facts_only") is not True
            or source.get("provider_contact_performed") is not False
            or source.get("runtime_connector_query_performed") is not False
            or source.get("does_not_mutate_oms") is not True
            or source.get("does_not_mutate_production_ledger") is not True
            or source.get("does_not_mutate_risk") is not True
            or source.get("does_not_mutate_kill_switch") is not True
            or source.get("does_not_change_capital_authority") is not True
            or source.get("broker_submission_enabled") is not False
            or source.get("broker_cancel_enabled") is not False
            or source.get("authorizes_execution") is not False
        ):
            blockers.append("current_per_order_confirmation_boundary_invalid")

        dossier = source.get("current_dossier")
        dossier = dossier if isinstance(dossier, dict) else {}
        if (
            dossier.get("review_ready") is not True
            or dossier.get("review_status") != "review_ready_non_submitting"
            or dossier.get("review_blockers")
            or dossier.get("submission_status") != "blocked"
            or dossier.get("authorizes_execution") is not False
            or str(dossier.get("dossier_fingerprint") or "").lower()
            != dossier_fingerprint
        ):
            blockers.append("current_per_order_dossier_not_review_ready")

        gateway = dossier.get("gateway_gates")
        gateway = gateway if isinstance(gateway, dict) else {}
        current_gates = gateway.get("gates")
        current_gates = current_gates if isinstance(current_gates, dict) else {}
        if (
            gateway.get("status") != "pass"
            or gateway.get("blockers")
            or gateway.get("persisted_facts_only") is not True
            or gateway.get("provider_contact_performed") is not False
            or gateway.get("authorizes_execution") is not False
        ):
            blockers.append("current_per_order_gateway_gates_not_passing")

        normalized_gates: dict[str, dict[str, Any]] = {}
        for gate in REQUIRED_GATEWAY_EVIDENCE:
            raw_gate = evidence.get(gate)
            raw_gate = raw_gate if isinstance(raw_gate, dict) else {}
            current_gate = current_gates.get(gate)
            current_gate = current_gate if isinstance(current_gate, dict) else {}
            gate_blockers = [
                str(item) for item in current_gate.get("blockers") or [] if str(item)
            ]
            if (
                current_gate.get("status") != "pass"
                or current_gate.get("resolution_status") != "resolved_clear"
                or gate_blockers
            ):
                blockers.append(f"current_per_order_gateway_gate_not_passing:{gate}")
            if str(current_gate.get("evidence_ref") or "") != str(
                raw_gate.get("evidence_ref") or ""
            ):
                blockers.append(f"current_per_order_gateway_ref_mismatch:{gate}")
            source_fingerprint = str(
                current_gate.get("source_fingerprint") or ""
            ).lower()
            if not FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
                blockers.append(
                    f"current_per_order_gateway_source_fingerprint_invalid:{gate}"
                )
            normalized_gates[gate] = {
                "resolution_status": str(current_gate.get("resolution_status") or ""),
                "evidence_ref": str(current_gate.get("evidence_ref") or ""),
                "source_identifier": str(current_gate.get("source_identifier") or ""),
                "source_fingerprint": source_fingerprint,
                "source_recorded_at": current_gate.get("source_recorded_at"),
            }

        blockers = list(dict.fromkeys(blockers))
        if blockers:
            raise ValueError(
                "current per-order confirmation not passing: " + ", ".join(blockers)
            )
        return {
            "status": "current_verified_non_authorizing_confirmation",
            "confirmation_id": confirmation_id,
            "dossier_fingerprint": dossier_fingerprint,
            "capital_evaluation_input_fingerprint": str(
                source.get("capital_evaluation_input_fingerprint") or ""
            ),
            "prior_batch_reconciliation_fingerprint": str(
                source.get("prior_batch_reconciliation_fingerprint") or ""
            ),
            "execution_gateway_verification_fingerprint": str(
                source.get("execution_gateway_verification_fingerprint") or ""
            ),
            "gateway_source_fingerprints": {
                gate: normalized_gates[gate]["source_fingerprint"]
                for gate in REQUIRED_GATEWAY_EVIDENCE
            },
            "gates": normalized_gates,
            "persisted_facts_only": True,
            "provider_contact_performed": False,
            "authorizes_execution": False,
        }

    def _require_kill_switch_clear(self) -> None:
        kill_switch = self._kill_switch_snapshot()
        if kill_switch["status"] == "pass":
            return
        if kill_switch["status"] == "unavailable":
            raise ValueError(
                "trading controls unavailable: " + ", ".join(kill_switch["blockers"])
            )
        reason = kill_switch["reason"]
        message = "kill switch is enabled"
        if reason:
            message = f"{message}: {reason}"
        raise ValueError(message)

    def _kill_switch_snapshot(self) -> dict[str, Any]:
        return resolve_kill_switch_evidence(self._trading_controls)

    def _controlled_bridge_policy_snapshot(self) -> dict[str, Any]:
        return controlled_bridge_policy_snapshot(self._controlled_bridge_policy)

    def _staged_broker_fills_for_order(
        self, order: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not self._broker_evidence_repository_factory:
            return []
        try:
            repository = self._broker_evidence_repository_factory()
            if repository is None:
                return []
            expected_type = (
                "trade_buy" if str(order.get("side")).lower() == "buy" else "trade_sell"
            )
            symbol = str(order.get("symbol") or "")
            from decimal import Decimal

            try:
                order_quantity = Decimal(str(order.get("quantity")))
            except Exception:
                order_quantity = None

            fills: list[dict[str, Any]] = []
            for import_run in repository.list_import_runs(limit=20):
                for event in repository.list_events(import_run.import_run_id):
                    if getattr(event, "event_type", "") != expected_type:
                        continue
                    if str(getattr(event, "symbol", "")) != symbol:
                        continue
                    event_quantity = None
                    try:
                        event_quantity = Decimal(str(getattr(event, "quantity", "")))
                    except Exception:
                        pass
                    match_status = (
                        "matched"
                        if order_quantity is not None
                        and event_quantity is not None
                        and abs(order_quantity) == abs(event_quantity)
                        else "quantity_mismatch"
                    )
                    fills.append(
                        {
                            "source": "staged_broker_evidence",
                            "import_run_id": getattr(event, "import_run_id", ""),
                            "event_id": getattr(event, "event_id", ""),
                            "event_type": getattr(event, "event_type", ""),
                            "symbol": getattr(event, "symbol", ""),
                            "side": "buy"
                            if getattr(event, "event_type", "") == "trade_buy"
                            else "sell",
                            "quantity": getattr(event, "quantity", ""),
                            "price": getattr(event, "price", ""),
                            "fee": getattr(event, "fee", ""),
                            "tax": getattr(event, "tax", ""),
                            "net_amount": getattr(event, "net_amount", ""),
                            "occurred_at": getattr(event, "occurred_at", ""),
                            "match_status": match_status,
                        }
                    )
            return fills
        except Exception:
            return []
