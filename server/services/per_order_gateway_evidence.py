"""Resolve per-order gateway gate references to persisted source facts."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

PER_ORDER_GATEWAY_EVIDENCE_SCHEMA_VERSION = "karkinos.per_order_gateway_gate_summary.v2"

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REQUIRED_GATEWAY_EVIDENCE: dict[str, tuple[str, frozenset[str], str]] = {
    "account_truth": (
        "gate_status",
        frozenset({"pass", "passed"}),
        "account_truth",
    ),
    "research_evidence": (
        "gate_status",
        frozenset({"pass", "passed"}),
        "decision_action",
    ),
    "risk": ("gate_status", frozenset({"pass", "passed"}), "risk"),
    "paper_shadow": (
        "divergence_status",
        frozenset({"within_expectations"}),
        "paper_shadow",
    ),
}


def resolve_per_order_gateway_evidence(
    *,
    db: Any,
    order: dict[str, Any],
    capital_scope: dict[str, Any],
    capital_evidence_refs: list[str] | tuple[str, ...],
    account_truth_provider: Callable[[], dict[str, Any]] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve exact gate refs without contacting providers or mutating state."""

    payload = _order_payload(order)
    raw_evidence = payload.get("gateway_evidence")
    raw_evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
    capital_refs = {
        str(item).strip() for item in capital_evidence_refs or [] if str(item).strip()
    }
    gates: dict[str, Any] = {}
    blockers: list[str] = []
    resolved: dict[str, dict[str, Any]] = {}

    for gate, (
        status_field,
        passing_values,
        expected_kind,
    ) in _REQUIRED_GATEWAY_EVIDENCE.items():
        raw = raw_evidence.get(gate)
        raw = raw if isinstance(raw, dict) else {}
        raw_status = str(raw.get(status_field) or "").strip().lower()
        evidence_ref = str(raw.get("evidence_ref") or "").strip()
        gate_blockers: list[str] = []
        if not evidence_ref:
            gate_blockers.append(f"gateway_evidence_missing:{gate}")
        elif raw_status not in passing_values:
            gate_blockers.append(f"gateway_evidence_not_passing:{gate}")

        kind, separator, identifier = evidence_ref.partition(":")
        kind = kind.strip()
        identifier = identifier.strip()
        if evidence_ref and (
            separator != ":" or kind != expected_kind or not identifier
        ):
            gate_blockers.append(f"gateway_evidence_ref_format_invalid:{gate}")
        if evidence_ref and evidence_ref not in capital_refs:
            gate_blockers.append(f"gateway_evidence_capital_ref_mismatch:{gate}")

        source = _missing_source(kind=kind, identifier=identifier)
        if not gate_blockers or (
            evidence_ref and separator == ":" and kind == expected_kind and identifier
        ):
            source, source_blockers = _resolve_source(
                gate=gate,
                identifier=identifier,
                db=db,
                order=order,
                capital_scope=capital_scope,
                resolved=resolved,
                account_truth_provider=account_truth_provider,
            )
            gate_blockers.extend(source_blockers)
        gate_blockers = list(dict.fromkeys(gate_blockers))
        resolved[gate] = source
        gates[gate] = {
            "status": "pass" if not gate_blockers else "blocked",
            "raw_status": raw_status or "missing",
            "evidence_ref": evidence_ref,
            "source_kind": kind,
            "source_identifier": identifier,
            "source_fingerprint": source.get("source_fingerprint"),
            "source_recorded_at": source.get("source_recorded_at"),
            "resolution_status": source.get("resolution_status"),
            "blockers": gate_blockers,
        }
        blockers.extend(gate_blockers)

    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": PER_ORDER_GATEWAY_EVIDENCE_SCHEMA_VERSION,
        "status": "pass" if not unique_blockers else "blocked",
        "gates": gates,
        "blockers": unique_blockers,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_account_truth": True,
        "does_not_mutate_risk": True,
        "does_not_change_capital_authority": True,
        "does_not_submit_or_cancel_orders": True,
        "authorizes_execution": False,
    }, unique_blockers


