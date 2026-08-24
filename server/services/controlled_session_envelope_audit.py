"""Append-only attestation audit evidence for controlled-session envelopes."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
    CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
    CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
    CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
)
from server.services.controlled_session_envelope_values import aware_utc as _aware_utc
from server.services.controlled_session_envelope_values import (
    decimal_string as _decimal_string,
)
from server.services.controlled_session_envelope_values import decimal_value as _decimal
from server.services.controlled_session_envelope_values import (
    event_response as _event_response,
)
from server.services.controlled_session_envelope_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_session_envelope_values import (
    safety_flags as _safety_flags,
)


class ControlledSessionEnvelopeAuditMixin:
    def _record_attempt(
        self,
        *,
        envelope: dict[str, Any],
        submitted_envelope_fingerprint: str,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprints: dict[str, str],
        session_start_account_truth_fingerprint: str,
        per_symbol_runtime_limits: dict[str, Any],
        operator_label: str,
        operator_approval: dict[str, Any],
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        identity = {
            "envelope_fingerprint": envelope["envelope_fingerprint"],
            "submitted_envelope_fingerprint": submitted_envelope_fingerprint,
            "capital_evaluation_input_fingerprint": (
                capital_evaluation_input_fingerprint
            ),
            "prior_batch_reconciliation_fingerprint": (
                prior_batch_reconciliation_fingerprint
            ),
            "execution_gateway_verification_fingerprints": dict(
                sorted(
                    (
                        str(order_id or ""),
                        str(fingerprint or ""),
                    )
                    for order_id, fingerprint in (
                        execution_gateway_verification_fingerprints or {}
                    ).items()
                )
            ),
            "resolved_execution_gateway_verification_fingerprints": {
                str(item.get("order_id") or ""): str(
                    item.get("verification_fingerprint") or ""
                )
                for item in envelope.get("execution_gateway_verifications") or []
            },
            "session_start_account_truth_fingerprint": (
                session_start_account_truth_fingerprint
            ),
            "per_symbol_runtime_limits": {
                str(symbol): _decimal_string(_decimal(value))
                for symbol, value in sorted((per_symbol_runtime_limits or {}).items())
            },
            "resolved_session_start_account_truth_fingerprint": str(
                (envelope.get("session_start_account_truth") or {}).get(
                    "account_truth_fingerprint"
                )
                or ""
            ),
            "order_ids": list(envelope["order_ids"]),
            "requested_start_at": envelope["requested_start_at"],
            "requested_expires_at": envelope["requested_expires_at"],
            "operator_label": operator_label,
            "operator_approval_id": operator_approval.get("approval_id"),
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": rejection_reasons,
        }
        attestation_id = _fingerprint(identity)
        payload = {
            "schema_version": CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
            "attestation_id": attestation_id,
            **identity,
            "review_status": envelope["review_status"],
            "review_blockers": list(envelope["review_blockers"]),
            "hard_submission_blockers": [
                blocker
                for blocker in envelope["hard_submission_blockers"]
                if blocker != "operator_identity_unverified"
                or not operator_approval.get("operator_identity_verified")
            ],
            "operator_approval": operator_approval,
            "runtime_session_status": "not_issued",
            "operator_identity_verified": bool(
                operator_approval.get("operator_identity_verified")
            ),
            "authorizes_execution": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=attestation_id,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        now = _aware_utc(self._clock())
        self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=attestation_id,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            source_ref=envelope["envelope_fingerprint"],
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=attestation_id,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("controlled session attestation was not recorded")
        return _event_response(saved[0], reused=False)

    def _latest_matching_attestation(
        self,
        envelope_fingerprint: str,
    ) -> dict[str, Any]:
        for item in self.list_attestations(limit=500):
            if (
                item.get("status") == "recorded_verified_identity"
                and item.get("envelope_fingerprint") == envelope_fingerprint
            ):
                return {
                    "status": "recorded_verified_identity",
                    "attestation_id": item.get("attestation_id"),
                    "recorded_at": item.get("recorded_at"),
                    "operator_label": item.get("operator_label"),
                    "operator_identity_verified": True,
                    "authorizes_execution": False,
                }
        return {
            "status": "missing",
            "attestation_id": "",
            "recorded_at": "",
            "operator_label": "",
            "operator_identity_verified": False,
            "authorizes_execution": False,
        }
