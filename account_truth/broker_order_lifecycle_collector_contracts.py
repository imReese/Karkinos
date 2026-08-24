"""Contracts for broker order-lifecycle collector batches."""

from __future__ import annotations

BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_collector_batch.v1"
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_collector_preview.v1"
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_collector_run.v1"
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT = (
    "ingest_broker_order_lifecycle_collector_batch_without_execution_authority"
)
MAX_COLLECTOR_BATCH_BYTES = 4 * 1024 * 1024

BROKER_ORDER_LIFECYCLE_COLLECTOR_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "collector_id",
        "deployment_id",
        "collector_version",
        "deployment_fingerprint",
        "release_evidence_ref",
        "release_review_status",
        "adapter_authorization_ref",
        "provider",
        "gateway_id",
        "account_id",
        "account_alias",
        "collection_mode",
        "source_contact_status",
        "connection_status",
        "batch_status",
        "cursor",
        "captured_at",
        "event_count",
        "callbacks_received",
        "duplicate_callbacks_dropped",
        "out_of_order_callbacks_dropped",
        "lifecycle",
    }
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_CURSOR_FIELDS = frozenset({"previous", "current"})
BROKER_ORDER_LIFECYCLE_COLLECTOR_COLLECTION_MODES = frozenset(
    {"callback", "poll", "replay", "fixture"}
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_SOURCE_CONTACT_STATUSES = frozenset(
    {"not_contacted", "read_only_contact", "unknown"}
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_CONNECTION_STATUSES = frozenset(
    {"connected", "disconnected", "not_applicable"}
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_STATUSES = frozenset({"complete", "partial"})
BROKER_ORDER_LIFECYCLE_COLLECTOR_RELEASE_REVIEW_STATUSES = frozenset(
    {"unreviewed", "reviewed"}
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
)
