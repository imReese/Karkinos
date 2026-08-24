"""Controlled execution persistence capability: controlled_clearance_uow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from server.persistence.controlled_execution_access import (
    ControlledExecutionRepositoryAccess,
)
from server.persistence.database_support import (
    controlled_submission_clearance_rejection,
    fill_event_payload,
    json_dict,
    serialize_metadata_json,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledClearanceUnitOfWorkMixin(ControlledExecutionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def record_controlled_submission_reconciliation_clearance_sync(
        self,
        *,
        clearance: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically record real fills, terminal OMS state, and clearance."""
        requested = dict(clearance)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                        SELECT *
                        FROM controlled_submission_reconciliation_clearances
                        WHERE clearance_id = ? OR submit_intent_id = ? OR order_id = ?
                        ORDER BY id ASC LIMIT 1
                        """,
                    (
                        requested["clearance_id"],
                        requested["submit_intent_id"],
                        requested["order_id"],
                    ),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["clearance_id"] == requested["clearance_id"]
                        and existing["clearance_fingerprint"]
                        == requested["clearance_fingerprint"]
                        and existing["submit_intent_id"]
                        == requested["submit_intent_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "cleared",
                            "blockers": [],
                            "reused": True,
                            "clearance": dict(existing),
                        }
                    conn.rollback()
                    return controlled_submission_clearance_rejection(
                        requested,
                        ["controlled_submission_clearance_conflict"],
                    )

                intent = conn.execute(
                    """
                        SELECT * FROM controlled_broker_submit_intents
                        WHERE submit_intent_id = ? LIMIT 1
                        """,
                    (requested["submit_intent_id"],),
                ).fetchone()
                order = conn.execute(
                    "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
                    (requested["order_id"],),
                ).fetchone()
                latest_item = conn.execute(
                    """
                        SELECT * FROM execution_reconciliation_items
                        WHERE order_id = ? ORDER BY id DESC LIMIT 1
                        """,
                    (requested["order_id"],),
                ).fetchone()
                blockers: list[str] = []
                if intent is None:
                    blockers.append("controlled_submission_intent_not_found")
                else:
                    if str(intent["status"]) != "submitted":
                        blockers.append("controlled_submission_intent_not_submitted")
                    if str(intent["order_id"]) != requested["order_id"]:
                        blockers.append("controlled_submission_intent_order_mismatch")
                    if (
                        str(intent["submit_fingerprint"])
                        != requested["submit_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_submission_submit_fingerprint_changed"
                        )
                    if str(intent["broker_order_id"]) != requested["broker_order_id"]:
                        blockers.append("controlled_submission_broker_order_changed")
                    if str(intent["client_order_id"]) != requested["client_order_id"]:
                        blockers.append("controlled_submission_client_order_changed")
                if order is None or str(order["status"]) != "submitted":
                    blockers.append("controlled_submission_oms_not_submitted")
                if intent is not None and order is not None:
                    from account_truth.broker_order_lifecycle import (
                        broker_order_lifecycle_terminal_outcome,
                        resolve_broker_order_lifecycle_from_connection,
                    )

                    account_alias = str(
                        json_dict(intent["payload_json"]).get("account_alias") or ""
                    )
                    if account_alias:
                        lifecycle_evidence = (
                            resolve_broker_order_lifecycle_from_connection(
                                conn,
                                gateway_id=str(intent["gateway_id"] or ""),
                                account_alias=account_alias,
                                broker_order_id=str(intent["broker_order_id"] or ""),
                                client_order_id=str(intent["client_order_id"] or ""),
                            )
                        )
                        terminal_lifecycle = broker_order_lifecycle_terminal_outcome(
                            dict(order),
                            lifecycle_evidence,
                        )
                        if terminal_lifecycle["status"] in {
                            "blocked",
                            "non_terminal",
                        }:
                            blockers.extend(terminal_lifecycle["blockers"])
                            blockers.append(
                                "controlled_submission_terminal_outcome_changed"
                            )
                        elif terminal_lifecycle["status"] == "terminal":
                            expected_terminal_fields = {
                                "terminal_status": requested["terminal_status"],
                                "filled_quantity": requested["fill_quantity"],
                                "cancelled_quantity": requested["cancelled_quantity"],
                                "observation_id": requested["lifecycle_observation_id"],
                                "evidence_fingerprint": requested[
                                    "lifecycle_evidence_fingerprint"
                                ],
                                "source_sequence": requested[
                                    "lifecycle_source_sequence"
                                ],
                            }
                            for field, expected in expected_terminal_fields.items():
                                if str(terminal_lifecycle.get(field) or "") != str(
                                    expected or ""
                                ):
                                    blockers.append(
                                        "controlled_submission_terminal_"
                                        f"lifecycle_{field}_changed"
                                    )
                        elif requested["terminal_status"] == "cancelled":
                            blockers.append(
                                "controlled_submission_terminal_lifecycle_missing"
                            )
                if latest_item is None:
                    blockers.append("controlled_submission_reconciliation_item_missing")
                else:
                    if int(latest_item["id"]) != int(
                        requested["review_reconciliation_item_id"]
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_item_superseded"
                        )
                    if (
                        str(latest_item["run_id"])
                        != requested["review_reconciliation_run_id"]
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_run_changed"
                        )
                    clearable_item_statuses = {
                        "filled": {"controlled_submission_broker_evidence_available"},
                        "cancelled": {
                            "controlled_submission_partial_fill_cancel_evidence_available",
                            "controlled_submission_cancel_evidence_available",
                        },
                    }
                    if str(
                        latest_item["item_status"]
                    ) not in clearable_item_statuses.get(
                        str(requested.get("terminal_status") or ""),
                        set(),
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_item_not_clearable"
                        )
                    item_payload = json_dict(latest_item["payload_json"])
                    item_summary = item_payload.get(
                        "controlled_submission_evidence_summary"
                    )
                    item_summary = (
                        item_summary if isinstance(item_summary, dict) else {}
                    )
                    if (
                        str(item_summary.get("submit_intent_id") or "")
                        != requested["submit_intent_id"]
                    ):
                        blockers.append(
                            "controlled_submission_reconciliation_intent_changed"
                        )
                    if (
                        str(item_summary.get("broker_evidence_fingerprint") or "")
                        != requested["broker_evidence_fingerprint"]
                    ):
                        blockers.append("controlled_submission_broker_evidence_changed")

                latest_import = conn.execute("""
                        SELECT * FROM broker_import_runs
                        WHERE validation_status != 'blocked'
                        ORDER BY created_at DESC, id DESC LIMIT 1
                        """).fetchone()
                if latest_import is None:
                    blockers.append(
                        "controlled_submission_account_truth_import_missing"
                    )
                else:
                    if (
                        str(latest_import["import_run_id"])
                        != requested["account_truth_import_run_id"]
                    ):
                        blockers.append(
                            "controlled_submission_account_truth_import_superseded"
                        )
                    if (
                        str(latest_import["file_fingerprint"])
                        != requested["account_truth_file_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_submission_account_truth_file_changed"
                        )

                fill_rows = list(requested.get("fills") or [])
                terminal_status = str(requested.get("terminal_status") or "")
                if not fill_rows and terminal_status != "cancelled":
                    blockers.append("controlled_submission_fill_evidence_missing")
                fill_quantity = sum(
                    (
                        Decimal(str(item.get("fill_quantity") or "0"))
                        for item in fill_rows
                    ),
                    Decimal("0"),
                )
                order_quantity = (
                    Decimal(str(order["quantity"]))
                    if order is not None
                    else Decimal("0")
                )
                cancelled_quantity = Decimal(
                    str(requested.get("cancelled_quantity") or "0")
                )
                if str(requested.get("fill_quantity") or "0") != str(fill_quantity):
                    blockers.append("controlled_submission_fill_quantity_changed")
                if terminal_status == "filled" and (
                    fill_quantity <= 0
                    or fill_quantity != abs(order_quantity)
                    or cancelled_quantity != 0
                ):
                    blockers.append("controlled_submission_full_fill_incomplete")
                elif terminal_status == "cancelled" and (
                    cancelled_quantity <= 0
                    or fill_quantity + cancelled_quantity != abs(order_quantity)
                ):
                    blockers.append("controlled_submission_cancel_quantity_incomplete")
                elif terminal_status not in {"filled", "cancelled"}:
                    blockers.append("controlled_submission_terminal_status_invalid")
                for fill in fill_rows:
                    broker_event = conn.execute(
                        """
                            SELECT * FROM broker_evidence_events
                            WHERE import_run_id = ? AND event_id = ?
                              AND row_fingerprint = ?
                            LIMIT 1
                            """,
                        (
                            fill.get("account_truth_import_run_id"),
                            fill.get("broker_event_id"),
                            fill.get("broker_row_fingerprint"),
                        ),
                    ).fetchone()
                    if broker_event is None:
                        blockers.append(
                            "controlled_submission_broker_event_source_changed"
                        )
                        continue
                    expected_values = {
                        "symbol": fill.get("symbol"),
                        "price": fill.get("fill_price"),
                        "fee": fill.get("fee"),
                        "tax": fill.get("tax"),
                        "transfer_fee": fill.get("transfer_fee"),
                        "broker_order_id": requested["broker_order_id"],
                        "client_order_id": requested["client_order_id"],
                    }
                    for field, expected in expected_values.items():
                        if str(broker_event[field] or "") != str(expected or ""):
                            blockers.append(
                                f"controlled_submission_broker_event_{field}_changed"
                            )
                    if abs(Decimal(str(broker_event["quantity"]))) != Decimal(
                        str(fill.get("fill_quantity") or "0")
                    ):
                        blockers.append(
                            "controlled_submission_broker_event_quantity_changed"
                        )
                if blockers:
                    conn.rollback()
                    return controlled_submission_clearance_rejection(
                        requested,
                        blockers,
                    )

                for fill in fill_rows:
                    existing_fill = conn.execute(
                        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1",
                        (fill["fill_id"],),
                    ).fetchone()
                    if existing_fill is not None:
                        conn.rollback()
                        return controlled_submission_clearance_rejection(
                            requested,
                            ["controlled_submission_fill_id_conflict"],
                        )
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
                    saved_fill = conn.execute(
                        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1",
                        (fill["fill_id"],),
                    ).fetchone()
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

                transition_payload = {
                    "clearance_id": requested["clearance_id"],
                    "submit_intent_id": requested["submit_intent_id"],
                    "broker_order_id": requested["broker_order_id"],
                    "filled_quantity": str(fill_quantity),
                    "cancelled_quantity": str(cancelled_quantity),
                    "terminal_status": terminal_status,
                    "account_truth_import_run_id": requested[
                        "account_truth_import_run_id"
                    ],
                    "production_ledger_mutated": False,
                }
                if terminal_status == "filled":
                    transition_steps = (
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
                elif fill_quantity > 0:
                    transition_steps = (
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
                else:
                    transition_steps = (
                        (
                            "submitted",
                            "cancelled",
                            "no-fill cancellation confirmed by signed reconciliation clearance",
                        ),
                    )
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
                        terminal_status,
                        len(fill_rows),
                        str(fill_quantity),
                        str(cancelled_quantity),
                        requested["lifecycle_observation_id"],
                        requested["lifecycle_evidence_fingerprint"],
                        int(requested["lifecycle_source_sequence"]),
                        int(requested["cleared_at_epoch_ms"]),
                        requested["cleared_at"],
                        _serialize_event_payload_json(requested["payload"]),
                        requested["cleared_at"],
                    ),
                )

                clearance_run_payload = {
                    "schema_version": "karkinos.execution_reconciliation.v1",
                    "source": "controlled_submission_reconciliation_clearance",
                    "clearance_id": requested["clearance_id"],
                    "review_reconciliation_run_id": requested[
                        "review_reconciliation_run_id"
                    ],
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
                    "oms_status": terminal_status,
                    "execution_mode": "controlled_live",
                    "controlled_submission_evidence_summary": {
                        "schema_version": (
                            "karkinos.controlled_submission_reconciliation.v3"
                        ),
                        "submit_intent_id": requested["submit_intent_id"],
                        "clearance_id": requested["clearance_id"],
                        "intent_status": "submitted",
                        "oms_status": terminal_status,
                        "terminal_status": terminal_status,
                        "filled_quantity": str(fill_quantity),
                        "cancelled_quantity": str(cancelled_quantity),
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
                        len(fill_rows),
                        (
                            "Signed controlled-submission reconciliation clearance "
                            f"recorded exact {terminal_status} outcome without "
                            "production-ledger mutation."
                        ),
                        _serialize_event_payload_json(clearance_item_payload),
                        requested["cleared_at"],
                    ),
                )
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
                saved = conn.execute(
                    """
                        SELECT * FROM controlled_submission_reconciliation_clearances
                        WHERE clearance_id = ? LIMIT 1
                        """,
                    (requested["clearance_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "cleared",
                    "blockers": [],
                    "reused": False,
                    "clearance": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
            ):
                conn.rollback()
                return controlled_submission_clearance_rejection(
                    requested,
                    ["controlled_submission_clearance_transaction_unavailable"],
                )
