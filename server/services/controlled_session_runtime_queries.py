"""Read-side status, authority resolution, and token verification."""

from __future__ import annotations

import hmac
from typing import Any

from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_STATUS_SCHEMA_VERSION,
)
from server.services.controlled_session_runtime_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_session_runtime_values import (
    TOKEN_PATTERN as _TOKEN_PATTERN,
)
from server.services.controlled_session_runtime_values import aware_utc as _aware_utc
from server.services.controlled_session_runtime_values import (
    blocked_session as _blocked_session,
)
from server.services.controlled_session_runtime_values import (
    parse_timestamp as _parse_timestamp,
)
from server.services.controlled_session_runtime_values import (
    safety_flags as _safety_flags,
)
from server.services.controlled_session_runtime_values import (
    session_response as _session_response,
)
from server.services.controlled_session_runtime_values import token_hash as _token_hash


class RuntimeAuthorityQueryMixin:
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
            "requires_replacement_operator_signature": True,
            "session_issue_endpoint_exposed": True,
            "session_revoke_endpoint_exposed": True,
            "session_replacement_endpoint_exposed": True,
            "session_resume_endpoint_exposed": False,
            "session_renew_endpoint_exposed": False,
            "session_widen_endpoint_exposed": False,
            "raw_token_storage_enabled": False,
            "session_token_return_policy": "first_successful_issue_response_only",
            "runtime_rate_admission_requires_token": True,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
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
