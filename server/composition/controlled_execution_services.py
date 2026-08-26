"""Canonical assembly for controlled-execution application services.

Routes are transport adapters.  They delegate service construction here so
that controlled-execution dependencies have one composition owner and never
need to import another route module.
"""

from __future__ import annotations

from typing import Any, Callable

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.dependencies import AppState
from server.services.broker_connector_runtime import build_broker_connectors
from server.services.broker_connector_soak_promotion import (
    BrokerConnectorSoakPromotionService,
)
from server.services.controlled_broker_cancellation import (
    ControlledBrokerCancellationService,
)
from server.services.controlled_broker_rejection_evidence import (
    ControlledBrokerRejectionEvidenceService,
)
from server.services.controlled_broker_submission import (
    ControlledBrokerSubmissionService,
)
from server.services.controlled_broker_write_release import (
    ControlledBrokerWriteReleaseService,
)
from server.services.controlled_session_automatic_pause import (
    ControlledSessionAutomaticPauseService,
)
from server.services.controlled_session_budget_reservation import (
    ControlledSessionBudgetReservationService,
)
from server.services.controlled_session_envelope import (
    ControlledSessionEnvelopeService,
)
from server.services.controlled_session_live_gates import (
    ControlledSessionAutomaticPauseOrchestratorService,
    ControlledSessionLiveGateSnapshotService,
)
from server.services.controlled_session_runtime_authority import (
    ControlledSessionRuntimeAuthorityService,
)
from server.services.controlled_session_runtime_rate_limiter import (
    ControlledSessionRuntimeRateLimiterService,
)
from server.services.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
    ControlledSubmissionReconciliationClearanceService,
)
from server.services.execution_gateway_verification import (
    ExecutionGatewayVerificationService,
)
from server.services.manual_broker_cancellation_evidence import (
    ManualBrokerCancellationEvidenceService,
)
from server.services.per_order_confirmation import PerOrderConfirmationService
from server.services.session_start_account_truth import (
    SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
    SessionStartAccountTruthService,
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
    try:
        persisted = build_controlled_broker_write_release_service(state)
        if persisted.get_status().get("active_release_count", 0) > 0:
            return persisted
    except Exception:
        return None
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


def build_controlled_session_envelope_service(
    state: AppState,
) -> ControlledSessionEnvelopeService:
    config = state.config
    return ControlledSessionEnvelopeService(
        db=state.db,
        connectors=build_broker_connectors(
            getattr(config, "broker_connectors", []) or []
        ),
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        trading_controls=state.trading_controls,
        execution_gateway_verification_provider=(
            ExecutionGatewayVerificationService(
                db=state.db,
                gateways=state.execution_gateways,
            ).resolve
        ),
        session_start_account_truth_provider=(
            SessionStartAccountTruthService(
                db=state.db,
                account_truth_provider=(
                    lambda: build_latest_account_truth_promotion_evidence(
                        state,
                        max_age_seconds=(SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS),
                    )
                ),
            ).resolve
        ),
    )


def build_controlled_session_budget_reservation_service(
    state: AppState,
    *,
    attestation_provider: Callable[[str], dict[str, Any]] | None = None,
) -> ControlledSessionBudgetReservationService:
    if attestation_provider is None:
        attestation_provider = build_controlled_session_envelope_service(
            state
        ).resolve_attestation
    return ControlledSessionBudgetReservationService(
        db=state.db,
        attestation_provider=attestation_provider,
    )


def build_controlled_session_runtime_authority_service(
    state: AppState,
    *,
    reservation_provider: Callable[[str], dict[str, Any]] | None = None,
    attestation_provider: Callable[[str], dict[str, Any]] | None = None,
) -> ControlledSessionRuntimeAuthorityService:
    envelope = None
    if attestation_provider is None:
        envelope = build_controlled_session_envelope_service(state)
        attestation_provider = envelope.resolve_attestation
    if reservation_provider is None:
        reservation_provider = build_controlled_session_budget_reservation_service(
            state,
            attestation_provider=attestation_provider,
        ).resolve
    config = state.config
    return ControlledSessionRuntimeAuthorityService(
        db=state.db,
        reservation_provider=reservation_provider,
        attestation_provider=attestation_provider,
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )


def build_controlled_session_live_gate_service(
    state: AppState,
    *,
    authority: ControlledSessionRuntimeAuthorityService | None = None,
    reservation_provider: Callable[[str], dict[str, Any]] | None = None,
    attestation_provider: Callable[[str], dict[str, Any]] | None = None,
) -> ControlledSessionLiveGateSnapshotService:
    if attestation_provider is None:
        attestation_provider = build_controlled_session_envelope_service(
            state
        ).resolve_attestation
    if reservation_provider is None:
        reservation_provider = build_controlled_session_budget_reservation_service(
            state,
            attestation_provider=attestation_provider,
        ).resolve
    if authority is None:
        authority = build_controlled_session_runtime_authority_service(
            state,
            reservation_provider=reservation_provider,
            attestation_provider=attestation_provider,
        )
    return ControlledSessionLiveGateSnapshotService(
        db=state.db,
        session_monitor_provider=authority.resolve_for_monitoring,
        reservation_provider=reservation_provider,
        attestation_provider=attestation_provider,
        trading_controls=state.trading_controls,
    )


def _build_controlled_session_monitoring_dependencies(
    state: AppState,
) -> tuple[
    ControlledSessionRuntimeAuthorityService,
    ControlledSessionLiveGateSnapshotService,
]:
    envelope = build_controlled_session_envelope_service(state)
    budget = build_controlled_session_budget_reservation_service(
        state,
        attestation_provider=envelope.resolve_attestation,
    )
    authority = build_controlled_session_runtime_authority_service(
        state,
        reservation_provider=budget.resolve,
        attestation_provider=envelope.resolve_attestation,
    )
    live_gates = build_controlled_session_live_gate_service(
        state,
        authority=authority,
        reservation_provider=budget.resolve,
        attestation_provider=envelope.resolve_attestation,
    )
    return authority, live_gates


def build_controlled_session_automatic_pause_service(
    state: AppState,
) -> ControlledSessionAutomaticPauseService:
    authority, live_gates = _build_controlled_session_monitoring_dependencies(state)
    return ControlledSessionAutomaticPauseService(
        db=state.db,
        session_provider=authority.resolve_for_monitoring,
        gate_provider=live_gates.resolve_gate_snapshot,
    )


def build_controlled_session_automatic_pause_orchestrator_service(
    state: AppState,
) -> ControlledSessionAutomaticPauseOrchestratorService:
    authority, live_gates = _build_controlled_session_monitoring_dependencies(state)
    automatic_pause = ControlledSessionAutomaticPauseService(
        db=state.db,
        session_provider=authority.resolve_for_monitoring,
        gate_provider=live_gates.resolve_gate_snapshot,
    )
    return ControlledSessionAutomaticPauseOrchestratorService(
        runtime_authority=authority,
        live_gates=live_gates,
        automatic_pause=automatic_pause,
    )


def build_controlled_session_runtime_rate_limiter_service(
    state: AppState,
) -> ControlledSessionRuntimeRateLimiterService:
    authority, live_gates = _build_controlled_session_monitoring_dependencies(state)
    return ControlledSessionRuntimeRateLimiterService(
        db=state.db,
        session_provider=authority.authenticate,
        gate_snapshot_provider=live_gates.latest,
    )
