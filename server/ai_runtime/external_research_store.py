"""Application-facing audit store for external backtest reports."""

from __future__ import annotations

from pathlib import Path

from server.contracts.external_research import (
    ExternalBacktestReportRecord,
    HumanExternalBacktestReportRequest,
)
from server.persistence.external_research_repository import (
    ExternalBacktestReportRepository,
)
from server.persistence.external_research_uow import (
    ExternalBacktestReportUnitOfWork,
)


class ExternalBacktestReportAuditStore:
    """Expose typed audit operations while persistence owns every SQLite detail."""

    def __init__(self, db_path: str | Path) -> None:
        self._repository = ExternalBacktestReportRepository(db_path)
        self._uow = ExternalBacktestReportUnitOfWork(self._repository)

    def init(self) -> None:
        self._repository.init()

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
        return self._uow.create_or_get(
            request,
            capture_id=capture_id,
            workflow_id=workflow_id,
            context_snapshot_id=context_snapshot_id,
            context_fingerprint=context_fingerprint,
            evidence_reference_id=evidence_reference_id,
            provider_id=provider_id,
            model_id=model_id,
            created_at=created_at,
        )

    def claim_run(self, analysis_id: str, *, claimed_at: str) -> bool:
        """Atomically let one exact request cross the billable model boundary."""
        return self._uow.claim_run(analysis_id, claimed_at=claimed_at)


__all__ = ["ExternalBacktestReportAuditStore"]