def _resolve_source(
    *,
    gate: str,
    identifier: str,
    db: Any,
    order: dict[str, Any],
    capital_scope: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    account_truth_provider: Callable[[], dict[str, Any]] | None,
) -> tuple[dict[str, Any], list[str]]:
    if gate == "account_truth":
        return _resolve_account_truth(
            identifier=identifier,
            provider=account_truth_provider,
        )
    if gate == "research_evidence":
        return _resolve_decision_action(
            identifier=identifier,
            db=db,
            order=order,
            capital_scope=capital_scope,
        )
    if gate == "risk":
        return _resolve_risk(
            identifier=identifier,
            db=db,
            order=order,
            capital_scope=capital_scope,
            action_source=resolved.get("research_evidence") or {},
        )
    return _resolve_paper_shadow(
        identifier=identifier,
        db=db,
        order=order,
        capital_scope=capital_scope,
        action_source=resolved.get("research_evidence") or {},
        risk_source=resolved.get("risk") or {},
    )


def _resolve_account_truth(
    *,
    identifier: str,
    provider: Callable[[], dict[str, Any]] | None,
) -> tuple[dict[str, Any], list[str]]:
    if not callable(provider):
        return _blocked_source(
            identifier=identifier,
            blocker="gateway_evidence_provider_unavailable:account_truth",
        )
    try:
        raw = provider() or {}
    except Exception:
        return _blocked_source(
            identifier=identifier,
            blocker="gateway_evidence_provider_failed:account_truth",
        )
    source = raw if isinstance(raw, dict) else {}
    blockers: list[str] = []
    if str(source.get("import_run_id") or "") != identifier:
        blockers.append("gateway_evidence_source_identity_mismatch:account_truth")
    if source.get("status") != "clear":
        blockers.append("gateway_evidence_source_not_clear:account_truth")
    if str(source.get("gate_status") or "").lower() != "pass":
        blockers.append("gateway_evidence_source_gate_blocked:account_truth")
    if str(source.get("data_freshness_status") or "").lower() != "fresh":
        blockers.append("gateway_evidence_source_stale:account_truth")
    if str(source.get("reconciliation_status") or "").lower() not in {
        "clear",
        "pass",
    }:
        blockers.append("gateway_evidence_source_unreconciled:account_truth")
    if _integer(source.get("unresolved_mismatch_count"), fallback=-1) != 0:
        blockers.append("gateway_evidence_source_unresolved:account_truth")
    source_fingerprint = str(source.get("source_fingerprint") or "").lower()
    if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
        blockers.append("gateway_evidence_source_fingerprint_invalid:account_truth")
    if source.get("does_not_mutate_production_ledger") is not True:
        blockers.append("gateway_evidence_source_boundary_invalid:account_truth")
    if source.get("does_not_issue_execution_authority") is not True:
        blockers.append("gateway_evidence_source_boundary_invalid:account_truth")
    if source.get("broker_submission_enabled") is not False:
        blockers.append("gateway_evidence_source_boundary_invalid:account_truth")
    if source.get("persisted_facts_only") is not True:
        blockers.append("gateway_evidence_source_boundary_invalid:account_truth")
    if source.get("provider_contact_performed") is not False:
        blockers.append("gateway_evidence_source_boundary_invalid:account_truth")
    blockers = list(dict.fromkeys(blockers))
    return {
        "resolution_status": "resolved_clear" if not blockers else "resolved_blocked",
        "source_identifier": identifier,
        "source_fingerprint": source_fingerprint or None,
        "source_recorded_at": str(source.get("captured_at") or "") or None,
        "import_run_id": str(source.get("import_run_id") or ""),
    }, blockers


