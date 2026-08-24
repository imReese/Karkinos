"""Signed attestation commands and current-source resolution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
    CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
    CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
    CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
)
from server.services.controlled_session_envelope_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_session_envelope_values import (
    blocked_attestation_resolution as _blocked_attestation_resolution,
)
from server.services.controlled_session_envelope_values import (
    event_response as _event_response,
)
from server.services.controlled_session_envelope_values import (
    parse_timestamp as _parse_timestamp,
)
from server.services.controlled_session_envelope_values import (
    safety_flags as _safety_flags,
)


class ControlledSessionEnvelopeAttestationMixin:
    def record_attestation(
        self,
        *,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprints: dict[str, str],
        session_start_account_truth_fingerprint: str,
        per_symbol_runtime_limits: dict[str, Any],
        order_ids: list[str] | tuple[str, ...],
        requested_start_at: datetime,
        requested_expires_at: datetime,
        envelope_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        envelope = self.preview_envelope(
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprints=(
                execution_gateway_verification_fingerprints
            ),
            session_start_account_truth_fingerprint=(
                session_start_account_truth_fingerprint
            ),
            per_symbol_runtime_limits=per_symbol_runtime_limits,
            order_ids=order_ids,
            requested_start_at=requested_start_at,
            requested_expires_at=requested_expires_at,
        )
        rejection_reasons: list[str] = []
        if not str(operator_label or "").strip():
            rejection_reasons.append("operator_label_missing")
        if acknowledgement != CONTROLLED_SESSION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if envelope_fingerprint != envelope["envelope_fingerprint"]:
            rejection_reasons.append("envelope_fingerprint_mismatch")
        if envelope["review_blockers"]:
            rejection_reasons.append("envelope_review_blocked")
        operator_approval, approval_blockers = self._resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            expected_action="attest_controlled_session_envelope",
            expected_artifact_type="controlled_session_envelope",
            expected_artifact_fingerprint=envelope["envelope_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("operator_approval_blocked")
        elif str(operator_label or "").strip() != operator_approval["operator_id"]:
            rejection_reasons.append("operator_label_approval_mismatch")
        status = "rejected" if rejection_reasons else "recorded_verified_identity"
        attempt = self._record_attempt(
            envelope=envelope,
            submitted_envelope_fingerprint=envelope_fingerprint,
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprints=(
                execution_gateway_verification_fingerprints
            ),
            session_start_account_truth_fingerprint=(
                session_start_account_truth_fingerprint
            ),
            per_symbol_runtime_limits=per_symbol_runtime_limits,
            operator_label=str(operator_label or "").strip(),
            operator_approval=operator_approval,
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise self._attestation_rejection(
                "controlled session attestation rejected: "
                + ", ".join(rejection_reasons),
                evidence=attempt,
            )
        return attempt

    def list_attestations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def resolve_attestation(self, attestation_id: str) -> dict[str, Any]:
        """Re-resolve every mutable source behind one signed envelope."""
        normalized = str(attestation_id or "").strip().lower()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            return _blocked_attestation_resolution(
                normalized,
                ["controlled_session_attestation_id_invalid"],
            )
        rows = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=normalized,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            return _blocked_attestation_resolution(
                normalized,
                ["controlled_session_attestation_not_found"],
            )
        recorded = _event_response(rows[0], reused=False)
        blockers: list[str] = []
        if recorded.get("schema_version") != (
            CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION
        ):
            blockers.append("controlled_session_attestation_schema_invalid")
        if recorded.get("status") != "recorded_verified_identity":
            blockers.append("controlled_session_attestation_not_verified")
        start_at = _parse_timestamp(recorded.get("requested_start_at"))
        expires_at = _parse_timestamp(recorded.get("requested_expires_at"))
        if start_at is None or expires_at is None:
            blockers.append("controlled_session_attestation_window_invalid")

        current_envelope: dict[str, Any] = {}
        if start_at is not None and expires_at is not None:
            try:
                current_envelope = self.preview_envelope(
                    capital_evaluation_input_fingerprint=str(
                        recorded.get("capital_evaluation_input_fingerprint") or ""
                    ),
                    prior_batch_reconciliation_fingerprint=str(
                        recorded.get("prior_batch_reconciliation_fingerprint") or ""
                    ),
                    execution_gateway_verification_fingerprints=(
                        recorded.get("execution_gateway_verification_fingerprints")
                        if isinstance(
                            recorded.get("execution_gateway_verification_fingerprints"),
                            dict,
                        )
                        else {}
                    ),
                    session_start_account_truth_fingerprint=str(
                        recorded.get("session_start_account_truth_fingerprint") or ""
                    ),
                    per_symbol_runtime_limits=(
                        recorded.get("per_symbol_runtime_limits")
                        if isinstance(recorded.get("per_symbol_runtime_limits"), dict)
                        else {}
                    ),
                    order_ids=[str(item) for item in recorded.get("order_ids") or []],
                    requested_start_at=start_at,
                    requested_expires_at=expires_at,
                )
            except Exception:
                blockers.append(
                    "controlled_session_attestation_source_resolution_failed"
                )
        if current_envelope:
            if current_envelope.get("envelope_fingerprint") != recorded.get(
                "envelope_fingerprint"
            ):
                blockers.append("controlled_session_envelope_source_changed")
            if current_envelope.get("review_blockers"):
                blockers.append("controlled_session_envelope_currently_blocked")

        operator_approval, approval_blockers = self._resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=str(recorded.get("operator_approval_id") or ""),
            expected_action="attest_controlled_session_envelope",
            expected_artifact_type="controlled_session_envelope",
            expected_artifact_fingerprint=str(
                recorded.get("envelope_fingerprint") or ""
            ),
            clock=self._clock,
        )
        if approval_blockers:
            blockers.append("controlled_session_operator_approval_blocked")
        elif str(recorded.get("operator_label") or "") != str(
            operator_approval.get("operator_id") or ""
        ):
            blockers.append("controlled_session_operator_identity_changed")
        unique_blockers = list(dict.fromkeys(blockers))
        if unique_blockers:
            return _blocked_attestation_resolution(normalized, unique_blockers)
        return {
            "schema_version": CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
            "status": "current_verified_non_executing",
            "attestation_id": normalized,
            "envelope_fingerprint": str(recorded["envelope_fingerprint"]),
            "operator_label": str(recorded.get("operator_label") or ""),
            "operator_approval_id": str(recorded.get("operator_approval_id") or ""),
            "recorded_at": str(recorded.get("recorded_at") or ""),
            "current_envelope": current_envelope,
            "blockers": [],
            "runtime_session_status": "not_issued",
            "operator_identity_verified": True,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }
