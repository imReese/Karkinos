"""Transaction-local writes for controlled reconciliation clearance."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_clearance_repository import (
    get_fill,
    get_saved_clearance,
)
from server.persistence.controlled_clearance_values import (
    ControlledClearanceWritePlan,
)
from server.persistence.database_serialization import serialize_metadata_json
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)
from server.persistence.financial_fact_event_payloads import (
    fill_event_payload,
)


def write_controlled_clearance(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    plan: ControlledClearanceWritePlan,
) -> tuple[list[str], sqlite3.Row | None]:
    """Apply a revalidated plan without opening or committing a transaction."""

    blockers = _insert_fills(conn, requested, plan)
    if blockers:
        return blockers, None
    _write_oms_transitions(conn, requested, plan)
    _insert_clearance(conn, requested, plan)
    _insert_clearance_reconciliation(conn, requested, plan)
    insert_event_sync(
        conn,
        event_type="controlled_broker.reconciliation_cleared",
        timestamp=requested["cleared_at"],
        entity_type="controlled_submission_reconciliation_clearance",
        entity_id=requested["clearance_id"],
        source="controlled_submission_reconciliation_clearance",
        source_ref=requested["submit_intent_id"],
        payload=requested["payload"],
    )
    return [], get_saved_clearance(conn, requested["clearance_id"])


def _insert_fills(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    plan: ControlledClearanceWritePlan,
) -> list[str]:
    for fill in plan.fill_rows:
        if get_fill(conn, fill["fill_id"]) is not None:
            return ["controlled_submission_fill_id_conflict"]
        metadata_json = serialize_metadata_json(fill["metadata"])
        conn.execute(
            """
                INSERT INTO fills (
                    fill_id, order_id, timestamp, symbol, side,
                    fill_price, fill_quantity, commission, slippage,
                    asset_class, execution_mode, provider_name,
                    broker_order_id, source, source_ref, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            (
                fill["fill_id"],
                requested["order_id"],
                fill["timestamp"],
                fill["symbol"],
                fill["side"],
                float(fill["fill_price"]),
                float(fill["fill_quantity"]),
                float(fill["fee"]),
                0.0,
                fill["asset_class"],
                "controlled_live",
                fill["provider_name"],
                requested["broker_order_id"],
                "controlled_submission_clearance",
                fill["broker_event_id"],
                metadata_json,
                requested["cleared_at"],
                requested["cleared_at"],
            ),
        )
        saved_fill = get_fill(conn, fill["fill_id"])
        if saved_fill is not None:
            insert_event_sync(
                conn,
                event_type="order.fill.recorded",
                timestamp=str(saved_fill["timestamp"]),
                entity_type="fill",
                entity_id=str(saved_fill["fill_id"]),
                source="fills",
                source_ref=str(saved_fill["fill_id"]),
                payload=fill_event_payload(saved_fill),
            )
    return []


