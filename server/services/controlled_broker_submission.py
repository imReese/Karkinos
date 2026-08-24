"""One-shot, human-signed broker submission with query-only recovery."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import server.services.controlled_broker_submission_gateway as _submission_gateway
import server.services.controlled_broker_submission_policy as _submission_policy
import server.services.controlled_broker_submission_values as _submission_values
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_GATEWAY_HEALTH_MAX_AGE_SECONDS as CONTROLLED_BROKER_GATEWAY_HEALTH_MAX_AGE_SECONDS,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT as CONTROLLED_BROKER_RECOVERY_ACKNOWLEDGEMENT,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS as CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_REJECTION_ENTITY_TYPE as CONTROLLED_BROKER_RECOVERY_REJECTION_ENTITY_TYPE,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_REJECTION_EVENT_TYPE as CONTROLLED_BROKER_RECOVERY_REJECTION_EVENT_TYPE,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_RECOVERY_SCHEMA_VERSION as CONTROLLED_BROKER_RECOVERY_SCHEMA_VERSION,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT as CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE as CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_REJECTION_ENTITY_TYPE as CONTROLLED_BROKER_SUBMISSION_REJECTION_ENTITY_TYPE,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_REJECTION_EVENT_TYPE as CONTROLLED_BROKER_SUBMISSION_REJECTION_EVENT_TYPE,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION as CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION,
)
from server.contracts.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION as CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION,
)
from server.contracts.controlled_broker_submission import (
    GATEWAY_RESULT_STATUSES,
    REQUIRED_CAPABILITIES,
    REQUIRED_RELEASE_ASSERTIONS,
)
from server.services.controlled_broker_submission_command import (
    ControlledBrokerSubmissionCommandMixin as _ControlledBrokerSubmissionCommandMixin,
)
from server.services.controlled_broker_submission_evidence import (
    ControlledBrokerSubmissionEvidenceMixin as _ControlledBrokerSubmissionEvidenceMixin,
)
from server.services.controlled_broker_submission_preview import (
    ControlledBrokerSubmissionPreviewMixin as _ControlledBrokerSubmissionPreviewMixin,
)
from server.services.controlled_broker_submission_queries import (
    ControlledBrokerSubmissionQueryMixin as _ControlledBrokerSubmissionQueryMixin,
)
from server.services.controlled_broker_submission_recovery import (
    ControlledBrokerSubmissionRecoveryMixin as _ControlledBrokerSubmissionRecoveryMixin,
)
from server.services.execution_gateway_verification_binding import (
    build_execution_gateway_order_contract,
)
from server.services.execution_identity import build_order_fingerprint
from server.services.operator_approval import (
    resolve_operator_approval,
    resolve_operator_approval_with_proof,
)

_FINGERPRINT_PATTERN = _submission_values.FINGERPRINT_PATTERN
_ID_PATTERN = _submission_values.ID_PATTERN
_REQUIRED_CAPABILITIES = REQUIRED_CAPABILITIES
_REQUIRED_RELEASE_ASSERTIONS = REQUIRED_RELEASE_ASSERTIONS
_GATEWAY_RESULT_STATUSES = GATEWAY_RESULT_STATUSES
_capabilities = _submission_gateway.capabilities
_health = _submission_gateway.health
_missing_health = _submission_gateway.missing_health
_dry_run = _submission_gateway.dry_run
_missing_dry_run = _submission_gateway.missing_dry_run
_classify_gateway_result = _submission_policy.classify_gateway_result
_sanitize_gateway_result = _submission_policy.sanitize_gateway_result
_intent_response = _submission_values.intent_response
_client_order_id = _submission_values.client_order_id
_fingerprint = _submission_values.fingerprint
_json_object = _submission_values.json_object
_mapping = _submission_values.mapping
_parse_timestamp = _submission_values.parse_timestamp
_aware_utc = _submission_values.aware_utc
_safety_flags = _submission_values.safety_flags


class ControlledBrokerSubmissionRejected(ValueError):
    """Raised after a rejected one-shot submission attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledBrokerSubmissionService(
    _ControlledBrokerSubmissionQueryMixin,
    _ControlledBrokerSubmissionPreviewMixin,
    _ControlledBrokerSubmissionCommandMixin,
    _ControlledBrokerSubmissionRecoveryMixin,
    _ControlledBrokerSubmissionEvidenceMixin,
):
    """Submit one exact order only after fresh human and operational evidence."""

    def __init__(
        self,
        *,
        db: Any,
        gateways: list[Any] | tuple[Any, ...] = (),
        confirmation_provider: Callable[[str], dict[str, Any]] | None = None,
        release_evidence_provider: Callable[[str], dict[str, Any]] | None = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        trading_controls: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateways = list(gateways or [])
        self._confirmation_provider = confirmation_provider
        self._release_evidence_provider = release_evidence_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._trading_controls = trading_controls
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _build_order_fingerprint(self, order: dict[str, Any]) -> str:
        return build_order_fingerprint(order)

    def _build_execution_gateway_order_contract(
        self,
        order: dict[str, Any],
    ) -> dict[str, Any]:
        return build_execution_gateway_order_contract(order)

    def _resolve_operator_approval(
        self,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_operator_approval(**kwargs)

    def _resolve_operator_approval_with_proof(
        self,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_operator_approval_with_proof(**kwargs)

    def _submission_rejection(
        self,
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> ControlledBrokerSubmissionRejected:
        return ControlledBrokerSubmissionRejected(message, evidence=evidence)
