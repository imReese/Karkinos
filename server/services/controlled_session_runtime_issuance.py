"""Issuance preview and signed command for controlled runtime sessions."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
)
from server.services.controlled_session_runtime_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_session_runtime_values import ID_PATTERN as _ID_PATTERN
from server.services.controlled_session_runtime_values import (
    SALT_PATTERN as _SALT_PATTERN,
)
from server.services.controlled_session_runtime_values import (
    TOKEN_PATTERN as _TOKEN_PATTERN,
)
from server.services.controlled_session_runtime_values import aware_utc as _aware_utc
from server.services.controlled_session_runtime_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_session_runtime_values import mapping as _mapping
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


class RuntimeAuthorityIssuanceMixin:
    def preview_issuance(
        self,
        *,
        reservation_id: str,
        _replacement_of_session_id: str = "",
    ) -> dict[str, Any]:
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
        paused_scope = None
        if authorization_id and account_alias and strategy_id:
            paused_scope = self._db.find_enabled_paused_controlled_session_sync(
                authorization_id=authorization_id,
                account_alias=account_alias,
                strategy_id=strategy_id,
                now_epoch_ms=int(now.timestamp() * 1000),
            )
        if paused_scope is not None and str(
            paused_scope.get("session_id") or ""
        ) != str(_replacement_of_session_id or ""):
            blockers.append("runtime_session_paused_scope_requires_signed_replacement")

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
        approval, approval_blockers = self._resolve_operator_approval(
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
            raise self._runtime_authority_rejection(
                "controlled session issuance rejected",
                evidence=evidence,
            )

        token = str(self._token_factory() or "")
        salt = str(self._salt_factory() or "")
        if not _TOKEN_PATTERN.fullmatch(token) or not _SALT_PATTERN.fullmatch(salt):
            evidence = self._record_rejection(
                action="issue_controlled_session",
                artifact=preview,
                submitted_fingerprint=issuance_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["runtime_session_secret_generation_failed"],
                transaction_blockers=[],
            )
            raise self._runtime_authority_rejection(
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
            raise self._runtime_authority_rejection(
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
