"""Signed, expiring runtime-session authority with no broker submission path."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable

from server.services.operator_approval import resolve_operator_approval_with_proof

CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION = (
    "karkinos.controlled_session_runtime_authority.v1"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_session_runtime_authority_status.v1"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE = (
    "controlled_session.runtime_authority_rejected"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_ENTITY_TYPE = (
    "controlled_session_runtime_authority"
)
CONTROLLED_SESSION_RUNTIME_AUTHORITY_EVENT_SOURCE = (
    "controlled_session_runtime_authority"
)
CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT = (
    "issue_exact_expiring_non_broker_controlled_session"
)
CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT = (
    "revoke_exact_controlled_session_no_auto_resume"
)
CONTROLLED_SESSION_REVOCATION_REASONS = frozenset(
    {
        "manual_operator_stop",
        "end_of_strategy_window",
        "operational_concern",
        "risk_review",
        "account_or_reconciliation_concern",
    }
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class ControlledSessionRuntimeAuthorityRejected(ValueError):
    """Raised after a session issuance or revocation attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionRuntimeAuthorityService:
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

    def get_status(self) -> dict[str, Any]:
        providers_configured = callable(self._reservation_provider) and callable(
            self._attestation_provider
        )
        return {
            "schema_version": (
                CONTROLLED_SESSION_RUNTIME_AUTHORITY_STATUS_SCHEMA_VERSION
            ),
            "contract_status": (
                "signed_runtime_session_authority_ready_non_broker"
                if providers_configured
                else "disabled_waiting_for_exact_evidence_providers"
            ),
            "reservation_provider_configured": callable(self._reservation_provider),
            "attestation_provider_configured": callable(self._attestation_provider),
            "requires_issue_operator_signature": True,
            "requires_revoke_operator_signature": True,
            "session_issue_endpoint_exposed": True,
            "session_revoke_endpoint_exposed": True,
            "session_resume_endpoint_exposed": False,
            "session_renew_endpoint_exposed": False,
            "session_widen_endpoint_exposed": False,
            "raw_token_storage_enabled": False,
            "session_token_return_policy": "first_successful_issue_response_only",
            "runtime_rate_admission_requires_token": True,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }

    def preview_issuance(self, *, reservation_id: str) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized = str(reservation_id or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            blockers.append("runtime_session_reservation_id_invalid")

        reservation = self._resolve_provider(
            self._reservation_provider,
            normalized,
            unavailable="runtime_session_reservation_provider_unavailable",
            failed="runtime_session_reservation_provider_failed",
            blockers=blockers,
        )
        if reservation.get("resolution_status") != ("current_reserved_non_executing"):
            blockers.append("runtime_session_reservation_not_current")
            blockers.extend(
                f"reservation:{item}"
                for item in reservation.get("blockers") or []
                if isinstance(item, str)
            )

        attestation_id = str(reservation.get("attestation_id") or "")
        attestation = self._resolve_provider(
            self._attestation_provider,
            attestation_id,
            unavailable="runtime_session_attestation_provider_unavailable",
            failed="runtime_session_attestation_provider_failed",
            blockers=blockers,
        )
        if attestation.get("status") != "current_verified_non_executing":
            blockers.append("runtime_session_attestation_not_current")
            blockers.extend(
                f"attestation:{item}"
                for item in attestation.get("blockers") or []
                if isinstance(item, str)
            )

        envelope = _mapping(attestation.get("current_envelope"))
        capital = _mapping(envelope.get("capital_evaluation"))
        scope = _mapping(capital.get("scope"))
        budget = _mapping(envelope.get("budget_projection"))
        order_ids = [str(item) for item in envelope.get("order_ids") or []]
        if (
            not order_ids
            or len(order_ids) != len(set(order_ids))
            or any(not _ID_PATTERN.fullmatch(item) for item in order_ids)
        ):
            blockers.append("runtime_session_order_scope_invalid")

        envelope_fingerprint = str(attestation.get("envelope_fingerprint") or "")
        if envelope_fingerprint != str(reservation.get("envelope_fingerprint") or ""):
            blockers.append("runtime_session_envelope_reservation_mismatch")
        if attestation_id != str(reservation.get("attestation_id") or ""):
            blockers.append("runtime_session_attestation_reservation_mismatch")

        authorization_id = str(capital.get("authorization_id") or "")
        account_alias = str(scope.get("account_alias") or "")
        strategy_id = str(scope.get("strategy_id") or "")
        if authorization_id != str(reservation.get("authorization_id") or ""):
            blockers.append("runtime_session_authorization_reservation_mismatch")
        if account_alias != str(reservation.get("account_alias") or ""):
            blockers.append("runtime_session_account_reservation_mismatch")
        if strategy_id != str(reservation.get("strategy_id") or ""):
            blockers.append("runtime_session_strategy_reservation_mismatch")
        if not _ID_PATTERN.fullmatch(authorization_id) or not _ID_PATTERN.fullmatch(
            strategy_id
        ):
            blockers.append("runtime_session_scope_invalid")
        if (
            not account_alias
            or len(account_alias) > 128
            or any(ord(character) < 32 for character in account_alias)
        ):
            blockers.append("runtime_session_account_alias_invalid")

        effective_at = _parse_timestamp(envelope.get("requested_start_at"))
        expires_at = _parse_timestamp(envelope.get("requested_expires_at"))
        if effective_at is None or expires_at is None or expires_at <= effective_at:
            blockers.append("runtime_session_window_invalid")
        else:
            if now < effective_at:
                blockers.append("runtime_session_not_yet_effective")
            if now >= expires_at:
                blockers.append("runtime_session_expired")
            if effective_at.isoformat() != str(
                reservation.get("requested_start_at") or ""
            ):
                blockers.append("runtime_session_start_reservation_mismatch")
            if expires_at.isoformat() != str(
                reservation.get("requested_expires_at") or ""
            ):
                blockers.append("runtime_session_expiry_reservation_mismatch")

        try:
            max_rate = int(budget.get("max_order_rate_per_minute") or 0)
        except (TypeError, ValueError):
            max_rate = 0
        if max_rate <= 0 or max_rate > 600:
            blockers.append("runtime_session_rate_invalid")

        operator_id = str(attestation.get("operator_label") or "")
        if not _ID_PATTERN.fullmatch(operator_id):
            blockers.append("runtime_session_attesting_operator_invalid")
        issuance_core = {
            "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            "action": "issue_controlled_session",
            "reservation_id": normalized,
            "attestation_id": attestation_id,
            "envelope_fingerprint": envelope_fingerprint,
            "authorization_id": authorization_id,
            "account_alias": account_alias,
            "strategy_id": strategy_id,
            "operator_id": operator_id,
            "order_ids": sorted(order_ids),
            "effective_at": effective_at.isoformat() if effective_at else "",
            "expires_at": expires_at.isoformat() if expires_at else "",
            "max_order_rate_per_minute": max_rate,
        }
        issuance_fingerprint = _fingerprint(issuance_core)
        session_id = _fingerprint(
            {
                "domain": "karkinos.controlled_session.runtime_session_id.v1",
                "issuance_fingerprint": issuance_fingerprint,
            }
        )
        session_fingerprint = _fingerprint(
            {
                "domain": "karkinos.controlled_session.runtime_session.v1",
                "session_id": session_id,
                **issuance_core,
            }
        )
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **issuance_core,
            "issuance_fingerprint": issuance_fingerprint,
            "session_id": session_id,
            "session_fingerprint": session_fingerprint,
            "generated_at": now.isoformat(),
            "status": "ready_for_signed_issue" if not unique_blockers else "blocked",
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "required_operator_approval": {
                "action": "issue_controlled_session",
                "artifact_type": "controlled_session_issuance",
                "artifact_fingerprint": issuance_fingerprint,
            },
            "runtime_session_issued": False,
            "runtime_authority_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }

    def issue(
        self,
        *,
        reservation_id: str,
        issuance_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview_issuance(reservation_id=reservation_id)
        rejection_reasons: list[str] = []
        if issuance_fingerprint != preview["issuance_fingerprint"]:
            rejection_reasons.append("runtime_session_issuance_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "runtime_session_issuance_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("runtime_session_issuance_review_blocked")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="issue_controlled_session",
            expected_artifact_type="controlled_session_issuance",
            expected_artifact_fingerprint=preview["issuance_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("runtime_session_issue_operator_approval_blocked")
        elif approval.get("operator_id") != preview["operator_id"]:
            rejection_reasons.append("runtime_session_issue_operator_mismatch")
        if rejection_reasons:
            evidence = self._record_rejection(
                action="issue_controlled_session",
                artifact=preview,
                submitted_fingerprint=issuance_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise ControlledSessionRuntimeAuthorityRejected(
                "controlled session issuance rejected",
                evidence=evidence,
            )

        token = str(self._token_factory() or "")
        salt = str(self._salt_factory() or "")
        if not _TOKEN_PATTERN.fullmatch(token) or not re.fullmatch(
            r"^[a-f0-9]{32,128}$", salt
        ):
            evidence = self._record_rejection(
                action="issue_controlled_session",
                artifact=preview,
                submitted_fingerprint=issuance_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["runtime_session_secret_generation_failed"],
                transaction_blockers=[],
            )
            raise ControlledSessionRuntimeAuthorityRejected(
                "controlled session secret generation rejected",
                evidence=evidence,
            )
        now = _aware_utc(self._clock())
        payload = {
            **{
                key: preview[key]
                for key in (
                    "schema_version",
                    "session_id",
                    "session_fingerprint",
                    "issuance_fingerprint",
                    "reservation_id",
                    "attestation_id",
                    "envelope_fingerprint",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                    "operator_id",
                    "order_ids",
                    "effective_at",
                    "expires_at",
                    "max_order_rate_per_minute",
                )
            },
            "operator_approval_id": operator_approval_id,
            "status": "enabled",
            "runtime_session_issued": True,
            "runtime_authority_enabled": True,
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=True),
        }
        transaction = self._db.issue_controlled_session_sync(
            session={
                **{
                    key: payload[key]
                    for key in (
                        "session_id",
                        "session_fingerprint",
                        "issuance_fingerprint",
                        "reservation_id",
                        "attestation_id",
                        "envelope_fingerprint",
                        "authorization_id",
                        "account_alias",
                        "strategy_id",
                        "operator_id",
                        "operator_approval_id",
                        "order_ids",
                        "max_order_rate_per_minute",
                    )
                },
                "requested_start_at": payload["effective_at"],
                "requested_expires_at": payload["expires_at"],
                "effective_at_epoch_ms": int(
                    _parse_timestamp(payload["effective_at"]).timestamp() * 1000
                ),
                "expires_at_epoch_ms": int(
                    _parse_timestamp(payload["expires_at"]).timestamp() * 1000
                ),
                "token_salt": salt,
                "token_hash": _token_hash(token, salt),
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") not in {"enabled", "revoked"}:
            evidence = self._record_rejection(
                action="issue_controlled_session",
                artifact=preview,
                submitted_fingerprint=issuance_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["runtime_session_issuance_transaction_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise ControlledSessionRuntimeAuthorityRejected(
                "controlled session issuance transaction rejected",
                evidence=evidence,
            )
        response = _session_response(
            transaction.get("session") or {},
            reused=bool(transaction.get("reused")),
        )
        if transaction.get("reused"):
            return {
                **response,
                "runtime_authority_enabled": response.get("status") == "enabled",
                "safety": _safety_flags(
                    runtime_authority=response.get("status") == "enabled"
                ),
                "session_token": "",
                "session_token_issued": False,
                "session_token_notice": "token_not_reissued_on_idempotent_retry",
            }
        return {
            **response,
            "runtime_authority_enabled": True,
            "safety": _safety_flags(runtime_authority=True),
            "session_token": token,
            "session_token_issued": True,
            "session_token_notice": "store_securely_token_will_not_be_shown_again",
        }

    def resolve_current(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip().lower()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            return _blocked_session(normalized, ["runtime_session_id_invalid"])
        row = self._db.get_controlled_session_runtime_session_sync(normalized)
        if row is None:
            return _blocked_session(normalized, ["runtime_session_not_found"])
        response = _session_response(row, reused=False)
        now = _aware_utc(self._clock())
        blockers: list[str] = []
        if response.get("status") != "enabled":
            blockers.append("runtime_session_not_enabled")
        effective_at = _parse_timestamp(response.get("effective_at"))
        expires_at = _parse_timestamp(response.get("expires_at"))
        if effective_at is None or expires_at is None:
            blockers.append("runtime_session_window_invalid")
        else:
            if now < effective_at:
                blockers.append("runtime_session_not_yet_effective")
            if now >= expires_at:
                blockers.append("runtime_session_expired")
        pause_state = (
            self._db.get_controlled_session_runtime_state_sync(normalized) or {}
        )
        if pause_state.get("status") == "paused":
            blockers.append("runtime_session_paused")
        reservation = self._resolve_provider(
            self._reservation_provider,
            str(response.get("reservation_id") or ""),
            unavailable="runtime_session_reservation_provider_unavailable",
            failed="runtime_session_reservation_provider_failed",
            blockers=blockers,
        )
        if reservation.get("resolution_status") != ("current_reserved_non_executing"):
            blockers.append("runtime_session_reservation_not_current")
        for field in (
            "reservation_id",
            "attestation_id",
            "envelope_fingerprint",
            "authorization_id",
            "account_alias",
            "strategy_id",
        ):
            if str(response.get(field) or "") != str(reservation.get(field) or ""):
                blockers.append(f"runtime_session_current_{field}_mismatch")
        unique_blockers = list(dict.fromkeys(blockers))
        if unique_blockers:
            return {
                **response,
                "status": "blocked",
                "blockers": unique_blockers,
                "session_authority_verified": False,
                "budget_reservation_verified": False,
                "upstream_gates_clear": False,
                "kill_switch_clear": False,
                "persistent_session_state_verified": True,
                "runtime_authentication_verified": False,
                "runtime_rate_limiter_enabled": False,
                "broker_submission_enabled": False,
                "runtime_authority_enabled": False,
                "safety": _safety_flags(runtime_authority=False),
            }
        return {
            **response,
            "status": "current_enabled_bounded_session",
            "blockers": [],
            "session_authority_verified": True,
            "budget_reservation_verified": True,
            "upstream_gates_clear": True,
            "kill_switch_clear": True,
            "persistent_session_state_verified": True,
            "runtime_authentication_verified": False,
            "runtime_rate_limiter_enabled": True,
            "broker_submission_enabled": False,
            "runtime_authority_enabled": True,
            "safety": _safety_flags(runtime_authority=True),
        }

    def authenticate(self, session_id: str, session_token: str) -> dict[str, Any]:
        current = self.resolve_current(session_id)
        if current.get("status") != "current_enabled_bounded_session":
            return current
        if not self._token_matches(
            str(current.get("session_id") or ""),
            session_token,
        ):
            return {
                **current,
                "status": "blocked",
                "blockers": ["runtime_session_authentication_failed"],
                "session_authority_verified": False,
                "runtime_authentication_verified": False,
                "runtime_rate_limiter_enabled": False,
            }
        return {
            **current,
            "runtime_authentication_verified": True,
        }

    def resolve_for_monitoring(self, session_id: str) -> dict[str, Any]:
        """Resolve immutable identity even when an upstream gate has degraded."""
        normalized = str(session_id or "").strip().lower()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            return _blocked_session(normalized, ["runtime_session_id_invalid"])
        row = self._db.get_controlled_session_runtime_session_sync(normalized)
        if row is None:
            return _blocked_session(normalized, ["runtime_session_not_found"])
        response = _session_response(row, reused=False)
        if response.get("status") != "enabled":
            return {
                **response,
                "status": "blocked",
                "blockers": ["runtime_session_not_monitorable"],
                "monitoring_identity_verified": False,
                "runtime_authentication_verified": False,
                "runtime_authority_enabled": False,
                "safety": _safety_flags(runtime_authority=False),
            }
        return {
            **response,
            "status": "monitorable_bounded_session",
            "blockers": [],
            "session_authority_verified": False,
            "monitoring_identity_verified": True,
            "persistent_session_state_verified": True,
            "runtime_authentication_verified": False,
            "runtime_authority_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }

    def authenticate_for_monitoring(
        self,
        session_id: str,
        session_token: str,
    ) -> dict[str, Any]:
        """Authenticate a self-check without treating degraded gates as authority."""
        monitored = self.resolve_for_monitoring(session_id)
        if monitored.get("status") != "monitorable_bounded_session":
            return monitored
        if not self._token_matches(
            str(monitored.get("session_id") or ""),
            session_token,
        ):
            return {
                **monitored,
                "status": "blocked",
                "blockers": ["runtime_session_authentication_failed"],
                "monitoring_identity_verified": False,
                "runtime_authentication_verified": False,
            }
        return {
            **monitored,
            "runtime_authentication_verified": True,
        }

    def list_sessions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_session_runtime_sessions_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [
            {
                **_session_response(row, reused=False),
                "current_authority_not_evaluated": True,
                "runtime_authority_enabled": False,
            }
            for row in rows
        ]

    def _token_matches(self, session_id: str, session_token: str) -> bool:
        normalized_token = str(session_token or "")
        row = self._db.get_controlled_session_runtime_session_sync(session_id) or {}
        stored_hash = str(row.get("token_hash") or "")
        salt = str(row.get("token_salt") or "")
        return bool(
            _TOKEN_PATTERN.fullmatch(normalized_token)
            and stored_hash
            and salt
            and hmac.compare_digest(_token_hash(normalized_token, salt), stored_hash)
        )

    def preview_revocation(
        self,
        *,
        session_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        normalized = str(session_id or "").strip().lower()
        normalized_reason = str(reason_code or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            blockers.append("runtime_session_id_invalid")
        if normalized_reason not in CONTROLLED_SESSION_REVOCATION_REASONS:
            blockers.append("runtime_session_revocation_reason_invalid")
        row = self._db.get_controlled_session_runtime_session_sync(normalized) or {}
        if not row:
            blockers.append("runtime_session_not_found")
        response = _session_response(row, reused=False) if row else {}
        if response and response.get("status") not in {"enabled", "revoked"}:
            blockers.append("runtime_session_revocation_state_invalid")
        core = {
            "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            "action": "revoke_controlled_session",
            "session_id": normalized,
            "session_fingerprint": str(response.get("session_fingerprint") or ""),
            "reservation_id": str(response.get("reservation_id") or ""),
            "reason_code": normalized_reason,
        }
        fingerprint = _fingerprint(core)
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **core,
            "revocation_fingerprint": fingerprint,
            "revocation_id": _fingerprint(
                {
                    "domain": "karkinos.controlled_session.revocation.v1",
                    **core,
                }
            ),
            "status": (
                "ready_for_signed_revocation" if not unique_blockers else "blocked"
            ),
            "ready": not unique_blockers,
            "already_revoked": response.get("status") == "revoked",
            "blockers": unique_blockers,
            "required_operator_approval": {
                "action": "revoke_controlled_session",
                "artifact_type": "controlled_session_revocation",
                "artifact_fingerprint": fingerprint,
            },
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }

    def revoke(
        self,
        *,
        session_id: str,
        reason_code: str,
        revocation_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview_revocation(
            session_id=session_id,
            reason_code=reason_code,
        )
        rejection_reasons: list[str] = []
        if revocation_fingerprint != preview["revocation_fingerprint"]:
            rejection_reasons.append("runtime_session_revocation_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "runtime_session_revocation_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("runtime_session_revocation_review_blocked")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="revoke_controlled_session",
            expected_artifact_type="controlled_session_revocation",
            expected_artifact_fingerprint=preview["revocation_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("runtime_session_revoke_operator_approval_blocked")
        if rejection_reasons:
            evidence = self._record_rejection(
                action="revoke_controlled_session",
                artifact=preview,
                submitted_fingerprint=revocation_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise ControlledSessionRuntimeAuthorityRejected(
                "controlled session revocation rejected",
                evidence=evidence,
            )
        now = _aware_utc(self._clock())
        payload = {
            **{
                key: preview[key]
                for key in (
                    "schema_version",
                    "revocation_id",
                    "revocation_fingerprint",
                    "session_id",
                    "session_fingerprint",
                    "reservation_id",
                    "reason_code",
                )
            },
            "operator_id": str(approval.get("operator_id") or ""),
            "operator_approval_id": operator_approval_id,
            "status": "revoked",
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }
        transaction = self._db.revoke_controlled_session_sync(
            revocation={
                **{
                    key: payload[key]
                    for key in (
                        "revocation_id",
                        "revocation_fingerprint",
                        "session_id",
                        "session_fingerprint",
                        "reason_code",
                        "operator_id",
                        "operator_approval_id",
                    )
                },
                "revoked_at_epoch_ms": int(now.timestamp() * 1000),
                "revoked_at": now.isoformat(),
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") != "revoked":
            evidence = self._record_rejection(
                action="revoke_controlled_session",
                artifact=preview,
                submitted_fingerprint=revocation_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["runtime_session_revocation_transaction_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise ControlledSessionRuntimeAuthorityRejected(
                "controlled session revocation transaction rejected",
                evidence=evidence,
            )
        return {
            **_revocation_response(
                transaction.get("revocation") or {},
                reused=bool(transaction.get("reused")),
            ),
            "current_session": _session_response(
                transaction.get("session") or {},
                reused=False,
            ),
        }

    def list_revocations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_session_revocations_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [_revocation_response(row, reused=False) for row in rows]

    def _resolve_provider(
        self,
        provider: Callable[[str], dict[str, Any]] | None,
        identifier: str,
        *,
        unavailable: str,
        failed: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        if not callable(provider):
            blockers.append(unavailable)
            return {}
        try:
            value = provider(identifier) or {}
        except Exception:
            blockers.append(failed)
            return {}
        return value if isinstance(value, dict) else {}

    def _record_rejection(
        self,
        *,
        action: str,
        artifact: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            "status": "rejected",
            "action": action,
            "session_id": str(artifact.get("session_id") or ""),
            "reservation_id": str(artifact.get("reservation_id") or ""),
            "expected_fingerprint": str(
                artifact.get("issuance_fingerprint")
                or artifact.get("revocation_fingerprint")
                or ""
            ),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in artifact.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "runtime_session_issued": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_RUNTIME_AUTHORITY_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_SESSION_RUNTIME_AUTHORITY_EVENT_SOURCE,
            source_ref=payload["expected_fingerprint"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            **payload,
        }


def _session_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "session_id": str(row.get("session_id") or payload.get("session_id") or ""),
        "session_fingerprint": str(
            row.get("session_fingerprint") or payload.get("session_fingerprint") or ""
        ),
        "issuance_fingerprint": str(
            row.get("issuance_fingerprint") or payload.get("issuance_fingerprint") or ""
        ),
        "reservation_id": str(
            row.get("reservation_id") or payload.get("reservation_id") or ""
        ),
        "attestation_id": str(
            row.get("attestation_id") or payload.get("attestation_id") or ""
        ),
        "envelope_fingerprint": str(
            row.get("envelope_fingerprint") or payload.get("envelope_fingerprint") or ""
        ),
        "authorization_id": str(
            row.get("authorization_id") or payload.get("authorization_id") or ""
        ),
        "account_alias": str(
            row.get("account_alias") or payload.get("account_alias") or ""
        ),
        "strategy_id": str(row.get("strategy_id") or payload.get("strategy_id") or ""),
        "order_ids": _json_list(
            row.get("order_ids_json") or payload.get("order_ids") or []
        ),
        "effective_at": str(
            row.get("effective_at") or payload.get("effective_at") or ""
        ),
        "expires_at": str(row.get("expires_at") or payload.get("expires_at") or ""),
        "max_order_rate_per_minute": int(
            row.get("max_order_rate_per_minute")
            or payload.get("max_order_rate_per_minute")
            or 0
        ),
        "status": str(row.get("status") or payload.get("status") or "not_found"),
        "persisted": bool(row),
        "reused": reused,
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "raw_token_stored": False,
        "session_token": "",
        "automatic_resume_enabled": False,
        "broker_submission_enabled": False,
        "safety": _safety_flags(runtime_authority=False),
    }


def _revocation_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "persisted": bool(row),
        "reused": reused,
        "revoked_at": str(row.get("revoked_at") or ""),
        "broker_submission_enabled": False,
        "safety": _safety_flags(runtime_authority=False),
    }


def _blocked_session(session_id: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
        "status": "blocked",
        "session_id": session_id,
        "session_fingerprint": "",
        "reservation_id": "",
        "blockers": list(dict.fromkeys(blockers)),
        "session_authority_verified": False,
        "budget_reservation_verified": False,
        "upstream_gates_clear": False,
        "kill_switch_clear": False,
        "persistent_session_state_verified": False,
        "runtime_authentication_verified": False,
        "runtime_rate_limiter_enabled": False,
        "broker_submission_enabled": False,
        "safety": _safety_flags(runtime_authority=False),
    }


def _token_hash(token: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{token}".encode("utf-8")).hexdigest()


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _parse_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safety_flags(*, runtime_authority: bool) -> dict[str, bool]:
    return {
        "runtime_session_authority_enabled": runtime_authority,
        "does_not_contact_broker": True,
        "does_not_submit_or_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_store_raw_session_token": True,
        "does_not_auto_resume_renew_or_expand": True,
        "does_not_grant_or_scale_capital_authority": True,
    }
