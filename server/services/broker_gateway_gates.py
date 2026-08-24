"""Fail-closed authority and evidence gates for broker gateway workflows."""

from __future__ import annotations

from typing import Any

from server.contracts.broker_gateway import (
    CONTROLLED_BRIDGE_POLICY_SCHEMA_VERSION,
)
from server.services.broker_gateway_values import (
    CONTROLLED_BRIDGE_REQUIRED_GATES as _CONTROLLED_BRIDGE_REQUIRED_GATES,
)
from server.services.broker_gateway_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.broker_gateway_values import (
    REQUIRED_GATEWAY_EVIDENCE as _REQUIRED_GATEWAY_EVIDENCE,
)
from server.services.broker_gateway_values import order_payload as _order_payload
from server.services.broker_gateway_values import string_list as _string_list


class BrokerGatewayGateMixin:
    """Validate persisted evidence without granting broker-write authority."""

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
        if not _FINGERPRINT_PATTERN.fullmatch(confirmation_id):
            blockers.append("current_per_order_confirmation_id_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(dossier_fingerprint):
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
        capital = dossier.get("capital_evaluation")
        capital = capital if isinstance(capital, dict) else {}
        if (
            capital.get("status") != "pass"
            or capital.get("mode") != "manual_each_order"
            or capital.get("does_not_enable_execution") is not True
        ):
            blockers.append("current_per_order_capital_evaluation_not_passing")

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
        for gate in _REQUIRED_GATEWAY_EVIDENCE:
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
            if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
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
                for gate in _REQUIRED_GATEWAY_EVIDENCE
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
        current_confirmation = gateway_evidence.get("current_per_order_confirmation")
        current_confirmation = (
            current_confirmation if isinstance(current_confirmation, dict) else {}
        )
        current_gates = current_confirmation.get("gates")
        current_gates = current_gates if isinstance(current_gates, dict) else {}
        for gate in _REQUIRED_GATEWAY_EVIDENCE:
            resolution = current_gates.get(gate)
            if not isinstance(resolution, dict):
                continue
            gates[gate] = {
                **gates[gate],
                "source": "current_per_order_confirmation",
                "confirmation_id": str(
                    current_confirmation.get("confirmation_id") or ""
                ),
                "dossier_fingerprint": str(
                    current_confirmation.get("dossier_fingerprint") or ""
                ),
                "source_fingerprint": str(resolution.get("source_fingerprint") or ""),
                "source_recorded_at": resolution.get("source_recorded_at"),
                "resolution_status": str(resolution.get("resolution_status") or ""),
            }
        gates["manual_confirmation"] = {
            "status": "pass",
            "evidence_ref": (
                f"oms_order:{order['order_id']}:{order.get('status') or 'unknown'}"
            ),
            "source": "oms_status",
        }
        kill_switch_gate = {
            "status": "pass" if kill_switch["status"] == "pass" else "blocked",
            "evidence_ref": kill_switch["evidence_ref"],
            "source": "trading_controls_snapshot",
        }
        if kill_switch["status"] == "unavailable":
            kill_switch_gate["evidence_status"] = "unavailable"
            kill_switch_gate["blockers"] = list(kill_switch["blockers"])
        gates["kill_switch_clear"] = kill_switch_gate
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
