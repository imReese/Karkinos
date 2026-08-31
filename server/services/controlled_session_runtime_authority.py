"""Signed, expiring runtime-session authority with no broker submission path."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Callable

from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT as CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT as CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_REPLACEMENT_MINIMUM_STABILITY_SECONDS as CONTROLLED_SESSION_REPLACEMENT_MINIMUM_STABILITY_SECONDS,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_REPLACEMENT_SNAPSHOT_MAX_AGE_SECONDS as CONTROLLED_SESSION_REPLACEMENT_SNAPSHOT_MAX_AGE_SECONDS,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT as CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_REVOCATION_REASONS as CONTROLLED_SESSION_REVOCATION_REASONS,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_ENTITY_TYPE as CONTROLLED_SESSION_RUNTIME_AUTHORITY_ENTITY_TYPE,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_EVENT_SOURCE as CONTROLLED_SESSION_RUNTIME_AUTHORITY_EVENT_SOURCE,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE as CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION as CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
)
from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_STATUS_SCHEMA_VERSION as CONTROLLED_SESSION_RUNTIME_AUTHORITY_STATUS_SCHEMA_VERSION,
)
from server.services import controlled_session_runtime_policy as _runtime_policy
from server.services import controlled_session_runtime_values as _runtime_values
from server.services.controlled_session_runtime_evidence import (
    RuntimeAuthorityEvidenceMixin as _RuntimeAuthorityEvidenceMixin,
)
from server.services.controlled_session_runtime_issuance import (
    RuntimeAuthorityIssuanceMixin as _RuntimeAuthorityIssuanceMixin,
)
from server.services.controlled_session_runtime_queries import (
    RuntimeAuthorityQueryMixin as _RuntimeAuthorityQueryMixin,
)
from server.services.controlled_session_runtime_replacement import (
    RuntimeAuthorityReplacementMixin as _RuntimeAuthorityReplacementMixin,
)
from server.services.controlled_session_runtime_revocation import (
    RuntimeAuthorityRevocationMixin as _RuntimeAuthorityRevocationMixin,
)
from server.services.operator_approval import resolve_operator_approval_with_proof

_FINGERPRINT_PATTERN = _runtime_values.FINGERPRINT_PATTERN
_ID_PATTERN = _runtime_values.ID_PATTERN
_TOKEN_PATTERN = _runtime_values.TOKEN_PATTERN
_replacement_bound_blockers = _runtime_policy.replacement_bound_blockers
_session_response = _runtime_values.session_response
_revocation_response = _runtime_values.revocation_response
_replacement_response = _runtime_values.replacement_response
_blocked_session = _runtime_values.blocked_session
_token_hash = _runtime_values.token_hash
_fingerprint = _runtime_values.fingerprint
_mapping = _runtime_values.mapping
_json_object = _runtime_values.json_object
_json_list = _runtime_values.json_list
_parse_timestamp = _runtime_values.parse_timestamp
_aware_utc = _runtime_values.aware_utc
_safety_flags = _runtime_values.safety_flags


class ControlledSessionRuntimeAuthorityRejected(ValueError):
    """Raised after a session issuance or revocation attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionRuntimeAuthorityService(
    _RuntimeAuthorityQueryMixin,
    _RuntimeAuthorityIssuanceMixin,
    _RuntimeAuthorityReplacementMixin,
    _RuntimeAuthorityRevocationMixin,
    _RuntimeAuthorityEvidenceMixin,
):
    """Issue and authenticate bounded sessions without contacting a broker."""

    def __init__(
        self,
        *,
        db: Any,
        reservation_provider: Callable[[str], dict[str, Any]] | None = None,
        attestation_provider: Callable[[str], dict[str, Any]] | None = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        salt_factory: Callable[[], str] | None = None,
    ) -> None:
        self._db = db
        self._reservation_provider = reservation_provider
        self._attestation_provider = attestation_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._salt_factory = salt_factory or (lambda: secrets.token_hex(16))

    def _resolve_operator_approval(
        self, **kwargs: Any
    ) -> tuple[dict[str, Any], list[str]]:
        """Keep the historical module-level approval seam patchable."""
        return resolve_operator_approval_with_proof(**kwargs)

    def _runtime_authority_rejection(
        self,
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> ControlledSessionRuntimeAuthorityRejected:
        return ControlledSessionRuntimeAuthorityRejected(message, evidence=evidence)
