"""Canonical assembly for controlled-execution application services.

Routes are transport adapters.  They delegate service construction here so
that controlled-execution dependencies have one composition owner and never
need to import another route module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.dependencies import AppState
from server.services.account.session_start_account_truth import (
    SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
    SessionStartAccountTruthService,
)
from server.services.controlled_execution.broker_connector_runtime import (
    build_broker_connectors,
)
from server.services.controlled_execution.broker_connector_soak_promotion import (
    BrokerConnectorSoakPromotionService,
)
from server.services.controlled_execution.controlled_broker_cancellation import (
    ControlledBrokerCancellationService,
)
from server.services.controlled_execution.controlled_broker_rejection_evidence import (
    ControlledBrokerRejectionEvidenceService,
)
from server.services.controlled_execution.controlled_broker_submission import (
    ControlledBrokerSubmissionService,
)
from server.services.controlled_execution.controlled_broker_write_release import (
    ControlledBrokerWriteReleaseService,
)
from server.services.controlled_execution.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
    ControlledSubmissionReconciliationClearanceService,
)
from server.services.controlled_execution.execution_gateway_verification import (
    ExecutionGatewayVerificationService,
)
from server.services.controlled_execution.manual_broker_cancellation_evidence import (
    ManualBrokerCancellationEvidenceService,
)
from server.services.controlled_execution.per_order_confirmation import (
    PerOrderConfirmationService,
)


def build_broker_connector_soak_promotion_service(
    state: AppState,
) -> BrokerConnectorSoakPromotionService:
    config = state.config
    return BrokerConnectorSoakPromotionService(
        db=state.db,
        connectors=build_broker_connectors(
            getattr(config, "broker_connectors", []) or []
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        account_truth_evidence_provider=(
            lambda: build_latest_account_truth_promotion_evidence(state)
        ),
    )


def build_per_order_confirmation_service(
    state: AppState,
) -> PerOrderConfirmationService:
    config = state.config
    connectors = build_broker_connectors(getattr(config, "broker_connectors", []) or [])
    trusted_operator_identities = (
        getattr(config, "trusted_operator_identities", []) or []
    )
    return PerOrderConfirmationService(
        db=state.db,
        connectors=connectors,
        trusted_operator_identities=trusted_operator_identities,
        trading_controls=state.trading_controls,
        broker_soak_promotion_evidence_provider=(
            lambda connector_id: BrokerConnectorSoakPromotionService(
                db=state.db,
                connectors=connectors,
                trusted_operator_identities=trusted_operator_identities,
                account_truth_evidence_provider=(
                    lambda: build_latest_account_truth_promotion_evidence(state)
                ),
            ).preview_dossier(connector_id)
        ),
        execution_gateway_verification_provider=(
            ExecutionGatewayVerificationService(
                db=state.db,
                gateways=state.execution_gateways,
            ).resolve
        ),
        account_truth_evidence_provider=(
            lambda: {
                **build_latest_account_truth_promotion_evidence(state),
                "persisted_facts_only": True,
                "provider_contact_performed": False,
            }
        ),
    )


def build_controlled_broker_write_release_service(
    state: AppState,
) -> ControlledBrokerWriteReleaseService:
    config = state.config
    return ControlledBrokerWriteReleaseService(
        db=state.db,
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        soak_promotion_provider=(
            lambda connector_id: build_broker_connector_soak_promotion_service(
                state
            ).preview_dossier(connector_id)
        ),
    )


def resolve_controlled_broker_release_evidence_provider(
    state: AppState,
) -> Callable[[str], dict[str, Any]] | None:
    injected = state.controlled_broker_release_evidence_provider
    if callable(injected):
        return injected
    return None


def build_controlled_broker_submission_service(
    state: AppState,
) -> ControlledBrokerSubmissionService:
    config = state.config
    return ControlledBrokerSubmissionService(
        db=state.db,
        gateways=state.execution_gateways,
        confirmation_provider=(
            build_per_order_confirmation_service(state).resolve_confirmation
        ),
        release_evidence_provider=(
            resolve_controlled_broker_release_evidence_provider(state)
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        trading_controls=state.trading_controls,
    )


def build_controlled_broker_cancellation_service(
    state: AppState,
) -> ControlledBrokerCancellationService:
    config = state.config
    return ControlledBrokerCancellationService(
        db=state.db,
        gateways=state.execution_gateways,
        release_evidence_provider=(
            resolve_controlled_broker_release_evidence_provider(state)
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )


def build_controlled_submission_clearance_service(
    state: AppState,
) -> ControlledSubmissionReconciliationClearanceService:
    config = state.config
    return ControlledSubmissionReconciliationClearanceService(
        db=state.db,
        account_truth_provider=(
            lambda: build_latest_account_truth_promotion_evidence(
                state,
                max_age_seconds=(
                    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS
                ),
            )
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )


def build_manual_broker_cancellation_service(
    state: AppState,
) -> ManualBrokerCancellationEvidenceService:
    return ManualBrokerCancellationEvidenceService(db=state.db)


def build_controlled_broker_rejection_evidence_service(
    state: AppState,
) -> ControlledBrokerRejectionEvidenceService:
    return ControlledBrokerRejectionEvidenceService(db=state.db)


class DisabledControlledSessionEnvelopeService:
    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.controlled_session_envelope_status.v1",
            "contract_status": "disabled",
            "ready": False,
            "registered_envelopes": [],
            "limitations": [
                "Automated session envelopes are permanently disabled in Karkinos."
            ],
        }

    def resolve_attestation(self, attestation_id: str) -> dict[str, Any]:
        return {}

    def preview_envelope(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "disabled",
            "ready": False,
            "blockers": ["automated_session_envelope_disabled"],
        }

    def record_attestation(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("automated session envelopes are permanently disabled")

    def list_attestations(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def get_attestation(self, attestation_id: str) -> dict[str, Any] | None:
        return None


class DisabledControlledSessionBudgetReservationService:
    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.controlled_session_budget_reservation_status.v1",
            "contract_status": "disabled",
            "ready": False,
            "limitations": [
                "Automated session budget reservations are permanently disabled in Karkinos."
            ],
        }

    def preview(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "disabled",
            "ready": False,
            "blockers": ["automated_budget_reservation_disabled"],
        }

    def record(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            "automated session budget reservations are permanently disabled"
        )

    def resolve(self, reservation_id: str) -> dict[str, Any]:
        return {}

    def list_reservations(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def get_reservation(self, reservation_id: str) -> dict[str, Any] | None:
        return None


class DisabledControlledSessionRuntimeAuthorityService:
    def __init__(self, db: Any = None) -> None:
        self._db = db

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.controlled_session_runtime_authority_status.v1",
            "contract_status": "disabled",
            "ready": False,
            "active_sessions": [],
            "limitations": [
                "Automated trading sessions are permanently disabled in Karkinos."
            ],
        }

    def preview(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "disabled",
            "ready": False,
            "blockers": ["automated_trading_sessions_disabled"],
        }

    def issue(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("automated trading session issuance is permanently disabled")

    def preview_replacement(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "disabled",
            "ready": False,
            "blockers": ["automated_trading_sessions_disabled"],
        }

    def replace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            "automated trading session replacement is permanently disabled"
        )

    def preview_revocation(
        self, *, session_id: str, reason_code: str
    ) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.controlled_session_runtime_authority.v1",
            "action": "revoke_controlled_session",
            "session_id": session_id,
            "session_fingerprint": "",
            "reservation_id": "",
            "reason_code": reason_code,
            "revocation_fingerprint": "",
            "revocation_id": "",
            "status": "blocked",
            "ready": False,
            "already_revoked": True,
            "blockers": ["automated_session_authority_decommissioned"],
            "required_operator_approval": {
                "action": "revoke_controlled_session",
                "artifact_type": "controlled_session_revocation",
                "artifact_fingerprint": "",
            },
            "broker_submission_enabled": False,
        }

    def revoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.controlled_session_runtime_authority.v1",
            "action": "revoke_controlled_session",
            "status": "revoked",
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "persisted": False,
            "reused": False,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        }

    def resolve_for_monitoring(self, session_id: str) -> dict[str, Any] | None:
        return None

    def authenticate(self, session_token: str) -> dict[str, Any] | None:
        return None

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return None


class DisabledControlledSessionLiveGateSnapshotService:
    def get_status(self) -> dict[str, Any]:
        return {"contract_status": "disabled", "ready": False}

    def resolve_gate_snapshot(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def latest(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return None


class DisabledControlledSessionAutomaticPauseService:
    def get_status(self) -> dict[str, Any]:
        return {"contract_status": "disabled", "ready": False}

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        return None


class DisabledControlledSessionAutomaticPauseOrchestratorService:
    def evaluate_all(self) -> dict[str, Any]:
        return {"evaluated": False, "paused": 0, "disabled": True}


class DisabledControlledSessionRuntimeRateLimiterService:
    def get_status(self) -> dict[str, Any]:
        return {"contract_status": "disabled", "ready": False}

    def list_admissions(self, limit: int = 100) -> list[dict[str, Any]]:
        return []


ControlledSessionEnvelopeService = DisabledControlledSessionEnvelopeService
ControlledSessionBudgetReservationService = (
    DisabledControlledSessionBudgetReservationService
)
ControlledSessionRuntimeAuthorityService = (
    DisabledControlledSessionRuntimeAuthorityService
)
ControlledSessionLiveGateSnapshotService = (
    DisabledControlledSessionLiveGateSnapshotService
)
ControlledSessionAutomaticPauseService = DisabledControlledSessionAutomaticPauseService
ControlledSessionAutomaticPauseOrchestratorService = (
    DisabledControlledSessionAutomaticPauseOrchestratorService
)
ControlledSessionRuntimeRateLimiterService = (
    DisabledControlledSessionRuntimeRateLimiterService
)


def build_controlled_session_envelope_service(
    state: AppState,
) -> DisabledControlledSessionEnvelopeService:
    return DisabledControlledSessionEnvelopeService()


def build_controlled_session_budget_reservation_service(
    state: AppState,
    *,
    attestation_provider: Callable[[str], dict[str, Any]] | None = None,
) -> DisabledControlledSessionBudgetReservationService:
    return DisabledControlledSessionBudgetReservationService()


def build_controlled_session_runtime_authority_service(
    state: AppState,
    *,
    reservation_provider: Callable[[str], dict[str, Any]] | None = None,
    attestation_provider: Callable[[str], dict[str, Any]] | None = None,
) -> DisabledControlledSessionRuntimeAuthorityService:
    return DisabledControlledSessionRuntimeAuthorityService(db=state.db)


def build_controlled_session_live_gate_service(
    state: AppState,
    *,
    authority: Any = None,
    reservation_provider: Callable[[str], dict[str, Any]] | None = None,
    attestation_provider: Callable[[str], dict[str, Any]] | None = None,
) -> DisabledControlledSessionLiveGateSnapshotService:
    return DisabledControlledSessionLiveGateSnapshotService()


def build_controlled_session_automatic_pause_service(
    state: AppState,
) -> DisabledControlledSessionAutomaticPauseService:
    return DisabledControlledSessionAutomaticPauseService()


def build_controlled_session_automatic_pause_orchestrator_service(
    state: AppState,
) -> DisabledControlledSessionAutomaticPauseOrchestratorService:
    return DisabledControlledSessionAutomaticPauseOrchestratorService()


def build_controlled_session_runtime_rate_limiter_service(
    state: AppState,
) -> DisabledControlledSessionRuntimeRateLimiterService:
    return DisabledControlledSessionRuntimeRateLimiterService()
