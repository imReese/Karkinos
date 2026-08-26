"""SQLite row projections for revocable external reviewed memory."""

from __future__ import annotations

import json
import sqlite3

from server.contracts.external_reviewed_memory import (
    ExternalReviewedMemoryPromotionRequest,
    ExternalReviewedMemoryRevocationRequest,
    StoredExternalReviewedMemoryPromotion,
    StoredExternalReviewedMemoryRevocation,
)


def external_reviewed_memory_promotion_from_row(
    row: sqlite3.Row,
) -> StoredExternalReviewedMemoryPromotion:
    request_payload = json.loads(str(row["request_json"]))
    request = ExternalReviewedMemoryPromotionRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        promoted_by=str(request_payload["promoted_by"]),
        rationale=str(request_payload["rationale"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalReviewedMemoryPromotion(
        promotion_id=str(row["promotion_id"]),
        review_id=str(row["review_id"]),
        analysis_id=str(row["analysis_id"]),
        workflow_id=str(row["workflow_id"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        promotion_target_fingerprint=str(row["promotion_target_fingerprint"]),
        memory_artifact_id=str(row["memory_artifact_id"]),
        memory_content=dict(json.loads(str(row["memory_content_json"]))),
        memory_artifact_fingerprint=str(row["memory_artifact_fingerprint"]),
        evidence_reference_ids=tuple(
            str(item) for item in json.loads(str(row["evidence_reference_ids_json"]))
        ),
        source_context_snapshot_id=str(row["source_context_snapshot_id"]),
        source_context_fingerprint=str(row["source_context_fingerprint"]),
        source_retrieval_id=(
            str(row["source_retrieval_id"])
            if row["source_retrieval_id"] is not None
            else None
        ),
        source_retrieval_target_fingerprint=(
            str(row["source_retrieval_target_fingerprint"])
            if row["source_retrieval_target_fingerprint"] is not None
            else None
        ),
        report_artifact_id=str(row["report_artifact_id"]),
        report_artifact_fingerprint=str(row["report_artifact_fingerprint"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        created_at=str(row["created_at"]),
    )


def external_reviewed_memory_revocation_from_row(
    row: sqlite3.Row,
) -> StoredExternalReviewedMemoryRevocation:
    request_payload = json.loads(str(row["request_json"]))
    request = ExternalReviewedMemoryRevocationRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        revoked_by=str(request_payload["revoked_by"]),
        reason=str(request_payload["reason"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalReviewedMemoryRevocation(
        revocation_id=str(row["revocation_id"]),
        promotion_id=str(row["promotion_id"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        promotion_target_fingerprint=str(row["promotion_target_fingerprint"]),
        memory_artifact_fingerprint=str(row["memory_artifact_fingerprint"]),
        created_at=str(row["created_at"]),
    )
