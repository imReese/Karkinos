"""Application wiring for persisted-only current per-order dossier review."""

from __future__ import annotations

from typing import Any

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.services.broker_connector_runtime import build_broker_connectors
from server.services.broker_connector_soak_promotion import (
    BrokerConnectorSoakPromotionService,
)
from server.services.current_per_order_dossier import (
    CurrentPerOrderDossierService,
    resolve_persisted_execution_gateway_verification,
)
from server.services.per_order_confirmation import PerOrderConfirmationService


def build_current_per_order_dossier_service(
    state: Any,
) -> CurrentPerOrderDossierService:
    """Compose the current-review service without a runtime gateway reader."""

    config = getattr(state, "config", None)
    connectors = build_broker_connectors(getattr(config, "broker_connectors", []) or [])
    trusted_operator_identities = (
        getattr(config, "trusted_operator_identities", []) or []
    )
    dossier_service = PerOrderConfirmationService(
        db=state.db,
        connectors=connectors,
        trusted_operator_identities=trusted_operator_identities,
        trading_controls=getattr(state, "trading_controls", None),
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
            lambda fingerprint: resolve_persisted_execution_gateway_verification(
                state.db,
                fingerprint,
            )
        ),
        account_truth_evidence_provider=(
            lambda: {
                **build_latest_account_truth_promotion_evidence(state),
                "persisted_facts_only": True,
                "provider_contact_performed": False,
            }
        ),
    )
    return CurrentPerOrderDossierService(
        db=state.db,
        dossier_service=dossier_service,
    )
