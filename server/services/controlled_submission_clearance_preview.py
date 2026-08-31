"""Fail-closed preview for exact-terminal reconciliation clearance."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
)
from server.services.controlled_submission_clearance_context import (
    ControlledSubmissionClearanceContext,
)
from server.services.controlled_submission_clearance_evidence_values import (
    fill_descriptor as _fill_descriptor,
)
from server.services.controlled_submission_clearance_evidence_values import (
    reconciliation_item_contract as _reconciliation_item_contract,
)
from server.services.controlled_submission_clearance_evidence_values import (
    terminal_cancel_statement_blockers as _terminal_cancel_statement_blockers,
)
from server.services.controlled_submission_clearance_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_submission_clearance_values import (
    ID_PATTERN as _ID_PATTERN,
)
from server.services.controlled_submission_clearance_values import (
    aware_utc as _aware_utc,
)
from server.services.controlled_submission_clearance_values import (
    clearance_response as _clearance_response,
)
from server.services.controlled_submission_clearance_values import (
    decimal_string as _decimal_string,
)
from server.services.controlled_submission_clearance_values import (
    decimal_value as _decimal,
)
from server.services.controlled_submission_clearance_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_submission_clearance_values import (
    json_object as _json_object,
)
from server.services.controlled_submission_clearance_values import mapping as _mapping
from server.services.controlled_submission_clearance_values import (
    safety_flags as _safety_flags,
)


class ControlledSubmissionClearancePreviewMixin(ControlledSubmissionClearanceContext):
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
            self._build_order_fingerprint(order)
        ):
            blockers.append("controlled_submission_clearance_order_changed")
        broker_order_id = str(intent.get("broker_order_id") or "")
        if not _ID_PATTERN.fullmatch(broker_order_id):
            blockers.append("controlled_submission_clearance_broker_order_id_invalid")
        client_order_id = str(intent.get("client_order_id") or "")
        if not _ID_PATTERN.fullmatch(client_order_id):
            blockers.append("controlled_submission_clearance_client_order_id_invalid")

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
            item_status = str(latest_item.get("item_status") or "")
            expected_actions = {
                "controlled_submission_broker_evidence_available": (
                    "review_controlled_submission_broker_evidence"
                ),
                "controlled_submission_partial_fill_cancel_evidence_available": (
                    "review_partial_fill_cancel_and_import_account_truth"
                ),
                "controlled_submission_cancel_evidence_available": (
                    "review_cancel_evidence_before_interlock_clearance"
                ),
            }
            if item_status not in expected_actions:
                blockers.append("controlled_submission_clearance_item_not_clearable")
            elif (
                str(latest_item.get("suggested_action") or "")
                != expected_actions[item_status]
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
        if str(controlled_summary.get("broker_evidence_fingerprint") or "") != (
            broker_evidence_fingerprint
        ):
            blockers.append(
                "controlled_submission_clearance_broker_fingerprint_invalid"
            )

        account_truth = self._resolve_account_truth(
            now=now,
            broker_evidence=broker_evidence,
            order=order,
        )
        blockers.extend(account_truth["blockers"])
        terminal_lifecycle = self._resolve_terminal_lifecycle(
            intent=intent,
            order=order,
        )
        blockers.extend(terminal_lifecycle["blockers"])

        order_quantity = abs(_decimal(order.get("quantity")) or Decimal("0"))
        broker_quantity = sum(
            (
                abs(_decimal(event.get("quantity")) or Decimal("0"))
                for event in broker_evidence
            ),
            Decimal("0"),
        )
        terminal_status = str(terminal_lifecycle.get("terminal_status") or "")
        if terminal_lifecycle["status"] == "non_terminal":
            blockers.append("controlled_submission_clearance_terminal_outcome_required")
        elif terminal_lifecycle["status"] == "not_available":
            if order_quantity > 0 and broker_quantity == order_quantity:
                terminal_status = "filled"
                terminal_lifecycle = {
                    **terminal_lifecycle,
                    "terminal_status": terminal_status,
                    "order_quantity": _decimal_string(order_quantity),
                    "filled_quantity": _decimal_string(broker_quantity),
                    "cancelled_quantity": "0",
                    "terminal_evidence_source": "independent_broker_statement",
                }
            else:
                blockers.append(
                    "controlled_submission_clearance_terminal_outcome_required"
                )

        filled_quantity = _decimal(
            terminal_lifecycle.get("filled_quantity")
        ) or Decimal("0")
        cancelled_quantity = _decimal(
            terminal_lifecycle.get("cancelled_quantity")
        ) or Decimal("0")
        if terminal_status not in {"filled", "cancelled"}:
            blockers.append("controlled_submission_clearance_terminal_status_invalid")
        if broker_quantity != filled_quantity:
            blockers.append(
                "controlled_submission_clearance_broker_fill_quantity_mismatch"
            )
        if terminal_status == "filled" and (
            filled_quantity != order_quantity or cancelled_quantity != 0
        ):
            blockers.append("controlled_submission_clearance_full_fill_mismatch")
        if terminal_status == "cancelled" and (
            cancelled_quantity <= 0
            or filled_quantity + cancelled_quantity != order_quantity
        ):
            blockers.append("controlled_submission_clearance_cancel_quantity_mismatch")
        if filled_quantity > 0 and not broker_evidence:
            blockers.append("controlled_submission_clearance_broker_evidence_missing")
        if terminal_status == "cancelled" and filled_quantity > 0:
            blockers.extend(
                _terminal_cancel_statement_blockers(
                    terminal_lifecycle,
                    broker_evidence,
                )
            )

        source = self._resolve_broker_source(
            broker_evidence,
            account_truth=account_truth,
            evidence_required=filled_quantity > 0,
        )
        blockers.extend(source["blockers"])
        if source["import_run_id"] != account_truth["import_run_id"]:
            blockers.append(
                "controlled_submission_clearance_account_truth_import_mismatch"
            )
        if source["file_fingerprint"] != account_truth["file_fingerprint"]:
            blockers.append(
                "controlled_submission_clearance_account_truth_file_mismatch"
            )

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
            if str(event.get("broker_order_id") or "") != broker_order_id:
                blockers.append(
                    "controlled_submission_clearance_broker_order_identity_mismatch"
                )
            if str(event.get("client_order_id") or "") != client_order_id:
                blockers.append(
                    "controlled_submission_clearance_client_order_identity_mismatch"
                )

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
            "client_order_id": client_order_id,
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
            "account_truth_resolution_status": account_truth["status"],
            "expected_ledger_delta_fingerprint": str(
                account_truth.get("expected_ledger_delta", {}).get("fingerprint") or ""
            ),
            "terminal_status": terminal_status,
            "terminal_evidence_source": str(
                terminal_lifecycle.get("terminal_evidence_source")
                or "broker_order_lifecycle_and_account_truth"
            ),
            "cancelled_quantity": _decimal_string(cancelled_quantity),
            "lifecycle_observation_id": str(
                terminal_lifecycle.get("observation_id") or ""
            ),
            "lifecycle_evidence_fingerprint": str(
                terminal_lifecycle.get("evidence_fingerprint") or ""
            ),
            "lifecycle_source_sequence": int(
                terminal_lifecycle.get("source_sequence") or 0
            ),
            "lifecycle_fill_fingerprint": str(
                terminal_lifecycle.get("fill_fingerprint") or _fingerprint([])
            ),
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
                clearance_reconciliation_run_id=clearance_reconciliation_run_id,
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
            "terminal_lifecycle": {
                key: value
                for key, value in terminal_lifecycle.items()
                if key != "lifecycle_fills"
            },
            "fills": fills,
            "required_operator_approval": {
                "action": "clear_controlled_submission_reconciliation",
                "artifact_type": "controlled_submission_reconciliation_clearance",
                "artifact_fingerprint": clearance_fingerprint,
            },
            "interlock_released": False,
            "oms_mutated": False,
            "real_fills_recorded": False,
            "production_ledger_mutated": False,
            "safety": _safety_flags(),
        }
