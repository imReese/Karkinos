"""Shared exact binding for current non-submitting gateway verification."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

EXECUTION_GATEWAY_VERIFICATION_BINDING_SCHEMA_VERSION = (
    "karkinos.execution_gateway_verification_binding.v1"
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SAFE_RESOLUTION_BLOCKERS = frozenset(
    {
        "verification_expired",
        "verification_fingerprint_invalid",
        "verification_not_found",
        "verification_recorded_at_invalid",
        "verification_source_changed",
        "verification_currently_blocked",
    }
)


def build_execution_gateway_order_contract(order: dict[str, Any]) -> dict[str, Any]:
    """Return the sanitized order terms that a gateway dry-run must bind."""

    return {
        "symbol": str(order.get("symbol") or "").strip(),
        "side": str(order.get("side") or "").strip().lower(),
        "asset_class": str(order.get("asset_class") or "").strip().lower(),
        "quantity": _number_string(order.get("quantity")),
        "order_type": str(order.get("order_type") or "").strip().lower(),
        "limit_price": _number_string(order.get("limit_price")),
    }


def resolve_execution_gateway_verification_binding(
    provider: Callable[[str], dict[str, Any]] | None,
    *,
    fingerprint: str,
    expected_gateway_id: str,
    expected_evidence_connector_id: str,
    expected_account_alias: str,
    expected_order_id: str,
    expected_order_fingerprint: str,
    expected_order_contract: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Resolve and match one current verification without granting authority."""

    normalized = str(fingerprint or "").strip()
    if not _FINGERPRINT_PATTERN.fullmatch(normalized):
        blocker = "execution_gateway_verification_fingerprint_invalid"
        return _blocked_binding(normalized, blocker), [blocker]
    if not callable(provider):
        blocker = "execution_gateway_verification_provider_unavailable"
        return _blocked_binding(normalized, blocker), [blocker]
    try:
        raw = provider(normalized) or {}
    except Exception:
        blocker = "execution_gateway_verification_provider_failed"
        return _blocked_binding(normalized, blocker), [blocker]
    raw = raw if isinstance(raw, dict) else {}
    resolved_order_contract = (
        raw.get("order_contract") if isinstance(raw.get("order_contract"), dict) else {}
    )
    checks = (
        (raw.get("status") == "clear", "execution_gateway_verification_not_clear"),
        (
            str(raw.get("verification_fingerprint") or "") == normalized,
            "execution_gateway_verification_fingerprint_mismatch",
        ),
        (
            bool(raw.get("runtime_gateway_verified")),
            "execution_gateway_runtime_not_verified",
        ),
        (
            str(raw.get("runtime_verification_status") or "")
            == "verified_non_submitting_dry_run",
            "execution_gateway_verification_status_mismatch",
        ),
        (
            str(raw.get("gateway_id") or "") == str(expected_gateway_id or ""),
            "execution_gateway_verification_gateway_mismatch",
        ),
        (
            str(raw.get("evidence_connector_id") or "")
            == str(expected_evidence_connector_id or ""),
            "execution_gateway_verification_connector_mismatch",
        ),
        (
            str(raw.get("account_alias") or "") == str(expected_account_alias or ""),
            "execution_gateway_verification_account_mismatch",
        ),
        (
            str(raw.get("order_id") or "") == str(expected_order_id or ""),
            "execution_gateway_verification_order_mismatch",
        ),
        (
            str(raw.get("order_fingerprint") or "")
            == str(expected_order_fingerprint or ""),
            "execution_gateway_verification_order_fingerprint_mismatch",
        ),
        (
            resolved_order_contract == expected_order_contract,
            "execution_gateway_verification_order_contract_mismatch",
        ),
        (
            raw.get("runtime_execution_authority") == "disabled",
            "execution_gateway_verification_authority_not_disabled",
        ),
        (
            raw.get("broker_submission_enabled") is False,
            "execution_gateway_verification_submission_not_disabled",
        ),
        (
            raw.get("authorizes_execution") is False,
            "execution_gateway_verification_unexpected_authority",
        ),
    )
    blockers = [reason for passed, reason in checks if not passed]
    provider_blockers = raw.get("blockers")
    if raw.get("status") != "clear" and isinstance(provider_blockers, list):
        blockers.extend(
            f"execution_gateway_verification:{str(item)}"
            for item in provider_blockers
            if str(item) in _SAFE_RESOLUTION_BLOCKERS
        )
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": EXECUTION_GATEWAY_VERIFICATION_BINDING_SCHEMA_VERSION,
        "status": "pass" if not unique_blockers else "blocked",
        "verification_id": str(raw.get("verification_id") or ""),
        "verification_fingerprint": normalized,
        "gateway_id": str(raw.get("gateway_id") or ""),
        "evidence_connector_id": str(raw.get("evidence_connector_id") or ""),
        "account_alias": str(raw.get("account_alias") or ""),
        "order_id": str(raw.get("order_id") or ""),
        "order_fingerprint": str(raw.get("order_fingerprint") or ""),
        "order_contract": dict(resolved_order_contract),
        "recorded_at": str(raw.get("recorded_at") or ""),
        "runtime_gateway_verified": not unique_blockers,
        "runtime_verification_status": (
            "verified_non_submitting_dry_run" if not unique_blockers else "blocked"
        ),
        "blockers": unique_blockers,
        "runtime_execution_authority": "disabled",
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }, unique_blockers


def _blocked_binding(fingerprint: str, blocker: str) -> dict[str, Any]:
    return {
        "schema_version": EXECUTION_GATEWAY_VERIFICATION_BINDING_SCHEMA_VERSION,
        "status": "blocked",
        "verification_id": "",
        "verification_fingerprint": fingerprint,
        "gateway_id": "",
        "evidence_connector_id": "",
        "account_alias": "",
        "order_id": "",
        "order_fingerprint": "",
        "order_contract": {},
        "recorded_at": "",
        "runtime_gateway_verified": False,
        "runtime_verification_status": "blocked",
        "blockers": [blocker],
        "runtime_execution_authority": "disabled",
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }


def _number_string(value: Any) -> str | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"
