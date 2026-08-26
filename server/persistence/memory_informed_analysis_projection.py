"""SQLite row projection for offline memory-informed fixture analysis."""

from __future__ import annotations

import json
import sqlite3

from server.contracts.memory_informed_analysis import (
    HumanMemoryInformedAnalysisRequest,
    MemoryInformedAnalysisRecord,
)


def memory_informed_analysis_record_from_row(
    row: sqlite3.Row,
) -> MemoryInformedAnalysisRecord:
    payload = json.loads(str(row["request_json"]))
    request = HumanMemoryInformedAnalysisRequest(
        retrieval_id=str(payload["retrieval_id"]),
        idempotency_key=str(payload["idempotency_key"]),
        requested_by=str(payload["requested_by"]),
        research_question=str(payload["research_question"]),
        confirmation=str(payload["confirmation"]),
        schema_version=str(payload["schema_version"]),
    )
    return MemoryInformedAnalysisRecord(
        analysis_id=str(row["analysis_id"]),
        request=request,
        stored_retrieval_id=str(row["retrieval_id"]),
        stored_idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        workflow_id=str(row["workflow_id"]),
        context_snapshot_id=str(row["context_snapshot_id"]),
        context_fingerprint=str(row["context_fingerprint"]),
        retrieval_target_fingerprint=str(row["retrieval_target_fingerprint"]),
        run_claimed_at=(
            str(row["run_claimed_at"]) if row["run_claimed_at"] is not None else None
        ),
        run_claim_expires_at=(
            str(row["run_claim_expires_at"])
            if row["run_claim_expires_at"] is not None
            else None
        ),
        created_at=str(row["created_at"]),
    )
