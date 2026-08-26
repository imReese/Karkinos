"""Persisted broker, lifecycle, Account Truth, and audit evidence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_EVENT_SOURCE,
    CONTROLLED_SUBMISSION_CLEARANCE_MAX_ACCOUNT_TRUTH_AGE_SECONDS,
    CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_ENTITY_TYPE,
    CONTROLLED_SUBMISSION_CLEARANCE_REJECTION_EVENT_TYPE,
    CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
)
from server.services.controlled_submission_clearance_context import (
    ControlledSubmissionClearanceContext,
)
from server.services.controlled_submission_clearance_evidence_values import (
    broker_event_contract as _broker_event_contract,
)
from server.services.controlled_submission_clearance_evidence_values import (
    controlled_post_trade_account_truth_delta as _controlled_post_trade_account_truth_delta,
)
from server.services.controlled_submission_clearance_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_submission_clearance_values import (
    aware_utc as _aware_utc,
)
from server.services.controlled_submission_clearance_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_submission_clearance_values import (
    json_object as _json_object,
)
from server.services.controlled_submission_clearance_values import mapping as _mapping
from server.services.controlled_submission_clearance_values import (
    parse_timestamp as _parse_timestamp,
)


class ControlledSubmissionClearanceEvidenceMixin(ControlledSubmissionClearanceContext):
    def _resolve_broker_source(
        self,
        broker_evidence: list[dict[str, Any]],
        *,
        account_truth: dict[str, Any],
        evidence_required: bool,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        import_ids = sorted(
            {str(item.get("import_run_id") or "") for item in broker_evidence}
        )
        if not broker_evidence and not evidence_required:
            import_run_id = str(account_truth.get("import_run_id") or "")
        elif len(import_ids) != 1 or not import_ids[0]:
            blockers.append("controlled_submission_clearance_single_import_required")
            import_run_id = ""
        else:
            import_run_id = import_ids[0]
        db_path = getattr(self._db, "_path", None)
        repository: Any = (
            self._broker_evidence_repository(Path(db_path)) if db_path else None
        )
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

    def _resolve_terminal_lifecycle(
        self,
        *,
        intent: dict[str, Any],
        order: dict[str, Any],
    ) -> dict[str, Any]:
        db_path = getattr(self._db, "_path", None)
        payload = _json_object(intent.get("payload_json"))
        if db_path is None:
            evidence: dict[str, Any] = {}
        else:
            evidence = self._broker_order_lifecycle_repository(
                Path(db_path),
                ensure_schema=False,
            ).resolve_order(
                gateway_id=str(intent.get("gateway_id") or ""),
                account_alias=str(
                    intent.get("account_alias") or payload.get("account_alias") or ""
                ),
                broker_order_id=str(intent.get("broker_order_id") or ""),
                client_order_id=str(intent.get("client_order_id") or ""),
            )
        terminal = self._broker_order_lifecycle_terminal_outcome(order, evidence)
        return {
            **terminal,
            "terminal_evidence_source": (
                "broker_order_lifecycle_and_account_truth"
                if terminal.get("status") == "terminal"
                else ""
            ),
            "lifecycle_fills": [
                _mapping(item)
                for item in evidence.get("fills") or []
                if isinstance(item, dict)
            ],
        }

    def _resolve_account_truth(
        self,
        *,
        now: datetime,
        broker_evidence: list[dict[str, Any]],
        order: dict[str, Any],
    ) -> dict[str, Any]:
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
        expected_delta = _controlled_post_trade_account_truth_delta(
            raw,
            broker_evidence=broker_evidence,
            order=order,
        )
        exact_expected_delta = expected_delta["status"] == "exact"
        required = {"data_freshness_status": "fresh"}
        for field, expected in required.items():
            if raw.get(field) != expected:
                blockers.append(
                    f"controlled_submission_clearance_account_truth_{field}_invalid"
                )
        if raw.get("status") != "clear" and not exact_expected_delta:
            blockers.append(
                "controlled_submission_clearance_account_truth_status_invalid"
            )
        if raw.get("gate_status") != "pass" and not exact_expected_delta:
            blockers.append(
                "controlled_submission_clearance_account_truth_gate_status_invalid"
            )
        if (
            int(raw.get("unresolved_mismatch_count") or 0) != 0
            and not exact_expected_delta
        ):
            blockers.append(
                "controlled_submission_clearance_account_truth_unresolved_mismatch_count_invalid"
            )
        if (
            raw.get("reconciliation_status") not in {"clear", "pass"}
            and not exact_expected_delta
        ):
            blockers.append(
                "controlled_submission_clearance_account_truth_reconciliation_status_invalid"
            )
        if str(raw.get("import_validation_status") or "pass") != "pass":
            blockers.append(
                "controlled_submission_clearance_account_truth_import_not_pass"
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
            "status": (
                "blocked"
                if blockers
                else (
                    "expected_controlled_ledger_delta"
                    if exact_expected_delta
                    else "clear"
                )
            ),
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
            "expected_ledger_delta": expected_delta,
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
