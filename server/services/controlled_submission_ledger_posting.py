"""Human-signed, exactly-once ledger posting for a cleared controlled order."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_evidence import BrokerEvidenceRepository
from server.account_truth_gate import broker_events_for_import_run
from server.services.operator_approval import resolve_operator_approval_with_proof
from server.services.valuation_snapshot import build_current_valuation_snapshot

CONTROLLED_SUBMISSION_LEDGER_POSTING_SCHEMA_VERSION = (
    "karkinos.controlled_submission_ledger_posting.v1"
)
CONTROLLED_SUBMISSION_LEDGER_POSTING_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_submission_ledger_posting_status.v1"
)
CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT = (
    "apply_exact_reconciled_ledger_posting_once"
)
CONTROLLED_SUBMISSION_LEDGER_POSTING_MAX_ACCOUNT_TRUTH_AGE_SECONDS = 120
CONTROLLED_SUBMISSION_LEDGER_POSTING_REJECTION_EVENT_TYPE = (
    "controlled_broker.ledger_posting_rejected"
)
CONTROLLED_SUBMISSION_LEDGER_POSTING_EVENT_SOURCE = (
    "controlled_submission_ledger_posting"
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_MONEY_TOLERANCE = Decimal("0.005")


class ControlledSubmissionLedgerPostingRejected(ValueError):
    """Raised after a rejected ledger-posting attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSubmissionLedgerPostingService:
    """Preview and atomically apply one reviewed controlled-order posting."""

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
        configured = callable(self._account_truth_provider) and bool(
            self._trusted_operator_identities
        )
        return {
            "schema_version": (
                CONTROLLED_SUBMISSION_LEDGER_POSTING_STATUS_SCHEMA_VERSION
            ),
            "contract_status": (
                "signed_exactly_once_posting_available"
                if configured
                else "disabled_waiting_for_account_truth_and_operator_signature"
            ),
            "preview_enabled": True,
            "apply_enabled": configured,
            "zero_fill_cancel_noop_posting_enabled": True,
            "partial_cancel_actual_fills_only": True,
            "correction_mode": "compensating_events_only",
            "deletion_enabled": False,
            "automatic_posting_enabled": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "acknowledgement": (CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT),
            "safety": _safety_flags(),
        }

    def preview(self, *, clearance_id: str) -> dict[str, Any]:
        normalized_clearance_id = str(clearance_id or "").strip().lower()
        existing = (
            self._db.get_controlled_submission_ledger_posting_for_clearance_sync(
                normalized_clearance_id
            )
            if _FINGERPRINT_PATTERN.fullmatch(normalized_clearance_id)
            else None
        )
        if existing is not None:
            return {
                **_posting_response(existing, reused=True),
                "review_status": "already_applied",
                "review_ready": False,
                "blockers": [],
            }

        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_clearance_id):
            blockers.append("controlled_ledger_posting_clearance_id_invalid")
        clearance = (
            self._db.get_controlled_submission_reconciliation_clearance_sync(
                normalized_clearance_id
            )
            if not blockers
            else None
        )
        if clearance is None:
            blockers.append("controlled_ledger_posting_clearance_not_found")
            clearance = {}
        clearance_payload = _json_object(clearance.get("payload_json"))
        if str(clearance.get("status") or "") != "cleared":
            blockers.append("controlled_ledger_posting_clearance_not_cleared")

        submit_intent_id = str(clearance.get("submit_intent_id") or "")
        order_id = str(clearance.get("order_id") or "")
        intent = (
            self._db.get_controlled_broker_submit_intent_sync(submit_intent_id)
            if submit_intent_id
            else None
        )
        order = self._db.get_oms_order_sync(order_id) if order_id else None
        if intent is None:
            blockers.append("controlled_ledger_posting_intent_not_found")
            intent = {}
        if order is None:
            blockers.append("controlled_ledger_posting_order_not_found")
            order = {}

        terminal_status = str(
            clearance.get("terminal_status")
            or clearance_payload.get("terminal_status")
            or ""
        )
        if terminal_status not in {"filled", "cancelled"}:
            blockers.append("controlled_ledger_posting_terminal_status_invalid")
        if order and str(order.get("status") or "") != terminal_status:
            blockers.append("controlled_ledger_posting_oms_terminal_status_changed")
        if intent and str(intent.get("status") or "") != "submitted":
            blockers.append("controlled_ledger_posting_intent_status_changed")
        if str(intent.get("order_id") or "") != order_id:
            blockers.append("controlled_ledger_posting_intent_order_mismatch")
        if str(intent.get("broker_order_id") or "") != str(
            clearance.get("broker_order_id") or ""
        ):
            blockers.append("controlled_ledger_posting_broker_order_mismatch")

        latest_item = (
            self._db.get_latest_execution_reconciliation_item_for_order_sync(order_id)
            if order_id
            else None
        )
        if latest_item is None:
            blockers.append("controlled_ledger_posting_reconciliation_missing")
            latest_item = {}
        else:
            if str(latest_item.get("run_id") or "") != str(
                clearance.get("clearance_reconciliation_run_id") or ""
            ):
                blockers.append("controlled_ledger_posting_reconciliation_superseded")
            if str(latest_item.get("item_status") or "") != (
                "controlled_submission_reconciliation_cleared"
            ):
                blockers.append("controlled_ledger_posting_reconciliation_not_clear")

        account_truth = self._resolve_account_truth(
            clearance=clearance,
            clearance_payload=clearance_payload,
        )
        blockers.extend(account_truth["blockers"])
        account_truth_review = self._db.get_account_truth_review_identity_sync(
            account_truth["import_run_id"]
        )
        ledger_entries, fill_blockers = self._resolve_ledger_entries(
            clearance=clearance,
            clearance_payload=clearance_payload,
            intent=intent,
            order=order,
        )
        blockers.extend(fill_blockers)

        pre_valuation = build_current_valuation_snapshot(self._db, persist=False)
        posting_core = {
            "schema_version": CONTROLLED_SUBMISSION_LEDGER_POSTING_SCHEMA_VERSION,
            "action": "post_controlled_submission_ledger",
            "clearance_id": normalized_clearance_id,
            "clearance_fingerprint": str(clearance.get("clearance_fingerprint") or ""),
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": str(clearance.get("submit_fingerprint") or ""),
            "order_id": order_id,
            "broker_order_id": str(clearance.get("broker_order_id") or ""),
            "client_order_id": str(intent.get("client_order_id") or ""),
            "terminal_status": terminal_status,
            "clearance_reconciliation_run_id": str(
                clearance.get("clearance_reconciliation_run_id") or ""
            ),
            "broker_evidence_fingerprint": str(
                clearance.get("broker_evidence_fingerprint") or ""
            ),
            "account_truth_import_run_id": account_truth["import_run_id"],
            "account_truth_file_fingerprint": account_truth["file_fingerprint"],
            "account_truth_source_fingerprint": account_truth["source_fingerprint"],
            "account_truth_review_fingerprint": account_truth_review["fingerprint"],
            "account_truth_resolution_status": str(
                clearance_payload.get("account_truth_resolution_status") or "clear"
            ),
            "expected_ledger_delta_fingerprint": str(
                clearance_payload.get("expected_ledger_delta_fingerprint") or ""
            ),
            "lifecycle_observation_id": str(
                clearance.get("lifecycle_observation_id") or ""
            ),
            "lifecycle_evidence_fingerprint": str(
                clearance.get("lifecycle_evidence_fingerprint") or ""
            ),
            "lifecycle_source_sequence": int(
                clearance.get("lifecycle_source_sequence") or 0
            ),
            "pre_valuation_snapshot_id": str(pre_valuation.get("snapshot_id") or ""),
            "pre_valuation_as_of": str(pre_valuation.get("as_of") or ""),
            "pre_valuation_status": str(pre_valuation.get("status") or ""),
            "pre_ledger_cutoff_id": int(pre_valuation.get("ledger_cutoff_id") or 0),
            "pre_ledger_fingerprint": str(
                pre_valuation.get("ledger_fingerprint") or ""
            ),
            "operator_id": str(clearance.get("operator_id") or ""),
            "ledger_entry_count": len(ledger_entries),
            "ledger_entry_fingerprint": _fingerprint(ledger_entries),
            "ledger_entries": ledger_entries,
        }
        posting_fingerprint = _fingerprint(posting_core)
        posting_id = _fingerprint(
            {
                "domain": "karkinos.controlled_submission.ledger_posting_id.v1",
                "posting_fingerprint": posting_fingerprint,
            }
        )
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **posting_core,
            "posting_id": posting_id,
            "posting_fingerprint": posting_fingerprint,
            "generated_at": _aware_utc(self._clock()).isoformat(),
            "review_status": (
                "ready_for_final_signature" if not unique_blockers else "blocked"
            ),
            "review_ready": not unique_blockers,
            "blockers": unique_blockers,
            "account_truth": account_truth,
            "account_truth_review": account_truth_review,
            "required_operator_approval": {
                "action": "post_controlled_submission_ledger",
                "artifact_type": "controlled_submission_ledger_posting",
                "artifact_fingerprint": posting_fingerprint,
            },
            "production_ledger_mutated": False,
            "safety": _safety_flags(),
        }

    def apply(
        self,
        *,
        clearance_id: str,
        posting_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        existing = self._db.get_controlled_submission_ledger_posting_for_clearance_sync(
            clearance_id
        )
        if existing is not None:
            if str(existing.get("posting_fingerprint") or "") == posting_fingerprint:
                return self._post_apply_response(existing, reused=True)
            raise ControlledSubmissionLedgerPostingRejected(
                "ledger posting retry conflicts with persisted posting",
                evidence={
                    "status": "rejected",
                    "clearance_id": clearance_id,
                    "blockers": ["controlled_ledger_posting_retry_conflict"],
                    "production_ledger_mutated": False,
                },
            )

        preview = self.preview(clearance_id=clearance_id)
        if preview.get("review_status") == "already_applied":
            concurrent = (
                self._db.get_controlled_submission_ledger_posting_for_clearance_sync(
                    clearance_id
                )
            )
            if concurrent is not None and str(
                concurrent.get("posting_fingerprint") or ""
            ) == str(posting_fingerprint or ""):
                return self._post_apply_response(concurrent, reused=True)
        rejection_reasons: list[str] = []
        if posting_fingerprint != preview["posting_fingerprint"]:
            rejection_reasons.append("controlled_ledger_posting_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_SUBMISSION_LEDGER_POSTING_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_ledger_posting_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_ledger_posting_review_blocked")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="post_controlled_submission_ledger",
            expected_artifact_type="controlled_submission_ledger_posting",
            expected_artifact_fingerprint=preview["posting_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("controlled_ledger_posting_operator_blocked")
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append("controlled_ledger_posting_operator_mismatch")
        if rejection_reasons:
            concurrent = (
                self._db.get_controlled_submission_ledger_posting_for_clearance_sync(
                    clearance_id
                )
            )
            if concurrent is not None and str(
                concurrent.get("posting_fingerprint") or ""
            ) == str(posting_fingerprint or ""):
                return self._post_apply_response(concurrent, reused=True)
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=posting_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise ControlledSubmissionLedgerPostingRejected(
                "controlled submission ledger posting rejected",
                evidence=evidence,
            )

        now = _aware_utc(self._clock())
        payload = {
            key: preview[key]
            for key in (
                "schema_version",
                "posting_id",
                "posting_fingerprint",
                "clearance_id",
                "clearance_fingerprint",
                "submit_intent_id",
                "submit_fingerprint",
                "order_id",
                "broker_order_id",
                "client_order_id",
                "terminal_status",
                "clearance_reconciliation_run_id",
                "broker_evidence_fingerprint",
                "account_truth_import_run_id",
                "account_truth_file_fingerprint",
                "account_truth_source_fingerprint",
                "account_truth_review_fingerprint",
                "account_truth_resolution_status",
                "expected_ledger_delta_fingerprint",
                "lifecycle_observation_id",
                "lifecycle_evidence_fingerprint",
                "lifecycle_source_sequence",
                "pre_valuation_snapshot_id",
                "pre_valuation_as_of",
                "pre_valuation_status",
                "pre_ledger_cutoff_id",
                "pre_ledger_fingerprint",
                "operator_id",
                "ledger_entry_count",
                "ledger_entry_fingerprint",
            )
        }
        payload.update(
            {
                "operator_approval_id": operator_approval_id,
                "status": "applied",
                "manual_final_signature_verified": True,
                "ledger_entries": preview["ledger_entries"],
                "automatic_posting_enabled": False,
                "broker_submission_enabled": False,
                "broker_cancel_enabled": False,
                "capital_authority_changed": False,
            }
        )
        transaction = self._db.record_controlled_submission_ledger_posting_sync(
            posting={
                **payload,
                "applied_at_epoch_ms": int(now.timestamp() * 1000),
                "applied_at": now.isoformat(),
                "payload": payload,
            }
        )
        if transaction.get("status") != "applied":
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=posting_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["controlled_ledger_posting_transaction_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise ControlledSubmissionLedgerPostingRejected(
                "controlled submission ledger posting transaction rejected",
                evidence=evidence,
            )
        return self._post_apply_response(
            transaction.get("posting") or {},
            reused=bool(transaction.get("reused")),
        )

    def get_posting(self, posting_id: str) -> dict[str, Any]:
        row = self._db.get_controlled_submission_ledger_posting_sync(posting_id)
        return (
            _posting_response(row, reused=False)
            if row is not None
            else {"status": "not_found", "posting_id": posting_id}
        )

    def list_postings(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            _posting_response(row, reused=False)
            for row in self._db.list_controlled_submission_ledger_postings_sync(
                limit=limit
            )
        ]

    def _resolve_account_truth(
        self,
        *,
        clearance: dict[str, Any],
        clearance_payload: dict[str, Any],
    ) -> dict[str, Any]:
        blockers: list[str] = []
        raw: dict[str, Any] = {}
        if not callable(self._account_truth_provider):
            blockers.append("controlled_ledger_posting_account_truth_unavailable")
        else:
            try:
                value = self._account_truth_provider() or {}
            except Exception:
                value = {}
                blockers.append("controlled_ledger_posting_account_truth_failed")
            raw = value if isinstance(value, dict) else {}
        expected = {
            "import_run_id": str(clearance.get("account_truth_import_run_id") or ""),
            "file_fingerprint": str(
                clearance.get("account_truth_file_fingerprint") or ""
            ),
            "source_fingerprint": str(
                clearance.get("account_truth_source_fingerprint") or ""
            ),
        }
        for field, expected_value in expected.items():
            if str(raw.get(field) or "") != expected_value:
                blockers.append(
                    f"controlled_ledger_posting_account_truth_{field}_changed"
                )
        if str(raw.get("data_freshness_status") or "") != "fresh":
            blockers.append("controlled_ledger_posting_account_truth_not_fresh")
        if _mapping(raw.get("ledger_coverage")).get("status") != "covered":
            blockers.append(
                "controlled_ledger_posting_account_truth_ledger_not_covered"
            )
        if raw.get("does_not_mutate_production_ledger") is not True:
            blockers.append("controlled_ledger_posting_account_truth_boundary_invalid")
        captured_at = _parse_timestamp(raw.get("captured_at"))
        age_seconds: int | None = None
        if captured_at is None:
            blockers.append("controlled_ledger_posting_account_truth_time_invalid")
        else:
            age = (_aware_utc(self._clock()) - captured_at).total_seconds()
            age_seconds = int(max(0, age))
            if age < -30 or age > (
                CONTROLLED_SUBMISSION_LEDGER_POSTING_MAX_ACCOUNT_TRUTH_AGE_SECONDS
            ):
                blockers.append(
                    "controlled_ledger_posting_account_truth_time_not_fresh"
                )
        resolution_status = str(
            clearance_payload.get("account_truth_resolution_status") or "clear"
        )
        expected_delta_fingerprint = str(
            clearance_payload.get("expected_ledger_delta_fingerprint") or ""
        )
        if resolution_status not in {"clear", "expected_controlled_ledger_delta"}:
            blockers.append("controlled_ledger_posting_clearance_account_truth_invalid")
        if (
            resolution_status == "expected_controlled_ledger_delta"
            and not _FINGERPRINT_PATTERN.fullmatch(expected_delta_fingerprint)
        ):
            blockers.append("controlled_ledger_posting_expected_delta_missing")
        return {
            "status": "current" if not blockers else "blocked",
            **expected,
            "captured_at": str(raw.get("captured_at") or ""),
            "age_seconds": age_seconds,
            "resolution_status": resolution_status,
            "expected_ledger_delta_fingerprint": expected_delta_fingerprint,
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _resolve_ledger_entries(
        self,
        *,
        clearance: dict[str, Any],
        clearance_payload: dict[str, Any],
        intent: dict[str, Any],
        order: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        blockers: list[str] = []
        order_id = str(clearance.get("order_id") or "")
        clearance_id = str(clearance.get("clearance_id") or "")
        all_fills = self._db.list_fills_sync(order_id=order_id, limit=500, offset=0)
        selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for fill in all_fills:
            metadata = _json_object(fill.get("metadata_json"))
            if metadata.get("clearance_id") == clearance_id:
                selected.append((fill, metadata))
        expected_count = int(clearance.get("fill_count") or 0)
        if len(selected) != expected_count:
            blockers.append("controlled_ledger_posting_fill_count_changed")
        selected_quantity = sum(
            (abs(_decimal(fill.get("fill_quantity"))) for fill, _ in selected),
            Decimal("0"),
        )
        if selected_quantity != abs(_decimal(clearance.get("fill_quantity"))):
            blockers.append("controlled_ledger_posting_fill_quantity_changed")
        controlled_fills = [
            fill
            for fill in all_fills
            if str(fill.get("execution_mode") or "") == "controlled_live"
        ]
        if len(controlled_fills) != len(selected):
            blockers.append("controlled_ledger_posting_unbound_controlled_fill_exists")

        db_path = getattr(self._db, "_path", None)
        repository = BrokerEvidenceRepository(Path(db_path)) if db_path else None
        import_run_id = str(clearance.get("account_truth_import_run_id") or "")
        import_run = (
            repository.get_import_run(import_run_id)
            if repository is not None and import_run_id
            else None
        )
        if import_run is None:
            blockers.append("controlled_ledger_posting_import_not_found")
            events: list[Any] = []
        else:
            if import_run.validation_status != "pass":
                blockers.append("controlled_ledger_posting_import_not_pass")
            if import_run.file_fingerprint != str(
                clearance.get("account_truth_file_fingerprint") or ""
            ):
                blockers.append("controlled_ledger_posting_import_fingerprint_changed")
            events = broker_events_for_import_run(repository, import_run)
        event_by_key = {
            (str(event.event_id), str(event.row_fingerprint)): event for event in events
        }

        ledger_entries: list[dict[str, Any]] = []
        for fill, metadata in sorted(
            selected,
            key=lambda item: (
                str(item[0].get("timestamp") or ""),
                item[0].get("id") or 0,
            ),
        ):
            event_key = (
                str(metadata.get("broker_event_id") or ""),
                str(metadata.get("broker_row_fingerprint") or ""),
            )
            event = event_by_key.get(event_key)
            if event is None:
                blockers.append("controlled_ledger_posting_broker_event_changed")
                continue
            descriptor, descriptor_blockers = _ledger_entry_descriptor(
                fill=fill,
                metadata=metadata,
                event=event,
                intent=intent,
                order=order,
                import_run_id=import_run_id,
            )
            blockers.extend(descriptor_blockers)
            ledger_entries.append(descriptor)

        existing_rows = self._db.get_ledger_entries_sync(limit=5000, offset=0)
        existing_sources = {
            (str(row.get("source") or ""), str(row.get("source_ref") or ""))
            for row in existing_rows
        }
        existing_settlements = {
            (
                str(row.get("settlement_source") or ""),
                str(row.get("settlement_source_ref") or ""),
            )
            for row in existing_rows
        }
        for entry in ledger_entries:
            if (entry["source"], entry["source_ref"]) in existing_sources:
                blockers.append("controlled_ledger_posting_fill_already_in_ledger")
            if (
                entry["settlement_source"],
                entry["settlement_source_ref"],
            ) in existing_settlements:
                blockers.append("controlled_ledger_posting_evidence_already_in_ledger")
        return ledger_entries, list(dict.fromkeys(blockers))

    def _post_apply_response(
        self,
        row: dict[str, Any],
        *,
        reused: bool,
    ) -> dict[str, Any]:
        response = _posting_response(row, reused=reused)
        try:
            post_valuation = self._db.publish_current_valuation_snapshot_sync()
            valuation_status = "published"
        except Exception:
            post_valuation = {}
            valuation_status = "publication_failed"
        raw_account_truth: dict[str, Any] = {}
        if callable(self._account_truth_provider):
            try:
                value = self._account_truth_provider() or {}
                raw_account_truth = value if isinstance(value, dict) else {}
            except Exception:
                raw_account_truth = {}
        reconciled = (
            raw_account_truth.get("status") == "clear"
            and raw_account_truth.get("gate_status") == "pass"
            and raw_account_truth.get("reconciliation_status") in {"clear", "pass"}
            and int(raw_account_truth.get("unresolved_mismatch_count") or 0) == 0
            and _mapping(raw_account_truth.get("ledger_coverage")).get("status")
            == "covered"
        )
        return {
            **response,
            "post_apply_status": (
                "reconciled" if reconciled else "post_apply_review_required"
            ),
            "post_valuation_publication_status": valuation_status,
            "post_valuation_snapshot_id": str(post_valuation.get("snapshot_id") or ""),
            "post_ledger_cutoff_id": int(
                post_valuation.get("ledger_cutoff_id")
                or response.get("post_ledger_cutoff_id")
                or 0
            ),
            "post_account_truth": {
                key: raw_account_truth.get(key)
                for key in (
                    "status",
                    "source_fingerprint",
                    "import_run_id",
                    "data_freshness_status",
                    "ledger_coverage",
                    "reconciliation_status",
                    "gate_status",
                    "unresolved_mismatch_count",
                    "blockers",
                )
            },
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
            "schema_version": CONTROLLED_SUBMISSION_LEDGER_POSTING_SCHEMA_VERSION,
            "status": "rejected",
            "posting_id": str(preview.get("posting_id") or ""),
            "clearance_id": str(preview.get("clearance_id") or ""),
            "order_id": str(preview.get("order_id") or ""),
            "expected_fingerprint": str(preview.get("posting_fingerprint") or ""),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "production_ledger_mutated": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "capital_authority_changed": False,
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SUBMISSION_LEDGER_POSTING_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type="controlled_submission_ledger_posting_rejection",
            entity_id=attempt_id,
            source=CONTROLLED_SUBMISSION_LEDGER_POSTING_EVENT_SOURCE,
            source_ref=payload["clearance_id"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {"event_id": event_id, "attempt_id": attempt_id, **payload}


def _ledger_entry_descriptor(
    *,
    fill: dict[str, Any],
    metadata: dict[str, Any],
    event: Any,
    intent: dict[str, Any],
    order: dict[str, Any],
    import_run_id: str,
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    side = str(order.get("side") or "").lower()
    quantity = abs(_decimal(getattr(event, "quantity", "0")))
    price = abs(_decimal(getattr(event, "price", "0")))
    gross = abs(_decimal(getattr(event, "gross_amount", "0")))
    fee = abs(_decimal(getattr(event, "fee", "0")))
    tax = abs(_decimal(getattr(event, "tax", "0")))
    transfer_fee = abs(_decimal(getattr(event, "transfer_fee", "0")))
    net_amount = _decimal(getattr(event, "net_amount", "0"))
    total_fee = fee + tax + transfer_fee
    expected_net = -(gross + total_fee) if side == "buy" else gross - total_fee
    if side not in {"buy", "sell"}:
        blockers.append("controlled_ledger_posting_side_invalid")
    if quantity <= 0 or price <= 0 or gross <= 0:
        blockers.append("controlled_ledger_posting_trade_values_invalid")
    if abs(gross - quantity * price) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_gross_amount_mismatch")
    if abs(net_amount - expected_net) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_net_amount_mismatch")
    comparisons = {
        "symbol": (
            str(fill.get("symbol") or ""),
            str(getattr(event, "symbol", "") or ""),
        ),
        "asset_class": (
            str(fill.get("asset_class") or ""),
            str(getattr(event, "asset_class", "") or ""),
        ),
        "broker_order_id": (
            str(intent.get("broker_order_id") or ""),
            str(getattr(event, "broker_order_id", "") or ""),
        ),
        "client_order_id": (
            str(intent.get("client_order_id") or ""),
            str(getattr(event, "client_order_id", "") or ""),
        ),
    }
    for field, (expected, actual) in comparisons.items():
        if expected != actual:
            blockers.append(f"controlled_ledger_posting_{field}_mismatch")
    if abs(_decimal(fill.get("fill_quantity")) - quantity) > Decimal("0.00000001"):
        blockers.append("controlled_ledger_posting_fill_quantity_mismatch")
    if abs(_decimal(fill.get("fill_price")) - price) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_fill_price_mismatch")
    if abs(_decimal(fill.get("commission")) - fee) > _MONEY_TOLERANCE:
        blockers.append("controlled_ledger_posting_fill_fee_mismatch")
    event_id = str(getattr(event, "event_id", "") or "")
    row_fingerprint = str(getattr(event, "row_fingerprint", "") or "")
    if str(metadata.get("broker_event_id") or "") != event_id:
        blockers.append("controlled_ledger_posting_fill_event_mismatch")
    if str(metadata.get("broker_row_fingerprint") or "") != row_fingerprint:
        blockers.append("controlled_ledger_posting_fill_row_mismatch")
    fee_breakdown = {
        "commission": _decimal_string(fee),
        "stamp_tax": _decimal_string(tax),
        "transfer_fee": _decimal_string(transfer_fee),
        "other_fees": "0",
        "total_fee": _decimal_string(total_fee),
        "confirmation_source": "broker_statement",
    }
    descriptor = {
        "fill_id": str(fill.get("fill_id") or ""),
        "broker_event_id": event_id,
        "broker_row_fingerprint": row_fingerprint,
        "entry_type": f"trade_{side}",
        "timestamp": str(getattr(event, "occurred_at", "") or ""),
        "settled_at": str(
            getattr(event, "settled_at", "") or getattr(event, "occurred_at", "") or ""
        ),
        "symbol": str(getattr(event, "symbol", "") or ""),
        "direction": side,
        "quantity": _decimal_string(quantity),
        "price": _decimal_string(price),
        "amount": _decimal_string(gross),
        "commission": _decimal_string(fee),
        "gross_amount": _decimal_string(gross),
        "net_cash_impact": _decimal_string(net_amount),
        "fee_breakdown": fee_breakdown,
        "fee_rule_id": "broker_statement_exact",
        "fee_rule_version": "broker_statement_exact.v1",
        "cost_basis_method": "broker_remaining_cost",
        "asset_class": str(getattr(event, "asset_class", "") or "stock"),
        "note": "Controlled submission reconciled ledger posting.",
        "source": "controlled_submission_ledger_posting",
        "source_ref": str(fill.get("fill_id") or ""),
        "settlement_status": "confirmed",
        "settlement_source": "broker_statement",
        "settlement_source_ref": f"{import_run_id}:{event_id}",
        "settlement_note": "Exact broker evidence bound by signed clearance.",
        "account_truth_import_run_id": import_run_id,
    }
    return descriptor, blockers


def _posting_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    try:
        ledger_entry_ids = json.loads(row.get("ledger_entry_ids_json") or "[]")
    except (TypeError, ValueError):
        ledger_entry_ids = []
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "posting_id": str(row.get("posting_id") or ""),
        "posting_fingerprint": str(row.get("posting_fingerprint") or ""),
        "clearance_id": str(row.get("clearance_id") or ""),
        "submit_intent_id": str(row.get("submit_intent_id") or ""),
        "order_id": str(row.get("order_id") or ""),
        "status": str(row.get("status") or "applied"),
        "ledger_entry_count": int(row.get("ledger_entry_count") or 0),
        "ledger_entry_ids": (
            ledger_entry_ids if isinstance(ledger_entry_ids, list) else []
        ),
        "pre_ledger_cutoff_id": int(row.get("pre_ledger_cutoff_id") or 0),
        "post_ledger_cutoff_id": int(row.get("post_ledger_cutoff_id") or 0),
        "applied_at": str(row.get("applied_at") or ""),
        "persisted": bool(row),
        "reused": reused,
        "production_ledger_mutated": int(row.get("ledger_entry_count") or 0) > 0,
        "automatic_posting_enabled": False,
        "broker_submission_enabled": False,
        "broker_cancel_enabled": False,
        "capital_authority_changed": False,
        "safety": _safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "persisted_facts_only": True,
        "exact_terminal_clearance_required": True,
        "operator_signature_required": True,
        "pre_ledger_identity_rechecked_in_transaction": True,
        "all_ledger_entries_one_transaction": True,
        "exactly_once_posting": True,
        "partial_cancel_posts_actual_fills_only": True,
        "zero_fill_cancel_creates_no_trade_entry": True,
        "corrections_require_compensating_events": True,
        "ledger_history_deletion_disabled": True,
        "automatic_posting_disabled": True,
        "provider_contact_disabled": True,
        "broker_submit_disabled": True,
        "broker_cancel_disabled": True,
        "strategy_direct_broker_access_disabled": True,
        "ai_trade_authority_disabled": True,
        "capital_authority_change_disabled": True,
    }


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


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _parse_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip().replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
