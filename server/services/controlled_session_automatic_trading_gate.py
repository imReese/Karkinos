"""Automatic-trading evidence projected into controlled-session live gates."""

from __future__ import annotations

from typing import Any

from server.services.controlled_session_live_gate_values import is_fingerprint


def automatic_trading_gate_values(value: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized automatic-gate fields stored in one live snapshot."""

    return {
        "automatic_trading_status": str(value.get("status") or "unavailable"),
        "automatic_trading_configured_enabled": value.get("configured_enabled"),
        "automatic_trading_enabled": value.get("enabled"),
        "automatic_trading_revision": value.get("revision"),
        "automatic_trading_control_fingerprint": str(
            value.get("control_fingerprint") or ""
        ),
        "automatic_trading_blockers": [
            str(item) for item in value.get("blockers") or []
        ],
    }


def automatic_trading_gate_blockers(gates: dict[str, Any]) -> list[str]:
    """Return fail-closed blockers for one normalized automatic gate."""

    blockers: list[str] = []
    if (
        gates.get("automatic_trading_status") != "enabled"
        or gates.get("automatic_trading_configured_enabled") is not True
        or gates.get("automatic_trading_enabled") is not True
    ):
        blockers.append("live_gate_automatic_trading_not_enabled")
    revision = gates.get("automatic_trading_revision")
    fingerprint = str(gates.get("automatic_trading_control_fingerprint") or "")
    if type(revision) is not int or revision <= 0 or not is_fingerprint(fingerprint):
        blockers.append("live_gate_automatic_trading_identity_invalid")
    return blockers


def automatic_trading_gate_evidence(value: dict[str, Any]) -> dict[str, Any]:
    """Return the allowlisted source evidence for the automatic gate."""

    return {
        "schema_version": str(value.get("schema_version") or ""),
        "status": str(value.get("status") or "unavailable"),
        "configured_enabled": value.get("configured_enabled"),
        "enabled": value.get("enabled"),
        "revision": value.get("revision"),
        "control_fingerprint": str(value.get("control_fingerprint") or ""),
        "effective_at": str(value.get("effective_at") or ""),
        "expires_at": str(value.get("expires_at") or ""),
        "updated_at": str(value.get("updated_at") or ""),
        "blockers": [str(item) for item in value.get("blockers") or []],
    }
