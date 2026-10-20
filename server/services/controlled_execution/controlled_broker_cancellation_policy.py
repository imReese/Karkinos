"""Pure gateway, release, and result policy for broker cancellation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from server.contracts.controlled_broker_cancellation import (
    CANCEL_RESULT_STATUSES,
    CONTROLLED_BROKER_CANCELLATION_GATEWAY_HEALTH_MAX_AGE_SECONDS,
    FINGERPRINT_PATTERN,
    QUERY_RESULT_STATUSES,
    REQUIRED_RELEASE_ASSERTIONS,
    cancellation_decimal_string,
    cancellation_mapping,
    parse_cancellation_timestamp,
)


def resolve_controlled_broker_cancellation_gateway(
    gateways: list[Any] | tuple[Any, ...],
    gateway_id: str,
) -> tuple[Any | None, list[str]]:
    """Resolve exactly one write gateway by stable identity."""

    matches = [
        item
        for item in gateways
        if str(getattr(item, "gateway_id", "") or "") == gateway_id
    ]
    if not matches:
        return None, ["controlled_broker_cancel_gateway_not_registered"]
    if len(matches) > 1:
        return None, ["controlled_broker_cancel_gateway_id_duplicated"]
    return matches[0], []


def controlled_broker_cancellation_capabilities(
    gateway: Any | None,
) -> tuple[dict[str, bool], list[str]]:
    """Validate the narrow cancel/query/idempotency capability set."""

    raw = getattr(gateway, "capabilities", {}) if gateway is not None else {}
    values = {
        field: bool(
            raw.get(field) if isinstance(raw, dict) else getattr(raw, field, False)
        )
        for field in (
            "can_cancel_orders",
            "can_query_orders",
            "supports_idempotent_client_order_id",
        )
    }
    blockers = [
        f"controlled_broker_cancel_capability_missing:{field}"
        for field, value in values.items()
        if not value
    ]
    if gateway is not None and not callable(getattr(gateway, "cancel_order", None)):
        blockers.append("controlled_broker_cancel_method_missing")
    if gateway is not None and not callable(getattr(gateway, "query_order", None)):
        blockers.append("controlled_broker_cancel_query_method_missing")
    return values, blockers


def controlled_broker_cancellation_gateway_health(
    gateway: Any | None,
    *,
    now: datetime,
) -> tuple[dict[str, Any], list[str]]:
    """Project cached gateway health without performing provider I/O."""

    getter = getattr(gateway, "get_health", None)
    if not callable(getter):
        return controlled_broker_cancellation_missing_health(), [
            "controlled_broker_cancel_health_unavailable"
        ]
    try:
        value = getter() or {}
    except Exception:
        return controlled_broker_cancellation_missing_health(), [
            "controlled_broker_cancel_health_failed"
        ]
    raw = value if isinstance(value, dict) else {}
    captured_at = parse_cancellation_timestamp(raw.get("captured_at"))
    source_fingerprint = str(raw.get("source_fingerprint") or "")
    blockers: list[str] = []
    if raw.get("status") != "healthy":
        blockers.append("controlled_broker_cancel_gateway_unhealthy")
    if captured_at is None:
        blockers.append("controlled_broker_cancel_health_timestamp_invalid")
        age_seconds = None
    else:
        age = (now - captured_at).total_seconds()
        age_seconds = int(max(0, age))
        if age < -30:
            blockers.append("controlled_broker_cancel_health_timestamp_future")
        elif age > CONTROLLED_BROKER_CANCELLATION_GATEWAY_HEALTH_MAX_AGE_SECONDS:
            blockers.append("controlled_broker_cancel_health_stale")
    if not FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
        blockers.append("controlled_broker_cancel_health_fingerprint_invalid")
    return {
        "status": str(raw.get("status") or "missing"),
        "captured_at": captured_at.isoformat() if captured_at else "",
        "source_fingerprint": source_fingerprint,
        "age_seconds": age_seconds,
    }, list(dict.fromkeys(blockers))


def resolve_controlled_broker_cancellation_release(
    release_evidence_provider: Callable[[str], dict[str, Any]] | None,
    release_evidence_id: str,
    *,
    expected_gateway_id: str,
    expected_account_alias: str,
    now: datetime,
) -> dict[str, Any]:
    """Validate one exact, current manual-only write release."""

    blockers: list[str] = []
    if not callable(release_evidence_provider):
        raw: dict[str, Any] = {}
        blockers.append("controlled_broker_cancel_release_provider_unavailable")
    else:
        try:
            value = release_evidence_provider(release_evidence_id) or {}
        except Exception:
            value = {}
            blockers.append("controlled_broker_cancel_release_provider_failed")
        raw = value if isinstance(value, dict) else {}
    evidence_fingerprint = str(raw.get("evidence_fingerprint") or "")
    if raw.get("status") != "current_clear_signed_release":
        blockers.append("controlled_broker_cancel_release_not_current")
    if str(raw.get("release_evidence_id") or "") != release_evidence_id:
        blockers.append("controlled_broker_cancel_release_identity_mismatch")
    if not FINGERPRINT_PATTERN.fullmatch(evidence_fingerprint):
        blockers.append("controlled_broker_cancel_release_fingerprint_invalid")
    if str(raw.get("gateway_id") or "") != expected_gateway_id:
        blockers.append("controlled_broker_cancel_release_gateway_mismatch")
    if str(raw.get("account_alias") or "") != expected_account_alias:
        blockers.append("controlled_broker_cancel_release_account_mismatch")
    if raw.get("operator_identity_verified") is not True:
        blockers.append("controlled_broker_cancel_release_operator_unverified")
    if raw.get("execution_mode") != "manual_each_order":
        blockers.append("controlled_broker_cancel_release_mode_invalid")
    if raw.get("automatic_execution_allowed") is not False:
        blockers.append("controlled_broker_cancel_release_automatic_mode_invalid")
    if raw.get("strategy_direct_submission_allowed") is not False:
        blockers.append("controlled_broker_cancel_release_strategy_path_invalid")
    for field in REQUIRED_RELEASE_ASSERTIONS:
        if raw.get(field) is not True:
            blockers.append(f"controlled_broker_cancel_release_{field}_missing")
    effective_at = parse_cancellation_timestamp(raw.get("effective_at"))
    expires_at = parse_cancellation_timestamp(raw.get("expires_at"))
    if effective_at is None or expires_at is None or expires_at <= effective_at:
        blockers.append("controlled_broker_cancel_release_window_invalid")
    elif now < effective_at or now >= expires_at:
        blockers.append("controlled_broker_cancel_release_not_effective")
    return {
        "status": "clear" if not blockers else "blocked",
        "release_evidence_id": release_evidence_id,
        "evidence_fingerprint": evidence_fingerprint,
        "gateway_id": str(raw.get("gateway_id") or ""),
        "account_alias": str(raw.get("account_alias") or ""),
        "effective_at": str(raw.get("effective_at") or ""),
        "expires_at": str(raw.get("expires_at") or ""),
        "blockers": list(dict.fromkeys(blockers)),
    }


def classify_controlled_broker_cancel_result(
    result: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> str:
    """Classify one sanitized gateway response without granting authority."""

    identity = cancellation_mapping(expected.get("identity"))
    exact = (
        str(result.get("client_order_id") or "")
        == str(identity.get("client_order_id") or "")
        and str(result.get("broker_order_id") or "")
        == str(identity.get("broker_order_id") or "")
        and str(result.get("cancel_command_id") or "")
        == str(expected.get("cancel_command_id") or "")
        and str(result.get("command_fingerprint") or "")
        == str(expected.get("cancel_fingerprint") or "")
    )
    status = str(result.get("status") or "")
    if exact and status in {
        "accepted",
        "requested",
        "cancel_pending",
        "cancelled",
        "partial_cancelled",
        "reused",
    }:
        return "cancel_requested"
    if (
        exact
        and result.get("definitive") is True
        and status
        in {
            "rejected",
            "blocked",
            "not_found",
        }
    ):
        return "cancel_rejected"
    return "cancellation_unknown"


def sanitize_controlled_broker_cancel_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Allowlist gateway cancel telemetry before persistence."""

    status = str(raw.get("status") or "")
    return {
        "status": status if status in CANCEL_RESULT_STATUSES else "unknown",
        "client_order_id": str(raw.get("client_order_id") or ""),
        "broker_order_id": str(raw.get("broker_order_id") or ""),
        "cancel_command_id": str(raw.get("cancel_command_id") or ""),
        "command_fingerprint": str(raw.get("command_fingerprint") or ""),
        "filled_quantity": cancellation_decimal_string(raw.get("filled_quantity")),
        "cancelled_quantity": cancellation_decimal_string(
            raw.get("cancelled_quantity")
        ),
        "definitive": raw.get("definitive") is True,
        "error_type": str(raw.get("error_type") or "")[:128],
        "reason": str(raw.get("reason") or "")[:256],
    }


def sanitize_controlled_broker_query_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Allowlist gateway query telemetry before persistence."""

    status = str(raw.get("status") or "")
    return {
        "status": status if status in QUERY_RESULT_STATUSES else "unknown",
        "client_order_id": str(raw.get("client_order_id") or ""),
        "broker_order_id": str(raw.get("broker_order_id") or ""),
        "order_fingerprint": str(raw.get("order_fingerprint") or ""),
        "filled_quantity": cancellation_decimal_string(raw.get("filled_quantity")),
        "cancelled_quantity": cancellation_decimal_string(
            raw.get("cancelled_quantity")
        ),
        "definitive": raw.get("definitive") is True,
        "error_type": str(raw.get("error_type") or "")[:128],
        "reason": str(raw.get("reason") or "")[:256],
    }


def controlled_broker_cancellation_missing_health() -> dict[str, Any]:
    """Return an explicit missing-health projection."""

    return {
        "status": "missing",
        "captured_at": "",
        "source_fingerprint": "",
        "age_seconds": None,
    }
