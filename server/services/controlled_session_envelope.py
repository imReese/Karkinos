"""Non-executing session-bounded envelope proposals and attestations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import server.services.controlled_session_envelope_policy as _envelope_policy
import server.services.controlled_session_envelope_values as _envelope_values
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ACKNOWLEDGEMENT as CONTROLLED_SESSION_ACKNOWLEDGEMENT,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE as CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE as CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE as CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION as CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ENVELOPE_SCHEMA_VERSION as CONTROLLED_SESSION_ENVELOPE_SCHEMA_VERSION,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_MAX_DURATION_SECONDS as CONTROLLED_SESSION_MAX_DURATION_SECONDS,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_MAX_ORDER_COUNT as CONTROLLED_SESSION_MAX_ORDER_COUNT,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS as CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS,
)
from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_STATUS_SCHEMA_VERSION,
)
from server.services.broker_connector_soak import BrokerConnectorSoakService
from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE as CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
)
from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_SOURCE as CAPITAL_AUTHORIZATION_EVENT_SOURCE,
)
from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_TYPE as CAPITAL_AUTHORIZATION_EVENT_TYPE,
)
from server.services.controlled_session_envelope_attestations import (
    ControlledSessionEnvelopeAttestationMixin as _ControlledSessionEnvelopeAttestationMixin,
)
from server.services.controlled_session_envelope_audit import (
    ControlledSessionEnvelopeAuditMixin as _ControlledSessionEnvelopeAuditMixin,
)
from server.services.controlled_session_envelope_evidence import (
    ControlledSessionEnvelopeEvidenceMixin as _ControlledSessionEnvelopeEvidenceMixin,
)
from server.services.controlled_session_envelope_preview import (
    ControlledSessionEnvelopePreviewMixin as _ControlledSessionEnvelopePreviewMixin,
)
from server.services.controlled_session_envelope_readiness import (
    ControlledSessionEnvelopeReadinessMixin as _ControlledSessionEnvelopeReadinessMixin,
)
from server.services.execution_batch_reconciliation import (
    resolve_prior_batch_reconciliation,
)
from server.services.execution_gateway_binding import build_execution_gateway_binding
from server.services.execution_gateway_verification_binding import (
    build_execution_gateway_order_contract,
    resolve_execution_gateway_verification_binding,
)
from server.services.execution_identity import build_order_fingerprint
from server.services.operator_approval import resolve_operator_approval
from server.services.session_start_account_truth import (
    resolve_session_start_account_truth_binding,
)

_REQUIRED_GATEWAY_EVIDENCE = _envelope_policy.REQUIRED_GATEWAY_EVIDENCE
_time_and_request_blockers = _envelope_policy.time_and_request_blockers
_verification_reference_blockers = _envelope_policy.verification_reference_blockers
_per_symbol_runtime_limit_summary = _envelope_policy.per_symbol_runtime_limit_summary
_budget_projection = _envelope_policy.budget_projection
_gateway_gate_summary = _envelope_policy.gateway_gate_summary
_public_capital_summary = _envelope_values.public_capital_summary
_missing_capital_summary = _envelope_values.missing_capital_summary
_order_payload = _envelope_values.order_payload
_connector_id = _envelope_values.connector_id
_event_response = _envelope_values.event_response
_blocked_attestation_resolution = _envelope_values.blocked_attestation_resolution
_safety_flags = _envelope_values.safety_flags
_decimal = _envelope_values.decimal_value
_decimal_string = _envelope_values.decimal_string
_parse_timestamp = _envelope_values.parse_timestamp
_aware_utc = _envelope_values.aware_utc
_is_aware = _envelope_values.is_aware
_fingerprint = _envelope_values.fingerprint
_json_object = _envelope_values.json_object


class ControlledSessionAttestationRejected(ValueError):
    """Raised after an invalid session attestation has been audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionEnvelopeService(
    _ControlledSessionEnvelopePreviewMixin,
    _ControlledSessionEnvelopeAttestationMixin,
    _ControlledSessionEnvelopeEvidenceMixin,
    _ControlledSessionEnvelopeReadinessMixin,
    _ControlledSessionEnvelopeAuditMixin,
):
    """Build bounded-session proposals without issuing runtime authority."""

    def __init__(
        self,
        *,
        db: Any,
        connectors: list[Any] | tuple[Any, ...] = (),
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        trading_controls: Any | None = None,
        execution_gateway_verification_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        session_start_account_truth_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._connectors = list(connectors or [])
        self._trusted_operator_identities = list(trusted_operator_identities or [])
        self._trading_controls = trading_controls
        self._execution_gateway_verification_provider = (
            execution_gateway_verification_provider
        )
        self._session_start_account_truth_provider = (
            session_start_account_truth_provider
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": CONTROLLED_SESSION_STATUS_SCHEMA_VERSION,
            "contract_status": "proposal_only_non_executing",
            "runtime_session_authority": "separate_signed_service_required",
            "session_issue_enabled": False,
            "separate_session_issue_endpoint_available": True,
            "session_enable_enabled": False,
            "session_pause_runtime_enabled": False,
            "session_resume_enabled": False,
            "session_revoke_runtime_enabled": True,
            "broker_submission_enabled": False,
            "operator_identity_verified": False,
            "signature_verification_configured": bool(
                self._trusted_operator_identities
            ),
            "automatic_scale_up_enabled": False,
            "exact_prior_batch_reconciliation_required": True,
            "per_order_gateway_verification_binding": "required_per_envelope",
            "session_start_account_truth_binding": "required_per_envelope",
            "per_symbol_runtime_limits": "required_explicit_map_per_envelope",
            "runtime_rate_limiter_foundation": "implemented_internal_default_closed",
            "maximum_proposal_duration_seconds": (
                CONTROLLED_SESSION_MAX_DURATION_SECONDS
            ),
            "maximum_proposal_order_count": CONTROLLED_SESSION_MAX_ORDER_COUNT,
            "acknowledgement": CONTROLLED_SESSION_ACKNOWLEDGEMENT,
            "safety": _safety_flags(),
        }

    def _resolve_operator_approval(
        self, **kwargs: Any
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_operator_approval(**kwargs)

    def _attestation_rejection(
        self,
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> ControlledSessionAttestationRejected:
        return ControlledSessionAttestationRejected(message, evidence=evidence)

    def _build_execution_gateway_binding(
        self,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return build_execution_gateway_binding(**kwargs)

    def _resolve_session_start_account_truth_binding(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_session_start_account_truth_binding(*args, **kwargs)

    def _build_order_fingerprint(self, order: dict[str, Any]) -> str:
        return build_order_fingerprint(order)

    def _build_execution_gateway_order_contract(
        self,
        order: dict[str, Any],
    ) -> dict[str, Any]:
        return build_execution_gateway_order_contract(order)

    def _resolve_execution_gateway_verification_binding(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_execution_gateway_verification_binding(*args, **kwargs)

    def _build_soak_service(self, **kwargs: Any) -> Any:
        return BrokerConnectorSoakService(**kwargs)

    def _resolve_prior_batch_reconciliation(
        self,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_prior_batch_reconciliation(**kwargs)