def _write_oms_transitions(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    plan: ControlledClearanceWritePlan,
) -> None:
    transition_payload = {
        "clearance_id": requested["clearance_id"],
        "submit_intent_id": requested["submit_intent_id"],
        "broker_order_id": requested["broker_order_id"],
        "filled_quantity": str(plan.fill_quantity),
        "cancelled_quantity": str(plan.cancelled_quantity),
        "terminal_status": plan.terminal_status,
        "account_truth_import_run_id": requested["account_truth_import_run_id"],
        "production_ledger_mutated": False,
    }
    transition_steps = _transition_steps(plan)
    for from_status, to_status, reason in transition_steps:
        conn.execute(
            "UPDATE oms_orders SET status = ?, updated_at = ? WHERE order_id = ?",
            (to_status, requested["cleared_at"], requested["order_id"]),
        )
        conn.execute(
            """
                INSERT INTO oms_transitions (
                    order_id, from_status, to_status, reason, actor,
                    payload_json, transitioned_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
            (
                requested["order_id"],
                from_status,
                to_status,
                reason,
                requested["operator_id"],
                _serialize_event_payload_json(transition_payload),
                requested["cleared_at"],
                requested["cleared_at"],
            ),
        )


def _transition_steps(
    plan: ControlledClearanceWritePlan,
) -> tuple[tuple[str, str, str], ...]:
    if plan.terminal_status == "filled":
        return (
            (
                "submitted",
                "accepted",
                "broker acceptance confirmed by signed reconciliation clearance",
            ),
            (
                "accepted",
                "filled",
                "full broker fill confirmed by signed reconciliation clearance",
            ),
        )
    if plan.fill_quantity > 0:
        return (
            (
                "submitted",
                "accepted",
                "broker acceptance confirmed by signed reconciliation clearance",
            ),
            (
                "accepted",
                "partially_filled",
                "partial broker fills confirmed by signed reconciliation clearance",
            ),
            (
                "partially_filled",
                "cancelled",
                "remaining quantity cancelled in exact terminal broker evidence",
            ),
        )
    return (
        (
            "submitted",
            "cancelled",
            "no-fill cancellation confirmed by signed reconciliation clearance",
        ),
    )


def _insert_clearance(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    plan: ControlledClearanceWritePlan,
) -> None:
    conn.execute(
        """
            INSERT INTO controlled_submission_reconciliation_clearances (
                clearance_id, clearance_fingerprint, submit_intent_id,
                submit_fingerprint, order_id, broker_order_id,
                review_reconciliation_run_id,
                review_reconciliation_item_id,
                broker_evidence_fingerprint,
                account_truth_import_run_id,
                account_truth_file_fingerprint,
                account_truth_source_fingerprint,
                clearance_reconciliation_run_id,
                operator_id, operator_approval_id, status,
                terminal_status, fill_count, fill_quantity,
                cancelled_quantity, lifecycle_observation_id,
                lifecycle_evidence_fingerprint,
                lifecycle_source_sequence, cleared_at_epoch_ms,
                cleared_at, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
        (
            requested["clearance_id"],
            requested["clearance_fingerprint"],
            requested["submit_intent_id"],
            requested["submit_fingerprint"],
            requested["order_id"],
            requested["broker_order_id"],
            requested["review_reconciliation_run_id"],
            int(requested["review_reconciliation_item_id"]),
            requested["broker_evidence_fingerprint"],
            requested["account_truth_import_run_id"],
            requested["account_truth_file_fingerprint"],
            requested["account_truth_source_fingerprint"],
            requested["clearance_reconciliation_run_id"],
            requested["operator_id"],
            requested["operator_approval_id"],
            "cleared",
            plan.terminal_status,
            len(plan.fill_rows),
            str(plan.fill_quantity),
            str(plan.cancelled_quantity),
            requested["lifecycle_observation_id"],
            requested["lifecycle_evidence_fingerprint"],
            int(requested["lifecycle_source_sequence"]),
            int(requested["cleared_at_epoch_ms"]),
            requested["cleared_at"],
            _serialize_event_payload_json(requested["payload"]),
            requested["cleared_at"],
        ),
    )


def _insert_clearance_reconciliation(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    plan: ControlledClearanceWritePlan,
) -> None:
    clearance_run_payload = {
        "schema_version": "karkinos.execution_reconciliation.v1",
        "source": "controlled_submission_reconciliation_clearance",
        "clearance_id": requested["clearance_id"],
        "review_reconciliation_run_id": requested["review_reconciliation_run_id"],
    }
    conn.execute(
        """
            INSERT INTO execution_reconciliation_runs (
                run_id, run_date, status, item_count, open_item_count,
                payload_json, created_at, updated_at
            ) VALUES (?, ?, 'clear', 1, 0, ?, ?, ?)
            """,
        (
            requested["clearance_reconciliation_run_id"],
            requested["clearance_run_date"],
            _serialize_event_payload_json(clearance_run_payload),
            requested["cleared_at"],
            requested["cleared_at"],
        ),
    )
    clearance_item_payload = {
        "oms_status": plan.terminal_status,
        "execution_mode": "controlled_live",
        "controlled_submission_evidence_summary": {
            "schema_version": "karkinos.controlled_submission_reconciliation.v3",
            "submit_intent_id": requested["submit_intent_id"],
            "clearance_id": requested["clearance_id"],
            "intent_status": "submitted",
            "oms_status": plan.terminal_status,
            "terminal_status": plan.terminal_status,
            "filled_quantity": str(plan.fill_quantity),
            "cancelled_quantity": str(plan.cancelled_quantity),
            "new_submissions_blocked": False,
            "recovery_resubmission_enabled": False,
            "production_ledger_mutated": False,
        },
    }
    conn.execute(
        """
            INSERT INTO execution_reconciliation_items (
                run_id, order_id, item_status, suggested_action,
                gateway_event_count, broker_event_count, detail,
                payload_json, created_at
            ) VALUES (?, ?, ?, 'no_action', 0, ?, ?, ?, ?)
            """,
        (
            requested["clearance_reconciliation_run_id"],
            requested["order_id"],
            "controlled_submission_reconciliation_cleared",
            len(plan.fill_rows),
            (
                "Signed controlled-submission reconciliation clearance "
                f"recorded exact {plan.terminal_status} outcome without "
                "production-ledger mutation."
            ),
            _serialize_event_payload_json(clearance_item_payload),
            requested["cleared_at"],
        ),
    )