def _resolve_decision_action(
    *,
    identifier: str,
    db: Any,
    order: dict[str, Any],
    capital_scope: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    try:
        action_id = int(identifier)
    except (TypeError, ValueError):
        return _blocked_source(
            identifier=identifier,
            blocker="gateway_evidence_source_identity_invalid:research_evidence",
        )
    reader = getattr(db, "get_action_task_sync", None)
    action = reader(action_id) if callable(reader) else None
    if not isinstance(action, dict):
        return _blocked_source(
            identifier=identifier,
            blocker="gateway_evidence_source_not_found:research_evidence",
        )
    source_core = {
        "action_id": action.get("id"),
        "source_signal_id": action.get("source_signal_id"),
        "symbol": action.get("symbol"),
        "direction": action.get("direction"),
        "strategy_id": action.get("strategy_id"),
        "timestamp": action.get("timestamp"),
        "status": action.get("status"),
    }
    blockers: list[str] = []
    if str(action.get("symbol") or "") != str(order.get("symbol") or ""):
        blockers.append("gateway_evidence_scope_mismatch:research_evidence:symbol")
    expected_strategy = str(capital_scope.get("strategy_id") or "")
    if (
        not expected_strategy
        or str(action.get("strategy_id") or "") != expected_strategy
    ):
        blockers.append("gateway_evidence_scope_mismatch:research_evidence:strategy")
    expected_side = _direction_side(action.get("direction"))
    if expected_side != str(order.get("side") or "").lower():
        blockers.append("gateway_evidence_scope_mismatch:research_evidence:side")
    if action.get("source_signal_id") is None:
        blockers.append("gateway_evidence_lineage_missing:research_evidence:signal")
    return {
        "resolution_status": "resolved_clear" if not blockers else "resolved_blocked",
        "source_identifier": identifier,
        "source_fingerprint": _fingerprint(source_core),
        "source_recorded_at": str(action.get("timestamp") or "") or None,
        "action_id": action_id,
        "source_signal_id": action.get("source_signal_id"),
        "strategy_id": str(action.get("strategy_id") or ""),
    }, blockers


def _resolve_risk(
    *,
    identifier: str,
    db: Any,
    order: dict[str, Any],
    capital_scope: dict[str, Any],
    action_source: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    rows = db.list_events_sync(
        event_type="risk.signal.recorded",
        entity_type="risk_signal",
        entity_id=identifier,
        source="risk_decisions",
        limit=1,
    )
    if not rows:
        return _blocked_source(
            identifier=identifier,
            blocker="gateway_evidence_source_not_found:risk",
        )
    row = rows[0]
    payload = _json_object(row.get("payload_json"))
    intent = _mapping(payload.get("intent"))
    decision = _mapping(payload.get("decision"))
    source_core = {"intent": intent, "decision": decision}
    blockers: list[str] = []
    if decision.get("passed") is not True:
        blockers.append("gateway_evidence_source_not_clear:risk")
    if str(decision.get("decision_id") or "") != identifier:
        blockers.append("gateway_evidence_source_identity_mismatch:risk")
    if str(decision.get("symbol") or "") != str(order.get("symbol") or ""):
        blockers.append("gateway_evidence_scope_mismatch:risk:symbol")
    if str(decision.get("side") or "").lower() != str(order.get("side") or "").lower():
        blockers.append("gateway_evidence_scope_mismatch:risk:side")
    expected_strategy = str(capital_scope.get("strategy_id") or "")
    if (
        not expected_strategy
        or str(intent.get("strategy_id") or "") != expected_strategy
    ):
        blockers.append("gateway_evidence_scope_mismatch:risk:strategy")
    expected_signal = action_source.get("source_signal_id")
    if expected_signal is None or str(intent.get("source_signal_id") or "") != str(
        expected_signal
    ):
        blockers.append("gateway_evidence_lineage_mismatch:risk:decision_action")
    return {
        "resolution_status": "resolved_clear" if not blockers else "resolved_blocked",
        "source_identifier": identifier,
        "source_fingerprint": _fingerprint(source_core),
        "source_recorded_at": str(
            decision.get("timestamp") or row.get("timestamp") or ""
        )
        or None,
        "decision_id": str(decision.get("decision_id") or ""),
    }, blockers


def _resolve_paper_shadow(
    *,
    identifier: str,
    db: Any,
    order: dict[str, Any],
    capital_scope: dict[str, Any],
    action_source: dict[str, Any],
    risk_source: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    reader = getattr(db, "get_paper_shadow_run_sync", None)
    run = reader(identifier) if callable(reader) else None
    if not isinstance(run, dict):
        return _blocked_source(
            identifier=identifier,
            blocker="gateway_evidence_source_not_found:paper_shadow",
        )
    payload = _json_object(run.get("payload_json"))
    action_id = action_source.get("action_id")
    action_ref = f"action:{action_id}" if action_id is not None else ""
    matching_orders = [
        item
        for item in payload.get("orders") or []
        if isinstance(item, dict)
        and str(_mapping(item.get("order_intent")).get("action_ref") or "")
        == action_ref
    ]
    matching_order = matching_orders[0] if len(matching_orders) == 1 else {}
    intent = _mapping(matching_order.get("order_intent"))
    source_core = {
        "run_id": run.get("run_id"),
        "plan_date": run.get("plan_date"),
        "input_fingerprint": run.get("input_fingerprint"),
        "status": run.get("status"),
        "divergence_status": run.get("divergence_status"),
        "matching_order": matching_order,
    }
    blockers: list[str] = []
    if str(run.get("run_id") or "") != identifier:
        blockers.append("gateway_evidence_source_identity_mismatch:paper_shadow")
    if (
        str(run.get("status") or "") != "within_expectations"
        or str(run.get("divergence_status") or "") != "within_expectations"
    ):
        blockers.append("gateway_evidence_source_not_clear:paper_shadow")
    if len(matching_orders) != 1:
        blockers.append(
            "gateway_evidence_lineage_mismatch:paper_shadow:decision_action"
        )
    if (
        str(matching_order.get("status") or "") != "filled"
        or str(matching_order.get("divergence_status") or "") != "within_expectations"
    ):
        blockers.append("gateway_evidence_order_not_clear:paper_shadow")
    if str(intent.get("symbol") or "") != str(order.get("symbol") or ""):
        blockers.append("gateway_evidence_scope_mismatch:paper_shadow:symbol")
    if str(intent.get("side") or "").lower() != str(order.get("side") or "").lower():
        blockers.append("gateway_evidence_scope_mismatch:paper_shadow:side")
    if not _decimal_equal(intent.get("estimated_quantity"), order.get("quantity")):
        blockers.append("gateway_evidence_scope_mismatch:paper_shadow:quantity")
    if str(order.get("order_type") or "").lower() == "limit" and not _decimal_equal(
        intent.get("estimated_price"), order.get("limit_price")
    ):
        blockers.append("gateway_evidence_scope_mismatch:paper_shadow:limit_price")
    expected_strategy = str(capital_scope.get("strategy_id") or "")
    if f"strategy:{expected_strategy}" not in {
        str(item) for item in intent.get("strategy_refs") or []
    }:
        blockers.append("gateway_evidence_lineage_mismatch:paper_shadow:strategy")
    risk_identifier = str(risk_source.get("decision_id") or "")
    if not risk_identifier or f"risk:{risk_identifier}" not in {
        str(item) for item in intent.get("risk_refs") or []
    }:
        blockers.append("gateway_evidence_lineage_mismatch:paper_shadow:risk")
    if (
        payload.get("does_not_submit_broker_order") is not True
        or payload.get("does_not_mutate_production_ledger") is not True
    ):
        blockers.append("gateway_evidence_source_boundary_invalid:paper_shadow")
    input_fingerprint = str(run.get("input_fingerprint") or "").lower()
    if not _FINGERPRINT_PATTERN.fullmatch(input_fingerprint):
        blockers.append("gateway_evidence_source_fingerprint_invalid:paper_shadow")
    blockers = list(dict.fromkeys(blockers))
    return {
        "resolution_status": "resolved_clear" if not blockers else "resolved_blocked",
        "source_identifier": identifier,
        "source_fingerprint": _fingerprint(source_core),
        "source_recorded_at": str(run.get("updated_at") or run.get("plan_date") or "")
        or None,
        "run_id": str(run.get("run_id") or ""),
        "input_fingerprint": input_fingerprint,
        "paper_order_id": str(matching_order.get("order_id") or ""),
    }, blockers


def _missing_source(*, kind: str, identifier: str) -> dict[str, Any]:
    return {
        "resolution_status": "not_resolved",
        "source_kind": kind,
        "source_identifier": identifier,
        "source_fingerprint": None,
        "source_recorded_at": None,
    }


def _blocked_source(
    *,
    identifier: str,
    blocker: str,
) -> tuple[dict[str, Any], list[str]]:
    return {
        "resolution_status": "blocked",
        "source_identifier": identifier,
        "source_fingerprint": None,
        "source_recorded_at": None,
    }, [blocker]


def _direction_side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"buy", "increase", "add", "overweight"}:
        return "buy"
    if normalized in {"sell", "decrease", "reduce", "underweight"}:
        return "sell"
    return ""


def _order_payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = order.get("payload")
    if isinstance(payload, dict):
        return payload
    return _json_object(order.get("payload_json"))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fingerprint(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _integer(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
