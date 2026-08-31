"""Public facade for exact, human-signed broker cancellation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from server.contracts.controlled_broker_cancellation import (
    CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_GATEWAY_HEALTH_MAX_AGE_SECONDS,
    CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS,
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION,
    CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
    CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION,
    ControlledBrokerCancellationRejected,
)
from server.persistence.controlled_broker_cancellations import (
    ControlledBrokerCancellationStore,
)
from server.projections.controlled_broker_cancellation import (
    controlled_broker_cancellation_command_response,
    controlled_broker_cancellation_safety_flags,
)
from server.services.controlled_broker_cancellation_audit import (
    record_controlled_broker_cancellation_rejection,
)
from server.services.controlled_broker_cancellation_policy import (
    resolve_controlled_broker_cancellation_gateway,
    resolve_controlled_broker_cancellation_release,
)
from server.services.controlled_broker_cancellation_preview import (
    build_controlled_broker_cancellation_preview,
    build_controlled_broker_cancellation_recovery_preview,
    build_controlled_broker_cancellation_status,
)
from server.services.controlled_broker_cancellation_workflows import (
    execute_controlled_broker_cancellation,
    execute_controlled_broker_cancellation_recovery,
)
from server.services.execution_identity import build_order_fingerprint
from server.services.manual_broker_cancellation_evidence import (
    ManualBrokerCancellationEvidenceService,
)


class ControlledBrokerCancellationService:
    """Issue one exact cancel command; broker responses remain non-authoritative."""

    def __init__(
        self,
        *,
        db: Any,
        gateways: list[Any] | tuple[Any, ...] = (),
        release_evidence_provider: Callable[[str], dict[str, Any]] | None = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateways = list(gateways or [])
        self._release_evidence_provider = release_evidence_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        db_path = getattr(db, "_path", None)
        self._store = (
            ControlledBrokerCancellationStore(
                Path(db_path),
                order_fingerprint_builder=build_order_fingerprint,
            )
            if db_path is not None
            else None
        )
        self._ticket_service = ManualBrokerCancellationEvidenceService(
            db=db,
            clock=self._clock,
        )

    def get_status(self) -> dict[str, Any]:
        return build_controlled_broker_cancellation_status(
            gateways=self._gateways,
            release_evidence_provider=self._release_evidence_provider,
            trusted_operator_identities=self._trusted_operator_identities,
            store=self._store,
        )

    def preview(self, *, submit_intent_id: str) -> dict[str, Any]:
        return build_controlled_broker_cancellation_preview(
            db=self._db,
            ticket_service=self._ticket_service,
            gateway_resolver=self._gateway,
            release_resolver=self._resolve_release,
            trusted_operator_identities=self._trusted_operator_identities,
            store=self._store,
            clock=self._clock,
            submit_intent_id=submit_intent_id,
        )

    def cancel(
        self,
        *,
        submit_intent_id: str,
        cancel_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        return execute_controlled_broker_cancellation(
            db=self._db,
            store=self._store,
            trusted_operator_identities_provider=(
                lambda: self._trusted_operator_identities
            ),
            clock=self._clock,
            preview_builder=self.preview,
            gateway_resolver=self._gateway,
            rejection_recorder=self._record_rejection,
            submit_intent_id=submit_intent_id,
            cancel_fingerprint=cancel_fingerprint,
            operator_approval_id=operator_approval_id,
            operator_proof_signature_base64=operator_proof_signature_base64,
            acknowledgement=acknowledgement,
        )

    def preview_recovery(self, *, cancel_command_id: str) -> dict[str, Any]:
        return build_controlled_broker_cancellation_recovery_preview(
            db=self._db,
            ticket_service=self._ticket_service,
            gateway_resolver=self._gateway,
            release_resolver=self._resolve_release,
            trusted_operator_identities=self._trusted_operator_identities,
            store=self._store,
            clock=self._clock,
            cancel_command_id=cancel_command_id,
        )

    def recover(
        self,
        *,
        cancel_command_id: str,
        recovery_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        return execute_controlled_broker_cancellation_recovery(
            db=self._db,
            store=self._store,
            trusted_operator_identities_provider=(
                lambda: self._trusted_operator_identities
            ),
            clock=self._clock,
            preview_builder=self.preview_recovery,
            gateway_resolver=self._gateway,
            rejection_recorder=self._record_rejection,
            cancel_command_id=cancel_command_id,
            recovery_fingerprint=recovery_fingerprint,
            operator_approval_id=operator_approval_id,
            operator_proof_signature_base64=operator_proof_signature_base64,
            acknowledgement=acknowledgement,
        )

    def get_command(self, cancel_command_id: str) -> dict[str, Any]:
        row = self._store.get(cancel_command_id) if self._store is not None else None
        if row is None:
            return {
                "status": "not_found",
                "cancel_command_id": cancel_command_id,
                "default_broker_cancellation_enabled": False,
                "safety": controlled_broker_cancellation_safety_flags(),
            }
        return controlled_broker_cancellation_command_response(
            row,
            reused=False,
            external_call_performed=False,
        )

    def list_commands(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._store.list(limit=limit) if self._store is not None else []
        return [
            controlled_broker_cancellation_command_response(
                row,
                reused=False,
                external_call_performed=False,
            )
            for row in rows
        ]

    def _gateway(self, gateway_id: str) -> tuple[Any | None, list[str]]:
        return resolve_controlled_broker_cancellation_gateway(
            self._gateways,
            gateway_id,
        )

    def _resolve_release(
        self,
        release_evidence_id: str,
        *,
        expected_gateway_id: str,
        expected_account_alias: str,
        now: datetime,
    ) -> dict[str, Any]:
        return resolve_controlled_broker_cancellation_release(
            self._release_evidence_provider,
            release_evidence_id,
            expected_gateway_id=expected_gateway_id,
            expected_account_alias=expected_account_alias,
            now=now,
        )

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
        recovery: bool,
    ) -> dict[str, Any]:
        return record_controlled_broker_cancellation_rejection(
            db=self._db,
            clock=self._clock,
            preview=preview,
            submitted_fingerprint=submitted_fingerprint,
            operator_approval_id=operator_approval_id,
            rejection_reasons=rejection_reasons,
            transaction_blockers=transaction_blockers,
            recovery=recovery,
        )
