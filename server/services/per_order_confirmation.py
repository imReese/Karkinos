"""Non-submitting, evidence-fingerprinted per-order confirmation dossiers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import server.services.per_order_confirmation_evidence as _evidence
import server.services.per_order_confirmation_values as _values
from server.contracts.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
    PER_ORDER_CONFIRMATION_EVENT_SOURCE,
    PER_ORDER_CONFIRMATION_EVENT_TYPE,
    PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS,
    PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
    PER_ORDER_DOSSIER_SCHEMA_VERSION,
)
from server.services.execution_identity import build_order_contract as _order_contract
from server.services.execution_identity import build_order_fingerprint
from server.services.per_order_confirmation_commands import (
    PerOrderConfirmationCommandMixin as _PerOrderConfirmationCommandMixin,
)
from server.services.per_order_confirmation_preview import (
    PerOrderConfirmationPreviewMixin as _PerOrderConfirmationPreviewMixin,
)
from server.services.per_order_confirmation_queries import (
    PerOrderConfirmationQueryMixin as _PerOrderConfirmationQueryMixin,
)

# Compatibility aliases for the historical module-local seams. New family modules
# import only public symbols, while existing callers retain the original facade.
_FINGERPRINT_PATTERN = _values.FINGERPRINT_PATTERN
_read_broker_adapter_readiness = _evidence.read_broker_adapter_readiness
_resolve_broker_adapter_release_binding = (
    _evidence.resolve_broker_adapter_release_binding
)
_missing_capital_summary = _values.missing_capital_summary
_resolve_signed_soak_promotion = _evidence.resolve_signed_soak_promotion
_missing_signed_soak_promotion = _values.missing_signed_soak_promotion
_connector_id = _values.connector_id
_event_response = _values.event_response
_blocked_confirmation_resolution = _values.blocked_confirmation_resolution
_mapping = _values.mapping
_safety_flags = _values.safety_flags
_parse_timestamp = _values.parse_timestamp
_aware_utc = _values.aware_utc
_fingerprint = _values.fingerprint
_json_object = _values.json_object


class PerOrderConfirmationRejected(ValueError):
    """Raised after a rejected confirmation attempt has been audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class PerOrderConfirmationService(
    _PerOrderConfirmationQueryMixin,
    _PerOrderConfirmationPreviewMixin,
    _PerOrderConfirmationCommandMixin,
):
    """Build and attest exact order dossiers without execution authority."""

    def __init__(
        self,
        *,
        db: Any,
        connectors: list[Any] | tuple[Any, ...] = (),
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        trading_controls: Any | None = None,
        broker_soak_promotion_evidence_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        execution_gateway_verification_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        account_truth_evidence_provider: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._connectors = list(connectors or [])
        self._trusted_operator_identities = list(trusted_operator_identities or [])
        self._trading_controls = trading_controls
        self._broker_soak_promotion_evidence_provider = (
            broker_soak_promotion_evidence_provider
        )
        self._execution_gateway_verification_provider = (
            execution_gateway_verification_provider
        )
        self._account_truth_evidence_provider = account_truth_evidence_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _confirmation_rejection(
        self,
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> PerOrderConfirmationRejected:
        return PerOrderConfirmationRejected(message, evidence=evidence)
