"""Stable contracts for evidence-only per-order confirmation."""

PER_ORDER_DOSSIER_SCHEMA_VERSION = "karkinos.per_order_confirmation_dossier.v5"
PER_ORDER_CONFIRMATION_SCHEMA_VERSION = "karkinos.per_order_confirmation.v4"
PER_ORDER_CONFIRMATION_EVENT_TYPE = "controlled_bridge.per_order_confirmed"
PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE = "per_order_confirmation"
PER_ORDER_CONFIRMATION_EVENT_SOURCE = "controlled_bridge_confirmation"
PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT = (
    "confirm_exact_non_submitting_dossier_for_review"
)
PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS = 900
