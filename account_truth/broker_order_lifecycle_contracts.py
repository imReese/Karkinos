"""Contracts for broker order-lifecycle evidence ingestion."""

from __future__ import annotations

BROKER_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_export.v1"
)
BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_preview.v1"
)
BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_evidence.v1"
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_BINDING_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_collector_binding.v1"
)
BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT = (
    "record_broker_order_lifecycle_evidence_without_execution_authority"
)
DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 120
MAX_EXPORT_BYTES = 2 * 1024 * 1024

BROKER_ORDER_LIFECYCLE_ORDER_STATUSES = frozenset(
    {
        "submitted",
        "open",
        "partially_filled",
        "filled",
        "cancelled",
        "rejected",
    }
)
BROKER_ORDER_LIFECYCLE_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "provider",
        "snapshot_kind",
        "gateway_id",
        "account_id",
        "account_alias",
        "captured_at",
        "source_sequence",
        "orders",
        "fills",
    }
)
BROKER_ORDER_LIFECYCLE_ORDER_FIELDS = frozenset(
    {
        "broker_order_id",
        "client_order_id",
        "symbol",
        "side",
        "status",
        "order_quantity",
        "cumulative_filled_quantity",
        "cancelled_quantity",
        "average_fill_price",
        "submitted_at",
        "updated_at",
    }
)
BROKER_ORDER_LIFECYCLE_FILL_FIELDS = frozenset(
    {
        "broker_trade_id",
        "broker_order_id",
        "client_order_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "fee",
        "tax",
        "transfer_fee",
        "net_amount",
        "filled_at",
    }
)
BROKER_ORDER_LIFECYCLE_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
)


def broker_order_lifecycle_safety_flags() -> dict[str, bool]:
    """Return the immutable non-authority claims shared by every projection."""

    return {
        "explicit_ingestion_required": True,
        "provider_contacted": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_release_submission_interlock": True,
        "authorizes_execution": False,
    }
