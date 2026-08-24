"""Signed one-way revocation workflow for controlled runtime sessions."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_REVOCATION_REASONS,
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
)
from server.services.controlled_session_runtime_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_session_runtime_values import aware_utc as _aware_utc
from server.services.controlled_session_runtime_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_session_runtime_values import (
    revocation_response as _revocation_response,
)
from server.services.controlled_session_runtime_values import (
    safety_flags as _safety_flags,
)
from server.services.controlled_session_runtime_values import (
    session_response as _session_response,
)


class RuntimeAuthorityRevocationMixin:
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
        approval, approval_blockers = self._resolve_operator_approval(
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
            raise self._runtime_authority_rejection(
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
            raise self._runtime_authority_rejection(
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
