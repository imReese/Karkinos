"""Explicit offline migration for the retired QMT lifecycle export v1 schema.

This module is compatibility-only.  It does not import a QMT SDK, contact a
broker, or register a runtime adapter.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION,
    MAX_EXPORT_BYTES,
)

LEGACY_QMT_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION = (
    "karkinos.qmt_order_lifecycle_export.v1"
)


class LegacyQmtOrderLifecycleMigrationRejected(ValueError):
    """Raised when a legacy file cannot be converted without guessing."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__("legacy QMT order-lifecycle export migration rejected")
        self.blockers = list(dict.fromkeys(blockers))


def migrate_legacy_qmt_order_lifecycle_export_v1(
    content: str | bytes,
) -> bytes:
    """Convert one legacy file to the broker-neutral canonical export schema."""

    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    blockers: list[str] = []
    if len(raw) > MAX_EXPORT_BYTES:
        blockers.append("legacy_qmt_order_lifecycle_export_too_large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        blockers.append("legacy_qmt_order_lifecycle_export_not_utf8")
        text = ""
    try:
        parsed: Any = json.loads(text) if text else None
    except json.JSONDecodeError:
        blockers.append("legacy_qmt_order_lifecycle_json_invalid")
        parsed = None
    if not isinstance(parsed, dict):
        blockers.append("legacy_qmt_order_lifecycle_payload_not_object")
    elif (
        str(parsed.get("schema_version") or "")
        != LEGACY_QMT_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION
    ):
        blockers.append("legacy_qmt_order_lifecycle_schema_mismatch")
    if blockers:
        raise LegacyQmtOrderLifecycleMigrationRejected(blockers)

    migrated = deepcopy(parsed)
    migrated["schema_version"] = BROKER_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION
    return json.dumps(
        migrated,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
