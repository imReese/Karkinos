"""Signed, expiring capability release for one reviewed broker execution edge.

This module intentionally remains the stable public facade. Contract policy,
evidence assembly, and SQLite transactions are owned by dedicated modules.
The release is necessary but never sufficient for an order submission.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_execution_edge_conformance import (
    BrokerExecutionEdgeConformanceRepository,
    preview_broker_execution_edge_manifest,
)
from server.contracts.controlled_broker_write_release import (
    CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION,
    CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_REASONS,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION,
    CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION,
    CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION,
    ControlledBrokerWriteReleaseRejected,
)
from server.persistence.controlled_broker_write_releases import (
    ControlledBrokerWriteReleaseRepository,
)
from server.services.broker_adapter_readiness import build_broker_adapter_readiness
from server.services.controlled_broker_write_release_dossier import (
    ControlledBrokerWriteReleaseDossierBuilder,
)
from server.services.controlled_broker_write_release_workflow import (
    ControlledBrokerWriteReleaseWorkflow,
)
from server.services.operator_approval import (
    resolve_operator_approval,
    resolve_operator_approval_with_proof,
)


class ControlledBrokerWriteReleaseService:
    """Stable application facade for append-only write-edge releases."""

    def __init__(
        self,
        *,
        db: Any,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        soak_promotion_provider: Callable[[str], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._trusted_operator_identities = tuple(trusted_operator_identities or ())
        self._soak_promotion_provider = soak_promotion_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        raw_path = getattr(db, "_path", None)
        self._path = Path(raw_path) if raw_path is not None else None
        self._repository = (
            ControlledBrokerWriteReleaseRepository(self._path)
            if self._path is not None
            else None
        )
        self._dossier_builder = ControlledBrokerWriteReleaseDossierBuilder(
            db=db,
            db_path=self._path,
            soak_promotion_provider_factory=(lambda: self._soak_promotion_provider),
            clock=lambda: self._clock(),
            manifest_previewer=(
                lambda *args, **kwargs: preview_broker_execution_edge_manifest(
                    *args, **kwargs
                )
            ),
            conformance_repository_factory=(
                lambda path: BrokerExecutionEdgeConformanceRepository(
                    path, ensure_schema=False
                )
            ),
            readonly_readiness_provider=(
                lambda database: build_broker_adapter_readiness(database)
            ),
        )
        self._workflow = ControlledBrokerWriteReleaseWorkflow(
            db=db,
            repository=self._repository,
            dossier_builder=self._dossier_builder,
            trusted_operator_identities=self._trusted_operator_identities,
            clock=lambda: self._clock(),
            approval_resolver=(lambda **kwargs: resolve_operator_approval(**kwargs)),
            proof_resolver=(
                lambda **kwargs: resolve_operator_approval_with_proof(**kwargs)
            ),
        )

    def __call__(self, release_evidence_id: str) -> dict[str, Any]:
        return self.resolve_release_evidence(release_evidence_id)

    def get_status(self) -> dict[str, Any]:
        releases = self.list_releases(limit=100)
        active = [
            item
            for item in releases
            if item.get("status") == "current_clear_signed_release"
        ]
        return {
            "schema_version": CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "active_expiring_manual_each_order_release"
                if active
                else "default_closed_waiting_for_signed_write_release"
            ),
            "recorded_release_count": len(releases),
            "active_release_count": len(active),
            "active_release_ids": [
                str(item.get("release_evidence_id") or "") for item in active
            ],
            "maximum_release_seconds": CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS,
            "supported_revocation_reasons": sorted(
                CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_REASONS
            ),
            "release_provider_available": bool(active),
            "default_registered": False,
            "gateway_registered": False,
            "broker_contact_performed": False,
            "broker_submission_performed": False,
            "broker_cancellation_performed": False,
            "automatic_execution_allowed": False,
            "strategy_direct_submission_allowed": False,
            "authorizes_order_submission_by_itself": False,
            "does_not_grant_capital_authority": True,
        }

    def preview_dossier(
        self,
        *,
        execution_edge_manifest: Mapping[str, Any],
        readonly_release_evidence_ref: str,
        soak_acceptance_id: str,
        effective_at: str,
        expires_at: str,
        owner_review_refs: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._workflow.preview_dossier(
            execution_edge_manifest=execution_edge_manifest,
            readonly_release_evidence_ref=readonly_release_evidence_ref,
            soak_acceptance_id=soak_acceptance_id,
            effective_at=effective_at,
            expires_at=expires_at,
            owner_review_refs=owner_review_refs,
        )

    def record_release(
        self,
        *,
        execution_edge_manifest: Mapping[str, Any],
        readonly_release_evidence_ref: str,
        soak_acceptance_id: str,
        effective_at: str,
        expires_at: str,
        owner_review_refs: Mapping[str, Any],
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        return self._workflow.record_release(
            execution_edge_manifest=execution_edge_manifest,
            readonly_release_evidence_ref=readonly_release_evidence_ref,
            soak_acceptance_id=soak_acceptance_id,
            effective_at=effective_at,
            expires_at=expires_at,
            owner_review_refs=owner_review_refs,
            dossier_fingerprint=dossier_fingerprint,
            operator_label=operator_label,
            operator_approval_id=operator_approval_id,
            operator_proof_signature_base64=operator_proof_signature_base64,
            acknowledgement=acknowledgement,
        )

    def preview_revocation(
        self, *, release_evidence_id: str, reason_code: str
    ) -> dict[str, Any]:
        return self._workflow.preview_revocation(
            release_evidence_id=release_evidence_id,
            reason_code=reason_code,
        )

    def revoke_release(
        self,
        *,
        release_evidence_id: str,
        reason_code: str,
        revocation_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        return self._workflow.revoke_release(
            release_evidence_id=release_evidence_id,
            reason_code=reason_code,
            revocation_fingerprint=revocation_fingerprint,
            operator_label=operator_label,
            operator_approval_id=operator_approval_id,
            operator_proof_signature_base64=operator_proof_signature_base64,
            acknowledgement=acknowledgement,
        )

    def resolve_release_evidence(self, release_evidence_id: str) -> dict[str, Any]:
        return self._workflow.resolve_release_evidence(release_evidence_id)

    def list_releases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            self.resolve_release_evidence(release_id)
            for release_id in self._workflow.list_release_ids(limit=limit)
        ]

    def get_release(self, release_evidence_id: str) -> dict[str, Any]:
        return self.resolve_release_evidence(release_evidence_id)


__all__ = [
    "CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_WRITE_RELEASE_DOSSIER_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_MAX_SECONDS",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT",
    "CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_SCHEMA_VERSION",
    "CONTROLLED_BROKER_WRITE_RELEASE_STATUS_SCHEMA_VERSION",
    "ControlledBrokerWriteReleaseRejected",
    "ControlledBrokerWriteReleaseService",
]
