"""Read projection seams for persisted lifecycle collector evidence."""

from __future__ import annotations

import sqlite3
from typing import Any


def broker_order_lifecycle_collector_release_binding(
    row: sqlite3.Row,
) -> dict[str, Any]:
    """Project only the release fields revalidated before cursor commit."""

    return {
        field: row[field]
        for field in (
            "release_evidence_ref",
            "collector_id",
            "deployment_id",
            "collector_version",
            "deployment_fingerprint",
            "provider",
            "gateway_id",
            "account_alias",
            "adapter_authorization_ref",
            "collection_mode",
        )
    }
