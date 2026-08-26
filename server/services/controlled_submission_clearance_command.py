"""Human-signed exact-terminal clearance command."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
)
from server.services.controlled_submission_clearance_context import (
    ControlledSubmissionClearanceContext,
)
from server.services.controlled_submission_clearance_values import (
    aware_utc as _aware_utc,
)
from server.services.controlled_submission_clearance_values import (
    clearance_response as _clearance_response,
)


class ControlledSubmissionClearanceCommandMixin(ControlledSubmissionClearanceContext):
    def record(
        self,
        *,
        submit_intent_id: str,
        reconciliation_run_id: str,
        clearance_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        existing = (
            self._db.get_controlled_submission_reconciliation_clearance_for_intent_sync(
                submit_intent_id
            )
        )
        if existing is not None:
            if (
                str(existing.get("clearance_fingerprint") or "")
                == clearance_fingerprint
                and str(existing.get("review_reconciliation_run_id") or "")
                == reconciliation_run_id
            ):
                return _clearance_response(existing, reused=True)
            raise self._clearance_rejection(
                "controlled submission clearance retry conflicts with persisted record",
                evidence={
                    "status": "rejected",
                    "submit_intent_id": submit_intent_id,
                    "blockers": ["controlled_submission_clearance_retry_conflict"],
                    "production_ledger_mutated": False,
                },
            )
        preview = self.preview(
            submit_intent_id=submit_intent_id,
            reconciliation_run_id=reconciliation_run_id,
        )
        if preview.get("status") == "cleared":
            if (
                preview.get("clearance_fingerprint") == clearance_fingerprint
                and preview.get("review_reconciliation_run_id") == reconciliation_run_id
            ):
                return {**preview, "reused": True}
            raise self._clearance_rejection(
                "controlled submission clearance retry conflicts with persisted record",
                evidence={
                    "status": "rejected",
                    "submit_intent_id": submit_intent_id,
                    "blockers": ["controlled_submission_clearance_retry_conflict"],
                    "production_ledger_mutated": False,
                },
            )
        rejection_reasons: list[str] = []
        if clearance_fingerprint != preview["clearance_fingerprint"]:
            rejection_reasons.append(
                "controlled_submission_clearance_fingerprint_mismatch"
            )
        if acknowledgement != CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_submission_clearance_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_submission_clearance_review_blocked")
        approval, approval_blockers = self._resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="clear_controlled_submission_reconciliation",
            expected_artifact_type="controlled_submission_reconciliation_clearance",
            expected_artifact_fingerprint=preview["clearance_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append(
                "controlled_submission_clearance_operator_approval_blocked"
            )
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append(
                "controlled_submission_clearance_operator_mismatch"
            )
        if rejection_reasons:
            concurrent_clearance = self._db.get_controlled_submission_reconciliation_clearance_for_intent_sync(
                submit_intent_id
            )
            if concurrent_clearance is not None and (
                str(concurrent_clearance.get("clearance_fingerprint") or "")
                == clearance_fingerprint
                and str(concurrent_clearance.get("review_reconciliation_run_id") or "")
                == reconciliation_run_id
            ):
                return _clearance_response(concurrent_clearance, reused=True)
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=clearance_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise self._clearance_rejection(
                "controlled submission reconciliation clearance rejected",
                evidence=evidence,
            )

        now = _aware_utc(self._clock())
        payload = {
            key: preview[key]
            for key in (
                "schema_version",
                "clearance_id",
                "clearance_fingerprint",
                "submit_intent_id",
                "submit_fingerprint",
                "order_id",
                "order_fingerprint",
                "broker_order_id",
                "client_order_id",
                "review_reconciliation_run_id",
                "review_reconciliation_item_id",
                "review_reconciliation_item_fingerprint",
                "broker_evidence_fingerprint",
                "broker_event_ids",
                "broker_row_fingerprints",
                "account_truth_import_run_id",
                "account_truth_file_fingerprint",
                "account_truth_source_fingerprint",
                "account_truth_resolution_status",
                "expected_ledger_delta_fingerprint",
                "clearance_reconciliation_run_id",
                "terminal_status",
                "terminal_evidence_source",
                "cancelled_quantity",
                "lifecycle_observation_id",
                "lifecycle_evidence_fingerprint",
                "lifecycle_source_sequence",
                "lifecycle_fill_fingerprint",
                "operator_id",
                "fill_count",
                "fill_quantity",
            )
        }
        payload.update(
            {
                "operator_approval_id": operator_approval_id,
                "status": "cleared",
                "manual_final_signature_verified": True,
                "interlock_released": True,
                "oms_terminal_status": preview["terminal_status"],
                "production_ledger_mutated": False,
                "automatic_submission_enabled": False,
                "strategy_direct_submission_enabled": False,
            }
        )
        transaction = (
            self._db.record_controlled_submission_reconciliation_clearance_sync(
                clearance={
                    **payload,
                    "fills": preview["fills"],
                    "cleared_at_epoch_ms": int(now.timestamp() * 1000),
                    "cleared_at": now.isoformat(),
                    "clearance_run_date": now.date().isoformat(),
                    "payload": payload,
                }
            )
        )
        if transaction.get("status") != "cleared":
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=clearance_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=[
                    "controlled_submission_clearance_transaction_rejected"
                ],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise self._clearance_rejection(
                "controlled submission reconciliation clearance transaction rejected",
                evidence=evidence,
            )
        return _clearance_response(
            transaction.get("clearance") or {},
            reused=bool(transaction.get("reused")),
        )
