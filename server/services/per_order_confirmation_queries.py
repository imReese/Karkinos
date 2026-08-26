"""Persisted queries and current-state resolution for per-order confirmation."""

from __future__ import annotations

from typing import Any

import server.services.per_order_confirmation_values as values
from server.contracts.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
    PER_ORDER_CONFIRMATION_EVENT_SOURCE,
    PER_ORDER_CONFIRMATION_EVENT_TYPE,
    PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
)
from server.services.operator_approval import resolve_operator_approval


class PerOrderConfirmationQueryMixin:
    def resolve_confirmation(self, confirmation_id: str) -> dict[str, Any]:
        """Re-resolve one recorded confirmation against current gate evidence."""

        normalized = str(confirmation_id or "").strip().lower()
        if not values.FINGERPRINT_PATTERN.fullmatch(normalized):
            return values.blocked_confirmation_resolution(
                normalized,
                ["per_order_confirmation_id_invalid"],
            )
        rows = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=normalized,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            return values.blocked_confirmation_resolution(
                normalized,
                ["per_order_confirmation_not_found"],
            )
        recorded = values.event_response(rows[0], reused=False)
        blockers: list[str] = []
        if recorded.get("status") != "recorded_verified_identity":
            blockers.append("per_order_confirmation_not_verified")
        order_id = str(recorded.get("order_id") or "")
        capital_fingerprint = str(
            recorded.get("capital_evaluation_input_fingerprint") or ""
        )
        prior_batch_fingerprint = str(
            recorded.get("prior_batch_reconciliation_fingerprint") or ""
        )
        gateway_fingerprint = str(
            recorded.get("execution_gateway_verification_fingerprint") or ""
        )
        if not values.FINGERPRINT_PATTERN.fullmatch(prior_batch_fingerprint):
            blockers.append("per_order_confirmation_prior_batch_evidence_missing")
        try:
            dossier = self.preview_dossier(
                order_id,
                capital_evaluation_input_fingerprint=capital_fingerprint,
                prior_batch_reconciliation_fingerprint=prior_batch_fingerprint,
                execution_gateway_verification_fingerprint=gateway_fingerprint,
            )
        except (KeyError, ValueError):
            dossier = {}
            blockers.append("per_order_confirmation_current_dossier_unavailable")
        if str(dossier.get("dossier_fingerprint") or "") != str(
            recorded.get("dossier_fingerprint") or ""
        ):
            blockers.append("per_order_confirmation_dossier_changed")
        if dossier.get("review_blockers"):
            blockers.append("per_order_confirmation_current_review_blocked")
        current_confirmation = values.mapping(dossier.get("confirmation"))
        if str(current_confirmation.get("confirmation_id") or "") != normalized:
            blockers.append("per_order_confirmation_not_current")
        approval, approval_blockers = resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=str(recorded.get("operator_approval_id") or ""),
            expected_action="attest_per_order_dossier",
            expected_artifact_type="per_order_dossier",
            expected_artifact_fingerprint=str(
                recorded.get("dossier_fingerprint") or ""
            ),
            clock=self._clock,
        )
        if approval_blockers:
            blockers.append("per_order_confirmation_operator_approval_not_current")
        elif str(approval.get("operator_id") or "") != str(
            recorded.get("operator_label") or ""
        ):
            blockers.append("per_order_confirmation_operator_mismatch")
        hard_blockers = [
            str(item) for item in dossier.get("hard_submission_blockers") or []
        ]
        expected_foundation_blockers = {
            "operator_identity_unverified",
            "runtime_execution_authority_disabled",
            "live_gateway_not_implemented",
            "broker_submission_disabled",
        }
        unexpected_hard_blockers = [
            item for item in hard_blockers if item not in expected_foundation_blockers
        ]
        if unexpected_hard_blockers:
            blockers.append("per_order_confirmation_unexpected_hard_blockers")
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            "schema_version": PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
            "status": (
                "current_verified_non_authorizing_confirmation"
                if not unique_blockers
                else "blocked"
            ),
            "confirmation_id": normalized,
            "order_id": order_id,
            "dossier_fingerprint": str(recorded.get("dossier_fingerprint") or ""),
            "capital_evaluation_input_fingerprint": capital_fingerprint,
            "prior_batch_reconciliation_fingerprint": prior_batch_fingerprint,
            "execution_gateway_verification_fingerprint": gateway_fingerprint,
            "operator_id": str(recorded.get("operator_label") or ""),
            "operator_approval_id": str(recorded.get("operator_approval_id") or ""),
            "current_dossier": dossier,
            "expected_foundation_blockers": sorted(expected_foundation_blockers),
            "unexpected_hard_blockers": unexpected_hard_blockers,
            "blockers": unique_blockers,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
            "safety": values.safety_flags(),
        }

    def list_confirmations(
        self,
        order_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            response = values.event_response(row, reused=False)
            if str(response.get("order_id") or "") == str(order_id):
                results.append(response)
        return results

    def _require_order(self, order_id: str) -> dict[str, Any]:
        order = self._db.get_oms_order_sync(order_id)
        if order is None:
            raise KeyError(f"OMS order not found: {order_id}")
        return dict(order)

    def _latest_matching_confirmation(
        self,
        order_id: str,
        *,
        dossier_fingerprint: str,
    ) -> dict[str, Any]:
        for item in self.list_confirmations(order_id, limit=100):
            if (
                item.get("status") == "recorded_verified_identity"
                and item.get("dossier_fingerprint") == dossier_fingerprint
            ):
                return {
                    "status": "recorded_verified_identity",
                    "confirmation_id": item.get("confirmation_id"),
                    "recorded_at": item.get("recorded_at"),
                    "operator_label": item.get("operator_label"),
                    "operator_identity_verified": True,
                    "authorizes_execution": False,
                }
        return {
            "status": "missing",
            "confirmation_id": "",
            "recorded_at": "",
            "operator_label": "",
            "operator_identity_verified": False,
            "authorizes_execution": False,
        }
