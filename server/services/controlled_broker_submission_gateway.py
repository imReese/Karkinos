"""Gateway capability, health, and side-effect-free dry-run evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_GATEWAY_HEALTH_MAX_AGE_SECONDS,
    REQUIRED_CAPABILITIES,
)
from server.services.controlled_broker_submission_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_broker_submission_values import (
    parse_timestamp as _parse_timestamp,
)


def capabilities(gateway: Any | None) -> tuple[dict[str, bool], list[str]]:
    raw = getattr(gateway, "capabilities", {}) if gateway is not None else {}
    result = {
        field: bool(
            raw.get(field) if isinstance(raw, dict) else getattr(raw, field, False)
        )
        for field in REQUIRED_CAPABILITIES
    }
    blockers = [
        f"controlled_broker_submit_capability_missing:{field}"
        for field, enabled in result.items()
        if not enabled
    ]
    return result, blockers


def health(gateway: Any | None, *, now: datetime) -> tuple[dict[str, Any], list[str]]:
    getter = getattr(gateway, "get_health", None)
    if not callable(getter):
        return missing_health(), ["controlled_broker_submit_health_unavailable"]
    try:
        raw = getter() or {}
    except Exception:
        return missing_health(), ["controlled_broker_submit_health_failed"]
    raw = raw if isinstance(raw, dict) else {}
    captured_at = _parse_timestamp(raw.get("captured_at"))
    source_fingerprint = str(raw.get("source_fingerprint") or "")
    blockers: list[str] = []
    if raw.get("status") != "healthy":
        blockers.append("controlled_broker_submit_gateway_unhealthy")
    if captured_at is None:
        blockers.append("controlled_broker_submit_health_timestamp_invalid")
        age_seconds = None
    else:
        age = (now - captured_at).total_seconds()
        age_seconds = int(max(0, age))
        if age < -30:
            blockers.append("controlled_broker_submit_health_timestamp_future")
        elif age > CONTROLLED_BROKER_GATEWAY_HEALTH_MAX_AGE_SECONDS:
            blockers.append("controlled_broker_submit_health_stale")
    if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
        blockers.append("controlled_broker_submit_health_fingerprint_invalid")
    return {
        "status": str(raw.get("status") or "missing"),
        "captured_at": captured_at.isoformat() if captured_at else "",
        "source_fingerprint": source_fingerprint,
        "age_seconds": age_seconds,
    }, blockers


def missing_health() -> dict[str, Any]:
    return {
        "status": "missing",
        "captured_at": "",
        "source_fingerprint": "",
        "age_seconds": None,
    }


def dry_run(
    gateway: Any | None,
    order: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    runner = getattr(gateway, "dry_run_order", None)
    if not callable(runner):
        return missing_dry_run(), ["controlled_broker_submit_dry_run_unavailable"]
    try:
        raw = runner(dict(order)) or {}
    except Exception:
        return missing_dry_run(), ["controlled_broker_submit_dry_run_failed"]
    raw = raw if isinstance(raw, dict) else {}
    result = {
        "status": str(raw.get("status") or ""),
        "order_fingerprint": str(raw.get("order_fingerprint") or ""),
        "client_order_id": str(raw.get("client_order_id") or ""),
        "payload_fingerprint": str(raw.get("payload_fingerprint") or ""),
        "submitted": raw.get("submitted") is True,
        "broker_order_id": str(raw.get("broker_order_id") or ""),
        "side_effect_count": int(raw.get("side_effect_count") or 0),
    }
    blockers: list[str] = []
    if result["status"] not in {"accepted", "pass"}:
        blockers.append("controlled_broker_submit_dry_run_not_accepted")
    if result["order_fingerprint"] != order["order_fingerprint"]:
        blockers.append("controlled_broker_submit_dry_run_order_mismatch")
    if result["client_order_id"] != order["client_order_id"]:
        blockers.append("controlled_broker_submit_dry_run_client_id_mismatch")
    if not _FINGERPRINT_PATTERN.fullmatch(result["payload_fingerprint"]):
        blockers.append("controlled_broker_submit_dry_run_payload_invalid")
    if result["submitted"] or result["broker_order_id"] or result["side_effect_count"]:
        blockers.append("controlled_broker_submit_dry_run_had_side_effect")
    return result, blockers


def missing_dry_run() -> dict[str, Any]:
    return {
        "status": "missing",
        "order_fingerprint": "",
        "client_order_id": "",
        "payload_fingerprint": "",
        "submitted": False,
        "broker_order_id": "",
        "side_effect_count": 0,
    }
