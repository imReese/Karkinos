"""Response projection helpers for persisted controlled-session live gates."""

from __future__ import annotations

from typing import Any

from server.services.controlled_session_automatic_trading_gate import (
    automatic_trading_gate_blockers,
)
from server.services.controlled_session_live_gate_values import (
    json_list,
    json_object,
    mapping,
    safety_flags,
)


def snapshot_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "snapshot_id": str(row.get("snapshot_id") or payload.get("snapshot_id") or ""),
        "snapshot_fingerprint": str(
            row.get("snapshot_fingerprint") or payload.get("snapshot_fingerprint") or ""
        ),
        "session_id": str(row.get("session_id") or payload.get("session_id") or ""),
        "observed_at": str(row.get("observed_at") or payload.get("observed_at") or ""),
        "status": str(row.get("status") or payload.get("status") or "blocked"),
        "gate_snapshot": json_object(
            row.get("gate_snapshot_json") or payload.get("gate_snapshot") or {}
        ),
        "source_evidence": json_object(
            row.get("source_evidence_json") or payload.get("source_evidence") or {}
        ),
        "blockers": json_list(
            row.get("blockers_json") or payload.get("blockers") or []
        ),
        "persisted": bool(row),
        "reused": reused,
        "broker_submission_enabled": False,
        "safety": safety_flags(),
    }


def nested_gate_status(order: dict[str, Any], gate: str) -> str:
    gateway_gates = mapping(order.get("gateway_gates"))
    gates = mapping(gateway_gates.get("gates"))
    item = mapping(gates.get(gate))
    return str(item.get("status") or "missing").lower()


def gate_blockers(gates: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    expected = {
        "account_truth_status": {"pass", "clear"},
        "risk_gate_status": {"pass", "passed"},
        "reconciliation_status": {"clear", "manually_accepted"},
        "paper_shadow_status": {"within_expectations", "manually_accepted"},
        "gateway_health_status": {"healthy"},
        "market_data_status": {"current", "confirmed", "live"},
        "budget_status": {"current_reserved", "current_reserved_non_executing"},
        "rate_limit_status": {"clear"},
    }
    for field, passing in expected.items():
        if gates.get(field) not in passing:
            blockers.append(f"live_gate_not_clear:{field}")
    if gates.get("kill_switch_enabled") is not False:
        blockers.append("live_gate_kill_switch_not_clear")
    blockers.extend(automatic_trading_gate_blockers(gates))
    for field in (
        "budget_exhausted",
        "daily_loss_limit_reached",
        "drawdown_limit_reached",
        "rejection_spike",
        "unexpected_account_change",
    ):
        if gates.get(field) is not False:
            blockers.append(f"live_gate_boolean_fact_not_clear:{field}")
    consecutive = gates.get("consecutive_errors")
    maximum = gates.get("max_consecutive_errors")
    if (
        not isinstance(consecutive, int)
        or not isinstance(maximum, int)
        or consecutive < 0
        or maximum <= 0
        or consecutive >= maximum
    ):
        blockers.append("live_gate_consecutive_error_limit_not_clear")
    return blockers


def missing_gate_values() -> dict[str, Any]:
    return {
        "source_fingerprint": "",
        "account_truth_status": "missing",
        "risk_gate_status": "missing",
        "reconciliation_status": "missing",
        "paper_shadow_status": "missing",
        "gateway_health_status": "missing",
        "market_data_status": "missing",
        "budget_status": "missing",
        "rate_limit_status": "missing",
        "kill_switch_enabled": None,
        "automatic_trading_status": "unavailable",
        "automatic_trading_configured_enabled": None,
        "automatic_trading_enabled": False,
        "automatic_trading_revision": None,
        "automatic_trading_control_fingerprint": "",
        "automatic_trading_blockers": ["automatic_trading_control_missing"],
        "budget_exhausted": None,
        "daily_loss_limit_reached": None,
        "drawdown_limit_reached": None,
        "rejection_spike": None,
        "unexpected_account_change": None,
        "consecutive_errors": None,
        "max_consecutive_errors": None,
    }


def missing_snapshot(session_id: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.controlled_session_live_gate_snapshot.v2",
        "status": "blocked",
        "session_id": session_id,
        "gate_snapshot": missing_gate_values(),
        "blockers": list(dict.fromkeys(blockers)),
        "resolution_status": "missing",
        "resolution_blockers": list(dict.fromkeys(blockers)),
        "persisted": False,
        "broker_submission_enabled": False,
        "safety": safety_flags(),
    }


__all__ = [
    "gate_blockers",
    "missing_gate_values",
    "missing_snapshot",
    "nested_gate_status",
    "snapshot_response",
]
