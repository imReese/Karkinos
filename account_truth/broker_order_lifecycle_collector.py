"""Broker-neutral, explicit collector-batch ingestion without broker authority."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_order_lifecycle import (
    BrokerOrderLifecycleEvidenceRepository,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
    MAX_COLLECTOR_BATCH_BYTES,
)
from account_truth.broker_order_lifecycle_collector_preview import (
    preview_broker_order_lifecycle_collector_batch as _preview_collector_batch,
)
from account_truth.broker_order_lifecycle_collector_repository import (
    BrokerOrderLifecycleCollectorReadRepositoryMixin,
)
from account_truth.broker_order_lifecycle_collector_schema import (
    BrokerOrderLifecycleCollectorSchemaMixin,
)
from account_truth.broker_order_lifecycle_collector_uow import (
    BrokerOrderLifecycleCollectorUnitOfWorkMixin,
)


class BrokerOrderLifecycleCollectorRejected(ValueError):
    """Raised when a collector run cannot be safely persisted or resumed."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def preview_broker_order_lifecycle_collector_batch(
    content: str | bytes,
    *,
    source_name: str = "",
    max_snapshot_age_seconds: int = 120,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Normalize one local collector batch without writing or contacting a broker."""

    return _preview_collector_batch(
        content,
        source_name=source_name,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        clock=clock,
    )


class BrokerOrderLifecycleCollectorRepository(
    BrokerOrderLifecycleCollectorUnitOfWorkMixin,
    BrokerOrderLifecycleCollectorReadRepositoryMixin,
    BrokerOrderLifecycleCollectorSchemaMixin,
):
    """Persist collector runs and advance one broker-neutral cursor fail-closed."""

    def __init__(
        self,
        path: str | Path,
        *,
        ensure_schema: bool = True,
    ) -> None:
        self._path = Path(path)
        if ensure_schema:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()
            BrokerOrderLifecycleEvidenceRepository(self._path)

    @staticmethod
    def _collector_rejection(
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> BrokerOrderLifecycleCollectorRejected:
        return BrokerOrderLifecycleCollectorRejected(message, evidence=evidence)

    def ingest(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Prepare and commit one batch; a prepared run is restart-replayable."""

        prepared = self.prepare(preview, acknowledgement=acknowledgement)
        if prepared["run_status"] != "prepared":
            return prepared
        return self.commit_prepared(str(prepared["run_id"]))

    def prepare(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Persist a sanitized preview before lifecycle evidence is committed."""

        return super().prepare(preview, acknowledgement=acknowledgement)

    def commit_prepared(self, run_id: str) -> dict[str, Any]:
        """Replay a prepared preview and atomically advance its collector cursor."""

        return super().commit_prepared(run_id)

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read persisted collector runs only; never create an absent database."""

        return super().list_runs(limit=limit)

    def get_state(
        self,
        *,
        provider: str,
        gateway_id: str,
        account_alias: str,
    ) -> dict[str, Any]:
        """Read one persisted cursor state without provider contact."""

        return super().get_state(
            provider=provider,
            gateway_id=gateway_id,
            account_alias=account_alias,
        )
