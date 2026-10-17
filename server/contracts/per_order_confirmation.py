"""Stable contracts for evidence-only per-order confirmation."""

from __future__ import annotations

from typing import Any, Mapping

PER_ORDER_DOSSIER_SCHEMA_PREFIX = "karkinos.per_order_confirmation_dossier."
PER_ORDER_DOSSIER_SCHEMA_VERSION = "karkinos.per_order_confirmation_dossier.v5"
PER_ORDER_CONFIRMATION_SCHEMA_PREFIX = "karkinos.per_order_confirmation."
PER_ORDER_CONFIRMATION_SCHEMA_VERSION = "karkinos.per_order_confirmation.v4"
PER_ORDER_CONFIRMATION_EVENT_TYPE = "controlled_bridge.per_order_confirmed"
PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE = "per_order_confirmation"
PER_ORDER_CONFIRMATION_EVENT_SOURCE = "controlled_bridge_confirmation"
PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT = (
    "confirm_exact_non_submitting_dossier_for_review"
)
PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS = 900


def validate_per_order_dossier_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("per_order_dossier_payload_must_be_mapping")
    schema_version = str(payload.get("schema_version") or "")
    if not schema_version.startswith(PER_ORDER_DOSSIER_SCHEMA_PREFIX):
        raise ValueError(
            f"per_order_dossier_schema_incompatible: expected prefix {PER_ORDER_DOSSIER_SCHEMA_PREFIX}, got {schema_version}"
        )
    required = (
        "order",
        "order_fingerprint",
        "dossier_fingerprint",
        "generated_at",
        "submission_status",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"per_order_dossier_missing_fields: {missing}")
    return dict(payload)


def validate_per_order_confirmation_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("per_order_confirmation_payload_must_be_mapping")
    schema_version = str(payload.get("schema_version") or "")
    if not schema_version.startswith(PER_ORDER_CONFIRMATION_SCHEMA_PREFIX):
        raise ValueError(
            f"per_order_confirmation_schema_incompatible: expected prefix {PER_ORDER_CONFIRMATION_SCHEMA_PREFIX}, got {schema_version}"
        )
    return dict(payload)
