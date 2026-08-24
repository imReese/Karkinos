"""Persist normalized broker order-lifecycle evidence without broker authority."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_BINDING_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    MAX_EXPORT_BYTES,
)
from account_truth.broker_order_lifecycle_preview import (
    preview_broker_order_lifecycle_export as _preview_export,
)
from account_truth.broker_order_lifecycle_projection import (
    broker_order_lifecycle_clearance_blockers as _clearance_blockers,
)
from account_truth.broker_order_lifecycle_projection import (
    broker_order_lifecycle_terminal_outcome as _terminal_outcome,
)
from account_truth.broker_order_lifecycle_projection import (
    resolve_broker_order_lifecycle_from_connection as _resolve_from_connection,
)
from account_truth.broker_order_lifecycle_repository import (
    BrokerOrderLifecycleEvidenceReadRepositoryMixin,
)
from account_truth.broker_order_lifecycle_schema import (
    BrokerOrderLifecycleEvidenceSchemaMixin,
)
from account_truth.broker_order_lifecycle_uow import (
    BrokerOrderLifecycleEvidenceUnitOfWorkMixin,
)
from account_truth.broker_order_lifecycle_values import (
    broker_order_lifecycle_account_ref_hash as _account_ref_hash,
)


class BrokerOrderLifecycleEvidenceRejected(ValueError):
    """Raised when an explicit lifecycle evidence record request is unsafe."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def preview_broker_order_lifecycle_export(
    content: str | bytes,
    *,
    source_name: str = "",
    max_snapshot_age_seconds: int = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Normalize one exact-order broker export without persisting any fact."""

    return _preview_export(
        content,
        source_name=source_name,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        clock=clock,
    )


def resolve_broker_order_lifecycle_from_connection(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    account_alias: str,
    broker_order_id: str,
    client_order_id: str,
) -> dict[str, Any]:
    """Resolve persisted evidence using the caller's current SQLite transaction."""

    return _resolve_from_connection(
        conn,
        gateway_id=gateway_id,
        account_alias=account_alias,
        broker_order_id=broker_order_id,
        client_order_id=client_order_id,
    )


def broker_order_lifecycle_clearance_blockers(
    order: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    """Return canonical blockers for treating a controlled order as fully filled."""

    return _clearance_blockers(order, evidence)


def broker_order_lifecycle_terminal_outcome(
    order: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Resolve an exact terminal fill/cancel fact without granting authority."""

    return _terminal_outcome(order, evidence)


def broker_order_lifecycle_account_ref_hash(
    account_id: str,
    *,
    provider: str,
) -> str:
    """Build the canonical provider-scoped opaque account reference."""

    return _account_ref_hash(account_id, provider=provider)


class BrokerOrderLifecycleEvidenceRepository(
    BrokerOrderLifecycleEvidenceUnitOfWorkMixin,
    BrokerOrderLifecycleEvidenceReadRepositoryMixin,
    BrokerOrderLifecycleEvidenceSchemaMixin,
):
    """Atomic staging store for sanitized broker lifecycle observations."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ensure_schema: bool = True,
    ) -> None:
        self._path = Path(db_path)
        if ensure_schema:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    @staticmethod
    def _lifecycle_rejection(
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> BrokerOrderLifecycleEvidenceRejected:
        return BrokerOrderLifecycleEvidenceRejected(message, evidence=evidence)

    def record(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Record one explicit import; never contact a provider or mutate OMS."""

        return super().record(preview, acknowledgement=acknowledgement)

    def list_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read persisted observations only; return empty when not configured."""

        return super().list_observations(limit=limit)

    def resolve_order(
        self,
        *,
        gateway_id: str,
        account_alias: str,
        broker_order_id: str,
        client_order_id: str,
    ) -> dict[str, Any]:
        """Resolve the newest persisted evidence for both exact order ids."""

        return super().resolve_order(
            gateway_id=gateway_id,
            account_alias=account_alias,
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
        )
