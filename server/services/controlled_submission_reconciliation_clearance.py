"""Signed full-fill reconciliation clearance for one controlled submission."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_evidence import BrokerEvidenceRepository
from server.services.operator_approval import resolve_operator_approval_with_proof
from server.services.per_order_confirmation import build_order_fingerprint

CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION = (
    "karkinos.controlled_submission_reconciliation_clearance.v1"
)
CONTROLLED_SUBMISSION_CLEARANCE_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_submission_reconciliation_clearance_status.v1"
)
CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT = (
    "clear_exact_full_fill_without_automatic_ledger_mutation"
)
CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS = 120
CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_EVENT_TYPE = (
    "controlled_broker.reconciliation_clearance_rejected"
)
CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_ENTITY_TYPE = (
    "controlled_submission_reconciliation_clearance_rejection"
)
CONTROLLED_SUBMISSION_CLEARANCE_EVENT_SOURCE = (
    "controlled_submission_reconciliation_clearance"
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class ControlledSubmissionReconciliationClearanceRejected(ValueError):
    """Raised after a rejected signed clearance attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSubmissionReconciliationClearanceService:
    """Turn exact reviewed broker evidence into real fills without ledger writes."""

    def __init__(
        self,
        *,
        db: Any,
        account_truth_provider: Callable[[], dict[str, Any]] | None = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._account_truth_provider = account_truth_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": CONTROLLED_SUBMISSION_CLEARANCE_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "signed_full_fill_clearance_available"
                if callable(self._account_truth_provider)
                and self._trusted_operator_identities
                else "disabled_waiting_for_account_truth_and_operator_signature"
            ),
            "account_truth_provider_configured": callable(self._account_truth_provider),
            "trusted_operator_signature_configured": bool(
                self._trusted_operator_identities
            ),
            "maximum_account_truth_age_seconds": (
                CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS
            ),
            "partial_fill_clearance_enabled": False,
            "automatic_ledger_mutation_enabled": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "acknowledgement": CONTROLLED_SUBMISSION_CLEARANCE_ACKNOWLEDGEMENT,
            "safety": _safety_flags(),
        }

    def preview(
        self,
        *,
        submit_intent_id: str,
        reconciliation_run_id: str,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized_intent_id = str(submit_intent_id or "").strip().lower()
        normalized_run_id = str(reconciliation_run_id or "").strip()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_intent_id):
            blockers.append("controlled_submission_clearance_intent_id_invalid")
        if not _ID_PATTERN.fullmatch(normalized_run_id):
            blockers.append("controlled_submission_clearance_run_id_invalid")

        existing = (
            self._db.get_controlled_submission_reconciliation_clearance_for_intent_sync(
                normalized_intent_id
            )
            if _FINGERPRINT_PATTERN.fullmatch(normalized_intent_id)
            else None
        )
        if existing is not None:
            return {
                **_clearance_response(existing, reused=True),
                "review_status": "already_cleared",
                "review_ready": False,
                "blockers": [],
            }

        intent = (
            self._db.get_controlled_broker_submit_intent_sync(normalized_intent_id)
            if _FINGERPRINT_PATTERN.fullmatch(normalized_intent_id)
            else None
        )
        if intent is None:
            blockers.append("controlled_submission_clearance_intent_not_found")
            intent = {}
        elif str(intent.get("status") or "") != "submitted":
            blockers.append("controlled_submission_clearance_intent_not_submitted")
        order_id = str(intent.get("order_id") or "")
        order = self._db.get_oms_order_sync(order_id) if order_id else None
        if order is None:
            blockers.append("controlled_submission_clearance_order_not_found")
            order = {}
        elif str(order.get("status") or "") != "submitted":
            blockers.append("controlled_submission_clearance_oms_not_submitted")
        if order and str(intent.get("order_fingerprint") or "") != (
            build_order_fingerprint(order)
        ):
            blockers.append("controlled_submission_clearance_order_changed")
        broker_order_id = str(intent.get("broker_order_id") or "")
        if not _ID_PATTERN.fullmatch(broker_order_id):
            blockers.append("controlled_submission_clearance_broker_order_id_invalid")

        run = (
            self._db.get_execution_reconciliation_run_sync(normalized_run_id)
            if normalized_run_id
            else None
        )
        if run is None:
            blockers.append("controlled_submission_clearance_run_not_found")
        latest_item = (
            self._db.get_latest_execution_reconciliation_item_for_order_sync(order_id)
            if order_id
            else None
        )
        if latest_item is None:
            blockers.append("controlled_submission_clearance_item_not_found")
            latest_item = {}
        else:
            if str(latest_item.get("run_id") or "") != normalized_run_id:
                blockers.append("controlled_submission_clearance_item_not_latest_run")
            if str(latest_item.get("item_status") or "") != (
                "controlled_submission_broker_evidence_available"
            ):
                blockers.append("controlled_submission_clearance_item_not_clearable")
            if str(latest_item.get("suggested_action") or "") != (
                "review_controlled_submission_broker_evidence"
            ):
                blockers.append("controlled_submission_clearance_action_mismatch")

        item_payload = _json_object(latest_item.get("payload_json"))
        controlled_summary = _mapping(
            item_payload.get("controlled_submission_evidence_summary")
        )
        if str(controlled_summary.get("submit_intent_id") or "") != (
            normalized_intent_id
        ):
            blockers.append("controlled_submission_clearance_item_intent_mismatch")
        if str(controlled_summary.get("broker_order_id") or "") != broker_order_id:
            blockers.append(
                "controlled_submission_clearance_item_broker_order_mismatch"
            )
        if controlled_summary.get("new_submissions_blocked") is not True:
            blockers.append("controlled_submission_clearance_interlock_not_active")
        broker_evidence = [
            _mapping(item)
            for item in controlled_summary.get("broker_event_evidence") or []
            if isinstance(item, dict)
        ]
        broker_evidence_fingerprint = _fingerprint(broker_evidence)
        if not broker_evidence:
            blockers.append("controlled_submission_clearance_broker_evidence_missing")
        if str(controlled_summary.get("broker_evidence_fingerprint") or "") != (
            broker_evidence_fingerprint
        ):
            blockers.append(
                "controlled_submission_clearance_broker_fingerprint_invalid"
            )

        source = self._resolve_broker_source(broker_evidence)
        blockers.extend(source["blockers"])
        account_truth = self._resolve_account_truth(now=now)
        blockers.extend(account_truth["blockers"])
        if source["import_run_id"] != account_truth["import_run_id"]:
            blockers.append(
                "controlled_submission_clearance_account_truth_import_mismatch"
            )
        if source["file_fingerprint"] != account_truth["file_fingerprint"]:
            blockers.append(
                "controlled_submission_clearance_account_truth_file_mismatch"
            )

        order_quantity = abs(_decimal(order.get("quantity")) or Decimal("0"))
        broker_quantity = sum(
            (
                abs(_decimal(event.get("quantity")) or Decimal("0"))
                for event in broker_evidence
            ),
            Decimal("0"),
        )
        if order_quantity <= 0 or broker_quantity != order_quantity:
            blockers.append("controlled_submission_clearance_full_fill_required")
        expected_event_type = (
            "trade_buy"
            if str(order.get("side") or "").lower() == "buy"
            else "trade_sell"
        )
        for event in broker_evidence:
            if str(event.get("event_type") or "") != expected_event_type:
                blockers.append("controlled_submission_clearance_side_mismatch")
            if str(event.get("symbol") or "") != str(order.get("symbol") or ""):
                blockers.append("controlled_submission_clearance_symbol_mismatch")
            if str(event.get("asset_class") or "") != str(
                order.get("asset_class") or ""
            ):
                blockers.append("controlled_submission_clearance_asset_class_mismatch")

        reconciliation_item_fingerprint = _fingerprint(
            _reconciliation_item_contract(latest_item)
        )
        clearance_core = {
            "schema_version": CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
            "action": "clear_controlled_submission_reconciliation",
            "submit_intent_id": normalized_intent_id,
            "submit_fingerprint": str(intent.get("submit_fingerprint") or ""),
            "order_id": order_id,
            "order_fingerprint": str(intent.get("order_fingerprint") or ""),
            "broker_order_id": broker_order_id,
            "review_reconciliation_run_id": normalized_run_id,
            "review_reconciliation_item_id": int(latest_item.get("id") or 0),
            "review_reconciliation_item_fingerprint": (reconciliation_item_fingerprint),
            "broker_evidence_fingerprint": broker_evidence_fingerprint,
            "broker_event_ids": [
                str(item.get("event_id") or "") for item in broker_evidence
            ],
            "broker_row_fingerprints": [
                str(item.get("row_fingerprint") or "") for item in broker_evidence
            ],
            "account_truth_import_run_id": account_truth["import_run_id"],
            "account_truth_file_fingerprint": account_truth["file_fingerprint"],
            "account_truth_source_fingerprint": account_truth["source_fingerprint"],
            "account_truth_captured_at": account_truth["captured_at"],
            "operator_id": str(intent.get("operator_id") or ""),
            "fill_count": len(broker_evidence),
            "fill_quantity": _decimal_string(broker_quantity),
        }
        clearance_fingerprint = _fingerprint(clearance_core)
        clearance_id = _fingerprint(
            {
                "domain": "karkinos.controlled_submission.clearance_id.v1",
                "clearance_fingerprint": clearance_fingerprint,
            }
        )
        clearance_reconciliation_run_id = (
            f"execution-reconciliation-clearance:{clearance_id[:32]}"
        )
        fills = [
            _fill_descriptor(
                event,
                order=order,
                intent=intent,
                clearance_id=clearance_id,
                clearance_reconciliation_run_id=(clearance_reconciliation_run_id),
                review_reconciliation_run_id=normalized_run_id,
                account_truth=account_truth,
            )
            for event in broker_evidence
        ]
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **clearance_core,
            "clearance_id": clearance_id,
            "clearance_fingerprint": clearance_fingerprint,
            "clearance_reconciliation_run_id": clearance_reconciliation_run_id,
            "generated_at": now.isoformat(),
            "review_status": (
                "ready_for_final_signature" if not unique_blockers else "blocked"
            ),
            "review_ready": not unique_blockers,
            "blockers": unique_blockers,
            "broker_evidence": broker_evidence,
            "account_truth": account_truth,
            "fills": fills,
            "required_operator_approval": {
                "action": "clear_controlled_submission_reconciliation",
                "artifact_type": ("controlled_submission_reconciliation_clearance"),
                "artifact_fingerprint": clearance_fingerprint,
            },
            "interlock_released": False,
            "oms_mutated": False,
            "real_fills_recorded": False,
            "production_ledger_mutated": False,
            "safety": _safety_flags(),
        }

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
            raise ControlledSubmissionReconciliationClearanceRejected(
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
            raise ControlledSubmissionReconciliationClearanceRejected(
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
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="clear_controlled_submission_reconciliation",
            expected_artifact_type=("controlled_submission_reconciliation_clearance"),
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
            raise ControlledSubmissionReconciliationClearanceRejected(
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
                "review_reconciliation_run_id",
                "review_reconciliation_item_id",
                "review_reconciliation_item_fingerprint",
                "broker_evidence_fingerprint",
                "broker_event_ids",
                "broker_row_fingerprints",
                "account_truth_import_run_id",
                "account_truth_file_fingerprint",
                "account_truth_source_fingerprint",
                "clearance_reconciliation_run_id",
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
                "oms_terminal_status": "filled",
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
            raise ControlledSubmissionReconciliationClearanceRejected(
                "controlled submission reconciliation clearance transaction rejected",
                evidence=evidence,
            )
        return _clearance_response(
            transaction.get("clearance") or {},
            reused=bool(transaction.get("reused")),
        )

    def get_clearance(self, clearance_id: str) -> dict[str, Any]:
        row = self._db.get_controlled_submission_reconciliation_clearance_sync(
            clearance_id
        )
        return (
            _clearance_response(row, reused=False)
            if row is not None
            else {"status": "not_found", "clearance_id": clearance_id}
        )

    def list_clearances(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            _clearance_response(row, reused=False)
            for row in self._db.list_controlled_submission_reconciliation_clearances_sync(
                limit=limit
            )
        ]

    def _resolve_broker_source(
        self,
        broker_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        blockers: list[str] = []
        import_ids = sorted(
            {str(item.get("import_run_id") or "") for item in broker_evidence}
        )
        if len(import_ids) != 1 or not import_ids[0]:
            blockers.append("controlled_submission_clearance_single_import_required")
            import_run_id = ""
        else:
            import_run_id = import_ids[0]
        db_path = getattr(self._db, "_path", None)
        repository = BrokerEvidenceRepository(Path(db_path)) if db_path else None
        import_run = (
            repository.get_import_run(import_run_id)
            if repository is not None and import_run_id
            else None
        )
        if import_run is None:
            blockers.append("controlled_submission_clearance_import_not_found")
            file_fingerprint = ""
            source_type = ""
            current_events: list[Any] = []
        else:
            file_fingerprint = str(import_run.file_fingerprint or "")
            source_type = str(import_run.source_type or "")
            if import_run.validation_status != "pass":
                blockers.append("controlled_submission_clearance_import_not_pass")
            current_events = repository.list_events(import_run_id)
        current_by_key = {
            (str(event.event_id), str(event.row_fingerprint)): event
            for event in current_events
        }
        resolved: list[dict[str, Any]] = []
        for expected in broker_evidence:
            key = (
                str(expected.get("event_id") or ""),
                str(expected.get("row_fingerprint") or ""),
            )
            event = current_by_key.get(key)
            if event is None:
                blockers.append("controlled_submission_clearance_broker_event_changed")
                continue
            contract = _broker_event_contract(event)
            if contract != expected:
                blockers.append("controlled_submission_clearance_broker_event_changed")
            resolved.append(contract)
        if len(resolved) != len(broker_evidence):
            blockers.append(
                "controlled_submission_clearance_broker_event_count_changed"
            )
        if len({item.get("event_id") for item in broker_evidence}) != len(
            broker_evidence
        ):
            blockers.append("controlled_submission_clearance_duplicate_event")
        return {
            "status": "clear" if not blockers else "blocked",
            "import_run_id": import_run_id,
            "file_fingerprint": file_fingerprint,
            "source_type": source_type,
            "broker_evidence_fingerprint": _fingerprint(resolved),
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _resolve_account_truth(self, *, now: datetime) -> dict[str, Any]:
        blockers: list[str] = []
        raw: dict[str, Any] = {}
        if not callable(self._account_truth_provider):
            blockers.append("controlled_submission_clearance_account_truth_unavailable")
        else:
            try:
                value = self._account_truth_provider() or {}
            except Exception:
                value = {}
                blockers.append("controlled_submission_clearance_account_truth_failed")
            raw = value if isinstance(value, dict) else {}
        captured_at = _parse_timestamp(raw.get("captured_at"))
        age_seconds: int | None = None
        if captured_at is None:
            blockers.append(
                "controlled_submission_clearance_account_truth_time_invalid"
            )
        else:
            age = (now - captured_at).total_seconds()
            age_seconds = int(max(0, age))
            if age < -30:
                blockers.append("controlled_submission_clearance_account_truth_future")
            elif age > CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS:
                blockers.append("controlled_submission_clearance_account_truth_stale")
        ledger_coverage = _mapping(raw.get("ledger_coverage"))
        required = {
            "status": "clear",
            "gate_status": "pass",
            "data_freshness_status": "fresh",
            "unresolved_mismatch_count": 0,
        }
        for field, expected in required.items():
            if raw.get(field) != expected:
                blockers.append(
                    f"controlled_submission_clearance_account_truth_{field}_invalid"
                )
        if raw.get("reconciliation_status") not in {"clear", "pass"}:
            blockers.append(
                "controlled_submission_clearance_account_truth_reconciliation_status_invalid"
            )
        if ledger_coverage.get("status") != "covered":
            blockers.append(
                "controlled_submission_clearance_account_truth_ledger_not_covered"
            )
        source_fingerprint = str(raw.get("source_fingerprint") or "")
        file_fingerprint = str(raw.get("file_fingerprint") or "")
        if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
            blockers.append(
                "controlled_submission_clearance_account_truth_fingerprint_invalid"
            )
        if not _FINGERPRINT_PATTERN.fullmatch(file_fingerprint):
            blockers.append(
                "controlled_submission_clearance_account_truth_file_invalid"
            )
        if raw.get("does_not_mutate_production_ledger") is not True:
            blockers.append(
                "controlled_submission_clearance_account_truth_ledger_boundary_invalid"
            )
        return {
            "status": "clear" if not blockers else "blocked",
            "source_fingerprint": source_fingerprint,
            "import_run_id": str(raw.get("import_run_id") or ""),
            "file_fingerprint": file_fingerprint,
            "source_type": str(raw.get("source_type") or ""),
            "captured_at": str(raw.get("captured_at") or ""),
            "age_seconds": age_seconds,
            "ledger_coverage_status": str(ledger_coverage.get("status") or ""),
            "reconciliation_status": str(raw.get("reconciliation_status") or ""),
            "gate_status": str(raw.get("gate_status") or ""),
            "unresolved_mismatch_count": int(raw.get("unresolved_mismatch_count") or 0),
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
            "status": "rejected",
            "clearance_id": str(preview.get("clearance_id") or ""),
            "submit_intent_id": str(preview.get("submit_intent_id") or ""),
            "order_id": str(preview.get("order_id") or ""),
            "expected_fingerprint": str(preview.get("clearance_fingerprint") or ""),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "interlock_released": False,
            "oms_mutated": False,
            "real_fills_recorded": False,
            "production_ledger_mutated": False,
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_SUBMISSION_CLEARANCE_EVENT_SOURCE,
            source_ref=payload["submit_intent_id"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "persisted": True,
            **payload,
        }


def _fill_descriptor(
    event: dict[str, Any],
    *,
    order: dict[str, Any],
    intent: dict[str, Any],
    clearance_id: str,
    clearance_reconciliation_run_id: str,
    review_reconciliation_run_id: str,
    account_truth: dict[str, Any],
) -> dict[str, Any]:
    fill_id = _fingerprint(
        {
            "domain": "karkinos.controlled_submission.real_fill.v1",
            "submit_intent_id": intent.get("submit_intent_id"),
            "import_run_id": event.get("import_run_id"),
            "row_fingerprint": event.get("row_fingerprint"),
        }
    )
    return {
        "fill_id": fill_id,
        "broker_event_id": str(event.get("event_id") or ""),
        "broker_row_fingerprint": str(event.get("row_fingerprint") or ""),
        "account_truth_import_run_id": str(event.get("import_run_id") or ""),
        "timestamp": str(event.get("occurred_at") or ""),
        "symbol": str(event.get("symbol") or ""),
        "side": str(order.get("side") or ""),
        "asset_class": str(event.get("asset_class") or ""),
        "fill_price": str(event.get("price") or ""),
        "fill_quantity": str(abs(_decimal(event.get("quantity")) or Decimal("0"))),
        "fee": str(event.get("fee") or "0"),
        "tax": str(event.get("tax") or "0"),
        "transfer_fee": str(event.get("transfer_fee") or "0"),
        "provider_name": str(account_truth.get("source_type") or "broker_evidence"),
        "metadata": {
            "schema_version": CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
            "clearance_id": clearance_id,
            "submit_intent_id": str(intent.get("submit_intent_id") or ""),
            "account_truth_import_run_id": str(event.get("import_run_id") or ""),
            "account_truth_source_fingerprint": str(
                account_truth.get("source_fingerprint") or ""
            ),
            "execution_reconciliation_run_id": (clearance_reconciliation_run_id),
            "review_reconciliation_run_id": review_reconciliation_run_id,
            "broker_event_id": str(event.get("event_id") or ""),
            "broker_row_fingerprint": str(event.get("row_fingerprint") or ""),
            "fee": str(event.get("fee") or "0"),
            "tax": str(event.get("tax") or "0"),
            "transfer_fee": str(event.get("transfer_fee") or "0"),
            "production_ledger_mutated": False,
        },
    }


def _broker_event_contract(event: Any) -> dict[str, Any]:
    return {
        "import_run_id": str(getattr(event, "import_run_id", "") or ""),
        "row_fingerprint": str(getattr(event, "row_fingerprint", "") or ""),
        "event_id": str(getattr(event, "event_id", "") or ""),
        "event_type": str(getattr(event, "event_type", "") or ""),
        "occurred_at": str(getattr(event, "occurred_at", "") or ""),
        "symbol": str(getattr(event, "symbol", "") or ""),
        "asset_class": str(getattr(event, "asset_class", "") or ""),
        "currency": str(getattr(event, "currency", "") or ""),
        "quantity": str(getattr(event, "quantity", "") or ""),
        "price": str(getattr(event, "price", "") or ""),
        "gross_amount": str(getattr(event, "gross_amount", "") or ""),
        "fee": str(getattr(event, "fee", "") or ""),
        "tax": str(getattr(event, "tax", "") or ""),
        "transfer_fee": str(getattr(event, "transfer_fee", "") or ""),
        "net_amount": str(getattr(event, "net_amount", "") or ""),
    }


def _reconciliation_item_contract(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "run_id",
            "order_id",
            "item_status",
            "suggested_action",
            "gateway_event_count",
            "broker_event_count",
            "detail",
            "payload_json",
            "created_at",
        )
    }


def _clearance_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "clearance_id": str(row.get("clearance_id") or ""),
        "clearance_fingerprint": str(row.get("clearance_fingerprint") or ""),
        "submit_intent_id": str(row.get("submit_intent_id") or ""),
        "order_id": str(row.get("order_id") or ""),
        "status": str(row.get("status") or "cleared"),
        "fill_count": int(row.get("fill_count") or 0),
        "fill_quantity": str(row.get("fill_quantity") or "0"),
        "cleared_at": str(row.get("cleared_at") or ""),
        "persisted": bool(row),
        "reused": reused,
        "interlock_released": True,
        "oms_terminal_status": "filled",
        "real_fills_recorded": True,
        "production_ledger_mutated": False,
        "automatic_submission_enabled": False,
        "strategy_direct_submission_enabled": False,
        "safety": _safety_flags(),
    }


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _safety_flags() -> dict[str, bool]:
    return {
        "manual_final_signature_required": True,
        "exact_latest_reconciliation_required": True,
        "fresh_account_truth_required": True,
        "full_fill_only": True,
        "atomic_fill_oms_clearance": True,
        "automatic_ledger_mutation_disabled": True,
        "automatic_submission_disabled": True,
        "strategy_direct_submission_disabled": True,
        "broker_cancel_disabled": True,
        "automatic_capital_expansion_disabled": True,
    }
