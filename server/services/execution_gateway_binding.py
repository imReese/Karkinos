"""Sanitized execution-gateway identity binding without runtime authority."""

from __future__ import annotations

from typing import Any


def build_execution_gateway_binding(
    *,
    gateway_id: object,
    health_status: object,
    can_submit_orders: object,
    account_binding_status: object,
) -> tuple[dict[str, Any], list[str]]:
    """Bind declared gateway facts while keeping runtime verification blocked."""

    normalized_gateway_id = str(gateway_id or "")
    normalized_health = str(health_status or "")
    normalized_account_binding = str(account_binding_status or "")
    can_submit = can_submit_orders is True
    blockers: list[str] = []
    if not normalized_gateway_id:
        blockers.append("execution_gateway_id_missing")
    if normalized_health != "healthy":
        blockers.append("execution_gateway_not_healthy")
    if not can_submit:
        blockers.append("execution_gateway_submit_capability_unavailable")
    if normalized_account_binding != "verified":
        blockers.append("connector_account_binding_not_verified")
    blockers.append("execution_gateway_runtime_not_verified")
    return {
        "schema_version": "karkinos.execution_gateway_binding.v1",
        "gateway_id": normalized_gateway_id,
        "declared_health_status": normalized_health,
        "declared_can_submit_orders": can_submit,
        "account_binding_status": normalized_account_binding,
        "runtime_verification_status": "unverified",
        "broker_contacted": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }, list(dict.fromkeys(blockers))
