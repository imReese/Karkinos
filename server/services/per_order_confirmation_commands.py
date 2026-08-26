"""Audited commands for evidence-only per-order confirmation."""

from __future__ import annotations

from typing import Any

import server.services.per_order_confirmation_values as values
from server.contracts.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
    PER_ORDER_CONFIRMATION_EVENT_SOURCE,
    PER_ORDER_CONFIRMATION_EVENT_TYPE,
    PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
)
from server.services.operator_approval import resolve_operator_approval


class PerOrderConfirmationCommandMixin:
    def record_confirmation(
        self,
        order_id: str,
        *,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprint: str,
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        dossier = self.preview_dossier(
            order_id,
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprint=(
                execution_gateway_verification_fingerprint
            ),
        )
        rejection_reasons: list[str] = []
        if not str(operator_label or "").strip():
            rejection_reasons.append("operator_label_missing")
        if acknowledgement != PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if dossier_fingerprint != dossier["dossier_fingerprint"]:
            rejection_reasons.append("dossier_fingerprint_mismatch")
        if dossier["review_blockers"]:
            rejection_reasons.append("dossier_review_blocked")
        operator_approval, approval_blockers = resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            expected_action="attest_per_order_dossier",
            expected_artifact_type="per_order_dossier",
            expected_artifact_fingerprint=dossier["dossier_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("operator_approval_blocked")
        elif str(operator_label or "").strip() != operator_approval["operator_id"]:
            rejection_reasons.append("operator_label_approval_mismatch")

        status = "rejected" if rejection_reasons else "recorded_verified_identity"
        attempt = self._record_attempt(
            order_id=order_id,
            dossier=dossier,
            submitted_dossier_fingerprint=dossier_fingerprint,
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprint=(
                execution_gateway_verification_fingerprint
            ),
            operator_label=str(operator_label or "").strip(),
            operator_approval=operator_approval,
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise self._confirmation_rejection(
                "per-order confirmation rejected: " + ", ".join(rejection_reasons),
                evidence=attempt,
            )
        return attempt

    def _record_attempt(
        self,
        *,
        order_id: str,
        dossier: dict[str, Any],
        submitted_dossier_fingerprint: str,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprint: str,
        operator_label: str,
        operator_approval: dict[str, Any],
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        recorded_at = values.aware_utc(self._clock())
        identity = {
            "order_id": order_id,
            "dossier_fingerprint": dossier["dossier_fingerprint"],
            "submitted_dossier_fingerprint": submitted_dossier_fingerprint,
            "capital_evaluation_input_fingerprint": (
                capital_evaluation_input_fingerprint
            ),
            "prior_batch_reconciliation_fingerprint": (
                prior_batch_reconciliation_fingerprint
            ),
            "execution_gateway_verification_fingerprint": (
                execution_gateway_verification_fingerprint
            ),
            "operator_label": operator_label,
            "operator_approval_id": operator_approval.get("approval_id"),
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": rejection_reasons,
        }
        confirmation_id = values.fingerprint(identity)
        payload = {
            "schema_version": PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
            "confirmation_id": confirmation_id,
            **identity,
            "order_fingerprint": dossier["order_fingerprint"],
            "review_status": dossier["review_status"],
            "review_blockers": list(dossier["review_blockers"]),
            "hard_submission_blockers": [
                blocker
                for blocker in dossier["hard_submission_blockers"]
                if blocker != "operator_identity_unverified"
                or not operator_approval.get("operator_identity_verified")
            ],
            "operator_approval": operator_approval,
            "operator_identity_verified": bool(
                operator_approval.get("operator_identity_verified")
            ),
            "authorizes_execution": False,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "safety": values.safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=confirmation_id,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return values.event_response(existing[0], reused=True)
        self._db.append_event_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            timestamp=recorded_at.isoformat(),
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=confirmation_id,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            source_ref=order_id,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=confirmation_id,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("per-order confirmation evidence was not recorded")
        return values.event_response(saved[0], reused=False)
