"""Atomic writes for external backtest research requests."""

from __future__ import annotations

from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.external_research import (
    EXTERNAL_BACKTEST_REPORT_PROMPT,
    ExternalBacktestReportRecord,
    HumanExternalBacktestReportRequest,
)
from server.contracts.idempotency import IdempotencyConflict

from .external_research_projection import external_backtest_report_record
from .external_research_repository import ExternalBacktestReportRepository


class ExternalBacktestReportUnitOfWork:
    """Commit an idempotent request mapping and its model-call claim atomically."""

    def __init__(self, repository: ExternalBacktestReportRepository) -> None:
        self._repository = repository

    def create_or_get(
        self,
        request: HumanExternalBacktestReportRequest,
        *,
        capture_id: str,
        workflow_id: str,
        context_snapshot_id: str,
        context_fingerprint: str,
        evidence_reference_id: str,
        provider_id: str,
        model_id: str,
        created_at: str,
    ) -> tuple[ExternalBacktestReportRecord, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "workflow_id": workflow_id,
            "evidence_reference_id": evidence_reference_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "prompt_version": EXTERNAL_BACKTEST_REPORT_PROMPT,
        }
        analysis_id = f"ai-external-report-{content_fingerprint(identity)[:24]}"
        with self._repository.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_external_backtest_report_requests "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["request_fingerprint"]) != request.fingerprint
                    or str(existing["workflow_id"]) != workflow_id
                    or str(existing["evidence_reference_id"]) != evidence_reference_id
                ):
                    raise IdempotencyConflict(
                        "external report idempotency key was reused with different input"
                    )
                return external_backtest_report_record(existing), True
            conn.execute(
                """
                INSERT INTO ai_external_backtest_report_requests (
                    analysis_id, idempotency_key, request_json,
                    request_fingerprint, requested_by, backtest_result_id,
                    capture_id, workflow_id, context_snapshot_id,
                    context_fingerprint, evidence_reference_id, provider_id,
                    model_id, prompt_version, run_claimed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    analysis_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.requested_by,
                    request.backtest_result_id,
                    capture_id,
                    workflow_id,
                    context_snapshot_id,
                    context_fingerprint,
                    evidence_reference_id,
                    provider_id,
                    model_id,
                    EXTERNAL_BACKTEST_REPORT_PROMPT,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_external_backtest_report_requests "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external report audit mapping persistence failed")
        return external_backtest_report_record(row), False

    def claim_run(self, analysis_id: str, *, claimed_at: str) -> bool:
        """Atomically let one exact request cross the billable model boundary."""
        with self._repository.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_external_backtest_report_requests
                SET run_claimed_at = ?
                WHERE analysis_id = ? AND run_claimed_at IS NULL
                """,
                (claimed_at, analysis_id),
            )
        return cursor.rowcount == 1


__all__ = ["ExternalBacktestReportUnitOfWork"]
