"""Projections and payload formatters for manual trading."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from domain.manual_trading import (
    clean_number,
    format_ticket_copy_text,
)
from server.contracts.broker_gateway import (
    BROKER_GATEWAY_SCHEMA_VERSION,
    CONTROLLED_BRIDGE_POLICY_SCHEMA_VERSION,
)

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
CONTROLLED_BRIDGE_REQUIRED_GATES = (
    "account_truth",
    "research_evidence",
    "risk",
    "paper_shadow",
    "manual_confirmation",
    "kill_switch_clear",
    "connector_health",
    "execution_reconciliation",
)
REQUIRED_GATEWAY_EVIDENCE: dict[str, tuple[str, set[str]]] = {
    "account_truth": ("gate_status", {"pass", "passed"}),
    "research_evidence": ("gate_status", {"pass", "passed"}),
    "risk": ("gate_status", {"pass", "passed"}),
    "paper_shadow": ("divergence_status", {"within_expectations"}),
}


def order_payload(order: dict[str, Any]) -> dict[str, Any]:
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


def first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def mapping_value(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def optional_clean_number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        return clean_number(value)
    except (TypeError, ValueError):
        return None


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def order_intent_payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = order_payload(order)
    return first_mapping(
        payload.get("order_intent"),
        payload.get("daily_trading_plan_intent"),
        payload,
    )


def operator_account_alias(policy: dict[str, Any] | None) -> str:
    if isinstance(policy, dict):
        aliases = policy.get("allowed_account_aliases")
        if isinstance(aliases, list) and aliases:
            return str(aliases[0])
    return "manual-review"


def fee_tax_assumptions(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = order_intent_payload(order)
    fee_components = mapping_value(
        source_payload.get("fee_breakdown"),
        source_payload.get("fee_components"),
    )
    return {
        "source": "oms_order_payload_or_fee_rule",
        "estimated_total_fee": optional_clean_number(
            source_payload.get("estimated_total_fee")
        ),
        "estimated_net_cash_impact": optional_clean_number(
            source_payload.get("estimated_net_cash_impact")
        ),
        "fee_rule_id": optional_string(source_payload.get("fee_rule_id")),
        "fee_rule_version": optional_string(source_payload.get("fee_rule_version")),
        "fee_components": dict(sorted(fee_components.items())),
        "notes": [
            "Broker client final fee and tax preview remains authoritative.",
            "Karkinos fee/tax values are execution-review assumptions only.",
        ],
    }


def cash_impact_preview(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = order_intent_payload(order)
    return {
        "source": "oms_order_payload_or_order_intent",
        "estimated_gross_amount": optional_clean_number(
            source_payload.get("estimated_gross_amount")
        ),
        "estimated_total_fee": optional_clean_number(
            source_payload.get("estimated_total_fee")
        ),
        "estimated_net_cash_impact": optional_clean_number(
            source_payload.get("estimated_net_cash_impact")
        ),
        "available_cash_before": optional_clean_number(
            source_payload.get("available_cash_before")
        ),
        "available_cash_after": optional_clean_number(
            source_payload.get("available_cash_after")
        ),
        "cash_status": optional_string(source_payload.get("cash_status")),
        "cash_shortfall": optional_clean_number(source_payload.get("cash_shortfall")),
    }


def position_cost_preview(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = order_intent_payload(order)
    position_effect = mapping_value(
        source_payload.get("position_effect"),
        source_payload.get("position_cost_preview"),
    )
    return {
        "source": "daily_trading_plan_position_effect",
        "current_quantity": optional_clean_number(
            position_effect.get("current_quantity")
        ),
        "current_avg_cost": optional_clean_number(
            position_effect.get("current_avg_cost")
        ),
        "current_market_value": optional_clean_number(
            position_effect.get("current_market_value")
        ),
        "estimated_quantity_after": optional_clean_number(
            position_effect.get("estimated_quantity_after")
        ),
        "estimated_avg_cost_after": optional_clean_number(
            position_effect.get("estimated_avg_cost_after")
        ),
        "cost_basis_method": optional_string(position_effect.get("cost_basis_method")),
    }


def trading_session_constraints(order: dict[str, Any]) -> dict[str, Any]:
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


def string_list(value: Any) -> list[str]:
    raw_values: tuple[Any, ...] | list[Any] | set[Any]
    if isinstance(value, str):
        raw_values = (value,)
    elif isinstance(value, list | tuple | set):
        raw_values = value
    else:
        raw_values = ()
    return sorted({str(item).strip() for item in raw_values if str(item).strip()})


def controlled_bridge_policy_snapshot(policy: Any | None) -> dict[str, Any]:
    enabled = bool(getattr(policy, "enabled", False)) if policy is not None else False
    allowed_connector_ids = string_list(
        getattr(policy, "allowed_connector_ids", ()) if policy is not None else ()
    )
    allowed_account_aliases = string_list(
        getattr(policy, "allowed_account_aliases", ()) if policy is not None else ()
    )
    allowed_strategy_ids = string_list(
        getattr(policy, "allowed_strategy_ids", ()) if policy is not None else ()
    )
    allowed_symbols = string_list(
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
            "incomplete_whitelist" if whitelist_empty else "configured_non_submitting"
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
        "required_gates": list(CONTROLLED_BRIDGE_REQUIRED_GATES),
        "blockers": blockers,
        "limitations": [
            "This is a non-submitting policy skeleton for future bridge review.",
            "It does not enable broker API submission or broker cancellation.",
            "Strategy code must not call broker adapters directly.",
        ],
    }


def manual_ticket_operator_form(
    order: dict[str, Any],
    *,
    ticket: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    account_alias = operator_account_alias(policy)
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
        "fee_tax_assumptions": fee_tax_assumptions(order),
        "cash_impact_preview": cash_impact_preview(order),
        "position_cost_preview": position_cost_preview(order),
        "trading_session_constraints": trading_session_constraints(order),
        "safety": {
            "broker_submission_enabled": False,
            "submitted_to_broker": False,
            "requires_human_broker_entry": True,
            "does_not_mutate_production_ledger": True,
        },
    }


def build_manual_ticket(
    order: dict[str, Any],
    *,
    policy: dict[str, Any],
) -> dict[str, Any]:
    side = str(order["side"]).lower()
    quantity = clean_number(order["quantity"])
    limit_price = (
        clean_number(order["limit_price"])
        if order.get("limit_price") is not None
        else None
    )
    order_type = str(order["order_type"]).lower()
    copy_text = format_ticket_copy_text(
        side=side,
        symbol=str(order["symbol"]),
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
    )
    ticket = {
        "symbol": str(order["symbol"]),
        "side": side,
        "asset_class": str(order["asset_class"]),
        "quantity": quantity,
        "order_type": order_type,
        "limit_price": limit_price,
        "copy_text": copy_text,
    }
    return {
        **ticket,
        "operator_form": manual_ticket_operator_form(
            order, ticket=ticket, policy=policy
        ),
    }


def build_manual_ticket_export(
    order: dict[str, Any],
    *,
    ticket: dict[str, Any],
    gateway_evidence: dict[str, Any],
    controlled_bridge_policy: dict[str, Any],
    actor: str | None,
) -> dict[str, Any]:
    evidence_refs = {
        key: str(gateway_evidence[key].get("evidence_ref"))
        for key in REQUIRED_GATEWAY_EVIDENCE
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
        "account_truth_resolution": gateway_evidence.get("account_truth_resolution"),
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


def build_required_gate_summary(
    order: dict[str, Any],
    *,
    gateway_evidence: dict[str, Any],
    kill_switch: dict[str, Any],
) -> dict[str, Any]:
    gates: dict[str, dict[str, Any]] = {}
    for gate in ("account_truth", "research_evidence", "risk", "paper_shadow"):
        evidence = gateway_evidence.get(gate)
        if isinstance(evidence, dict):
            status_field, passing_values = REQUIRED_GATEWAY_EVIDENCE[gate]
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
    for gate in REQUIRED_GATEWAY_EVIDENCE:
        resolution = current_gates.get(gate)
        if not isinstance(resolution, dict):
            continue
        gates[gate] = {
            **gates[gate],
            "source": "current_per_order_confirmation",
            "confirmation_id": str(current_confirmation.get("confirmation_id") or ""),
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
        "required_gates": list(CONTROLLED_BRIDGE_REQUIRED_GATES),
        "gates": gates,
        "broker_submission_enabled": False,
        "submitted_to_broker": False,
        "does_not_authorize_execution": True,
    }


build_position_cost_preview = position_cost_preview
