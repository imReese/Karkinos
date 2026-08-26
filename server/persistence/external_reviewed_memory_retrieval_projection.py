"""SQLite row projection for external reviewed-memory retrieval."""

from __future__ import annotations

import json
import sqlite3

from server.contracts.external_reviewed_memory_retrieval import (
    HumanExternalReviewedMemoryRetrievalRequest,
    StoredExternalReviewedMemoryRetrieval,
)


def external_reviewed_memory_retrieval_from_row(
    row: sqlite3.Row,
) -> StoredExternalReviewedMemoryRetrieval:
    request_payload = json.loads(str(row["request_json"]))
    request = HumanExternalReviewedMemoryRetrievalRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        requested_by=str(request_payload["requested_by"]),
        purpose=str(request_payload["purpose"]),
        current_context_snapshot_id=str(request_payload["current_context_snapshot_id"]),
        promotion_ids=tuple(str(item) for item in request_payload["promotion_ids"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalReviewedMemoryRetrieval(
        retrieval_id=str(row["retrieval_id"]),
        request=request,
        stored_idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        stored_current_context_snapshot_id=str(row["current_context_snapshot_id"]),
        retrieval_target_fingerprint=str(row["retrieval_target_fingerprint"]),
        created_at=str(row["created_at"]),
    )
