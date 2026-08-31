"""Controlled execution persistence capability: controlled_broker_intents."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from server.persistence.controlled_clearance_lifecycle import (
    controlled_lifecycle_invalidated_clearance_rows,
)
from server.persistence.controlled_execution_access import (
    ControlledExecutionRepositoryAccess,
)
from server.persistence.controlled_execution_rejections import (
    controlled_broker_submit_rejection,
)
from server.persistence.database_normalization import json_dict
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledBrokerIntentRepositoryMixin(ControlledExecutionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

    def prepare_controlled_broker_submit_intent_sync(
        self,
        *,
        intent: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one one-shot submit intent before any external broker call."""
        requested = dict(intent)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                        SELECT * FROM controlled_broker_submit_intents
                        WHERE submit_intent_id = ? OR order_id = ? OR client_order_id = ?
                        ORDER BY id ASC
                        LIMIT 1
                        """,
                    (
                        requested["submit_intent_id"],
                        requested["order_id"],
                        requested["client_order_id"],
                    ),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["submit_intent_id"] == requested["submit_intent_id"]
                        and existing["submit_fingerprint"]
                        == requested["submit_fingerprint"]
                        and existing["order_id"] == requested["order_id"]
                        and existing["client_order_id"] == requested["client_order_id"]
                    ):
                        conn.commit()
                        return {
                            "status": str(existing["status"]),
                            "blockers": [],
                            "reused": True,
                            "external_call_permitted": False,
                            "intent": dict(existing),
                        }
                    conn.rollback()
                    return controlled_broker_submit_rejection(
                        requested,
                        ["controlled_broker_submit_intent_conflict"],
                    )
                unresolved = conn.execute(
                    """
                        SELECT submit_intent_id, order_id, status
                        FROM controlled_broker_submit_intents AS intent
                        WHERE intent.status IN (
                            'prepared', 'submitted', 'submission_unknown'
                        )
                          AND intent.order_id != ?
                          AND NOT EXISTS (
                              SELECT 1
                              FROM controlled_submission_reconciliation_clearances AS clearance
                              WHERE clearance.submit_intent_id = intent.submit_intent_id
                                AND clearance.status = 'cleared'
                          )
                        ORDER BY intent.id ASC
                        LIMIT 1
                        """,
                    (requested["order_id"],),
                ).fetchone()
                lifecycle_invalidated_clearances = (
                    controlled_lifecycle_invalidated_clearance_rows(
                        conn,
                        exclude_order_id=requested["order_id"],
                        limit=1,
                    )
                )
                order = conn.execute(
                    "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
                    (requested["order_id"],),
                ).fetchone()
                blockers: list[str] = []
                if unresolved is not None:
                    blockers.append(
                        "controlled_broker_submit_unreconciled_intent_exists"
                    )
                if lifecycle_invalidated_clearances:
                    blockers.append(
                        "controlled_broker_submit_lifecycle_clearance_invalidated"
                    )
                if order is None:
                    blockers.append("controlled_broker_submit_order_not_found")
                else:
                    if order["status"] != "manually_confirmed":
                        blockers.append(
                            "controlled_broker_submit_order_not_manually_confirmed"
                        )
                    snapshot = requested["order_snapshot"]
                    for field in ("symbol", "side", "asset_class", "order_type"):
                        if str(order[field] or "") != str(snapshot.get(field) or ""):
                            blockers.append(
                                f"controlled_broker_submit_order_{field}_changed"
                            )
                    if float(order["quantity"]) != float(snapshot.get("quantity")):
                        blockers.append(
                            "controlled_broker_submit_order_quantity_changed"
                        )
                    current_limit = (
                        None
                        if order["limit_price"] is None
                        else float(order["limit_price"])
                    )
                    requested_limit = (
                        None
                        if snapshot.get("limit_price") in {None, ""}
                        else float(snapshot.get("limit_price"))
                    )
                    if current_limit != requested_limit:
                        blockers.append(
                            "controlled_broker_submit_order_limit_price_changed"
                        )
                kill_switch_row = conn.execute(
                    "SELECT value_json FROM runtime_controls WHERE key = 'kill_switch' LIMIT 1"
                ).fetchone()
                if kill_switch_row is not None:
                    kill_switch = json_dict(kill_switch_row["value_json"])
                    if kill_switch.get("enabled") is True:
                        blockers.append("controlled_broker_submit_kill_switch_enabled")
                if blockers:
                    conn.rollback()
                    return controlled_broker_submit_rejection(requested, blockers)
                conn.execute(
                    """
                        INSERT INTO controlled_broker_submit_intents (
                            submit_intent_id, submit_fingerprint, order_id,
                            order_fingerprint, confirmation_id, dossier_fingerprint,
                            gateway_id, gateway_verification_fingerprint,
                            release_evidence_id, release_evidence_fingerprint,
                            client_order_id, operator_id, operator_approval_id,
                            status, broker_order_id, broker_status,
                            prepared_at_epoch_ms, prepared_at, last_recovery_at_epoch_ms,
                            last_recovery_at, payload_json, result_json, created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                    (
                        requested["submit_intent_id"],
                        requested["submit_fingerprint"],
                        requested["order_id"],
                        requested["order_fingerprint"],
                        requested["confirmation_id"],
                        requested["dossier_fingerprint"],
                        requested["gateway_id"],
                        requested["gateway_verification_fingerprint"],
                        requested["release_evidence_id"],
                        requested["release_evidence_fingerprint"],
                        requested["client_order_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        "prepared",
                        "",
                        "",
                        int(requested["prepared_at_epoch_ms"]),
                        requested["prepared_at"],
                        0,
                        "",
                        _serialize_event_payload_json(requested["payload"]),
                        "{}",
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                        UPDATE oms_orders
                        SET status = 'submission_pending', updated_at = ?
                        WHERE order_id = ? AND status = 'manually_confirmed'
                        """,
                    (requested["created_at"], requested["order_id"]),
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
                        "manually_confirmed",
                        "submission_pending",
                        "signed controlled broker submit intent prepared",
                        requested["operator_id"],
                        _serialize_event_payload_json(
                            {
                                "submit_intent_id": requested["submit_intent_id"],
                                "submit_fingerprint": requested["submit_fingerprint"],
                                "gateway_id": requested["gateway_id"],
                                "client_order_id": requested["client_order_id"],
                                "one_shot_manual_authority": True,
                                "strategy_direct_submission": False,
                            }
                        ),
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                        SELECT * FROM controlled_broker_submit_intents
                        WHERE submit_intent_id = ? LIMIT 1
                        """,
                    (requested["submit_intent_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "prepared",
                    "blockers": [],
                    "reused": False,
                    "external_call_permitted": True,
                    "intent": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_broker_submit_rejection(
                    requested,
                    ["controlled_broker_submit_prepare_transaction_unavailable"],
                )

    def claim_controlled_broker_recovery_query_sync(
        self,
        *,
        submit_intent_id: str,
        recovery_fingerprint: str,
        operator_approval_id: str,
        claimed_at_epoch_ms: int,
        claimed_at: str,
        minimum_wait_seconds: int,
    ) -> dict[str, Any]:
        """Atomically admit one query-only recovery attempt and audit its identity."""
        requested = {
            "submit_intent_id": str(submit_intent_id or ""),
            "recovery_fingerprint": str(recovery_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
        }
        if (
            len(requested["recovery_fingerprint"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in requested["recovery_fingerprint"]
            )
            or len(requested["operator_approval_id"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in requested["operator_approval_id"]
            )
            or int(claimed_at_epoch_ms) < 0
            or int(minimum_wait_seconds) < 1
        ):
            return controlled_broker_submit_rejection(
                requested,
                ["controlled_broker_recovery_query_claim_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                intent = conn.execute(
                    """
                        SELECT * FROM controlled_broker_submit_intents
                        WHERE submit_intent_id = ? LIMIT 1
                        """,
                    (requested["submit_intent_id"],),
                ).fetchone()
                if intent is None:
                    conn.rollback()
                    return controlled_broker_submit_rejection(
                        requested,
                        ["controlled_broker_submit_intent_not_found"],
                    )
                current_status = str(intent["status"])
                if current_status in {"submitted", "rejected"}:
                    conn.commit()
                    return {
                        "status": current_status,
                        "blockers": [],
                        "reused": True,
                        "external_call_permitted": False,
                        "intent": dict(intent),
                    }
                if current_status not in {"prepared", "submission_unknown"}:
                    conn.rollback()
                    return controlled_broker_submit_rejection(
                        dict(intent),
                        ["controlled_broker_recovery_query_state_invalid"],
                    )
                previous_attempt_epoch_ms = max(
                    int(intent["prepared_at_epoch_ms"] or 0),
                    int(intent["last_recovery_at_epoch_ms"] or 0),
                )
                minimum_wait_ms = int(minimum_wait_seconds) * 1000
                elapsed_ms = max(
                    0,
                    int(claimed_at_epoch_ms) - previous_attempt_epoch_ms,
                )
                if elapsed_ms < minimum_wait_ms:
                    conn.commit()
                    return {
                        "status": "recovery_wait_required",
                        "blockers": ["controlled_broker_recovery_query_wait_required"],
                        "reused": True,
                        "external_call_permitted": False,
                        "recovery_wait_remaining_seconds": max(
                            1,
                            (minimum_wait_ms - elapsed_ms + 999) // 1000,
                        ),
                        "intent": dict(intent),
                    }
                claim_id = hashlib.sha256(
                    json.dumps(
                        {
                            "domain": "karkinos.controlled_broker.recovery_query_claim.v1",
                            **requested,
                            "claimed_at_epoch_ms": int(claimed_at_epoch_ms),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                conn.execute(
                    """
                        UPDATE controlled_broker_submit_intents
                        SET last_recovery_at_epoch_ms = ?, last_recovery_at = ?,
                            updated_at = ?
                        WHERE submit_intent_id = ?
                        """,
                    (
                        int(claimed_at_epoch_ms),
                        claimed_at,
                        claimed_at,
                        requested["submit_intent_id"],
                    ),
                )
                event = {
                    "schema_version": "karkinos.controlled_broker_recovery_query_claim.v1",
                    "claim_id": claim_id,
                    **requested,
                    "source_status": current_status,
                    "client_order_id": str(intent["client_order_id"] or ""),
                    "gateway_id": str(intent["gateway_id"] or ""),
                    "query_only": True,
                    "broker_submit_enabled": False,
                    "broker_cancel_enabled": False,
                    "production_ledger_mutated": False,
                    "authority_changed": False,
                    "claimed_at_epoch_ms": int(claimed_at_epoch_ms),
                    "claimed_at": claimed_at,
                }
                cursor = insert_event_sync(
                    conn,
                    event_type="controlled_broker.recovery_query_claimed",
                    timestamp=claimed_at,
                    entity_type="controlled_broker_submission_recovery",
                    entity_id=claim_id,
                    source="controlled_broker_submission",
                    source_ref=requested["recovery_fingerprint"],
                    payload=event,
                )
                saved = conn.execute(
                    """
                        SELECT * FROM controlled_broker_submit_intents
                        WHERE submit_intent_id = ? LIMIT 1
                        """,
                    (requested["submit_intent_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "recovery_query_claimed",
                    "blockers": [],
                    "reused": False,
                    "external_call_permitted": True,
                    "claim_id": claim_id,
                    "event_id": cursor.lastrowid or 0,
                    "intent": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_broker_submit_rejection(
                    requested,
                    ["controlled_broker_recovery_query_claim_transaction_unavailable"],
                )

    def finalize_controlled_broker_submit_intent_sync(
        self,
        *,
        submit_intent_id: str,
        status: str,
        broker_order_id: str,
        broker_status: str,
        result: dict[str, Any],
        actor: str,
        finalized_at_epoch_ms: int,
        finalized_at: str,
        recovered: bool = False,
    ) -> dict[str, Any]:
        """Persist a broker result without ever retrying the external submit call."""
        normalized_status = str(status or "")
        if normalized_status not in {"submitted", "rejected", "submission_unknown"}:
            return controlled_broker_submit_rejection(
                {"submit_intent_id": submit_intent_id},
                ["controlled_broker_submit_result_status_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                intent = conn.execute(
                    """
                        SELECT * FROM controlled_broker_submit_intents
                        WHERE submit_intent_id = ? LIMIT 1
                        """,
                    (submit_intent_id,),
                ).fetchone()
                if intent is None:
                    conn.rollback()
                    return controlled_broker_submit_rejection(
                        {"submit_intent_id": submit_intent_id},
                        ["controlled_broker_submit_intent_not_found"],
                    )
                current_status = str(intent["status"])
                if current_status in {"submitted", "rejected"}:
                    if current_status != normalized_status:
                        conn.rollback()
                        return controlled_broker_submit_rejection(
                            dict(intent),
                            ["controlled_broker_submit_terminal_result_conflict"],
                        )
                    conn.commit()
                    return {
                        "status": current_status,
                        "blockers": [],
                        "reused": True,
                        "intent": dict(intent),
                    }
                if current_status not in {"prepared", "submission_unknown"}:
                    conn.rollback()
                    return controlled_broker_submit_rejection(
                        dict(intent),
                        ["controlled_broker_submit_state_invalid"],
                    )
                order = conn.execute(
                    "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
                    (intent["order_id"],),
                ).fetchone()
                expected_order_statuses = {"submission_pending", "submission_unknown"}
                if order is None or str(order["status"]) not in expected_order_statuses:
                    conn.rollback()
                    return controlled_broker_submit_rejection(
                        dict(intent),
                        ["controlled_broker_submit_oms_state_changed"],
                    )
                from_status = str(order["status"])
                conn.execute(
                    """
                        UPDATE controlled_broker_submit_intents
                        SET status = ?, broker_order_id = ?, broker_status = ?,
                            result_json = ?, last_recovery_at_epoch_ms = ?,
                            last_recovery_at = ?, updated_at = ?
                        WHERE submit_intent_id = ?
                        """,
                    (
                        normalized_status,
                        broker_order_id,
                        broker_status,
                        _serialize_event_payload_json(result),
                        int(finalized_at_epoch_ms) if recovered else 0,
                        finalized_at if recovered else "",
                        finalized_at,
                        submit_intent_id,
                    ),
                )
                if from_status != normalized_status:
                    conn.execute(
                        "UPDATE oms_orders SET status = ?, updated_at = ? WHERE order_id = ?",
                        (normalized_status, finalized_at, intent["order_id"]),
                    )
                    conn.execute(
                        """
                            INSERT INTO oms_transitions (
                                order_id, from_status, to_status, reason, actor,
                                payload_json, transitioned_at, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                        (
                            intent["order_id"],
                            from_status,
                            normalized_status,
                            (
                                "controlled broker submission recovered by query"
                                if recovered
                                else "controlled broker submission result recorded"
                            ),
                            actor,
                            _serialize_event_payload_json(
                                {
                                    "submit_intent_id": submit_intent_id,
                                    "gateway_id": intent["gateway_id"],
                                    "client_order_id": intent["client_order_id"],
                                    "broker_order_id": broker_order_id,
                                    "broker_status": broker_status,
                                    "recovered": recovered,
                                    "production_ledger_mutated": False,
                                }
                            ),
                            finalized_at,
                            finalized_at,
                        ),
                    )
                saved = conn.execute(
                    """
                        SELECT * FROM controlled_broker_submit_intents
                        WHERE submit_intent_id = ? LIMIT 1
                        """,
                    (submit_intent_id,),
                ).fetchone()
                conn.commit()
                return {
                    "status": normalized_status,
                    "blockers": [],
                    "reused": False,
                    "intent": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_broker_submit_rejection(
                    {"submit_intent_id": submit_intent_id},
                    ["controlled_broker_submit_finalize_transaction_unavailable"],
                )

    def get_controlled_broker_submit_intent_sync(
        self,
        submit_intent_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE submit_intent_id = ? LIMIT 1
                    """,
                (submit_intent_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_broker_submit_intent_for_order_sync(
        self,
        order_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM controlled_broker_submit_intents
                    WHERE order_id = ? LIMIT 1
                    """,
                (order_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_broker_submit_intents_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                    SELECT * FROM controlled_broker_submit_intents
                    ORDER BY prepared_at_epoch_ms DESC, id DESC LIMIT ?
                    """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_unreconciled_controlled_broker_submit_intents_sync(
        self,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List controlled intents that still block every different order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                    SELECT intent.*
                    FROM controlled_broker_submit_intents AS intent
                    WHERE intent.status IN (
                        'prepared', 'submitted', 'submission_unknown'
                    )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM controlled_submission_reconciliation_clearances AS clearance
                          WHERE clearance.submit_intent_id = intent.submit_intent_id
                            AND clearance.status = 'cleared'
                      )
                    ORDER BY intent.prepared_at_epoch_ms ASC, intent.id ASC
                    LIMIT ?
                    """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            unresolved = [dict(row) for row in rows]
            known_ids = {str(row.get("submit_intent_id") or "") for row in unresolved}
            for row in controlled_lifecycle_invalidated_clearance_rows(
                conn,
                limit=max(1, min(int(limit), 500)),
            ):
                if str(row.get("submit_intent_id") or "") not in known_ids:
                    unresolved.append(row)
            unresolved.sort(
                key=lambda row: (
                    int(row.get("prepared_at_epoch_ms") or 0),
                    int(row.get("id") or 0),
                )
            )
            return unresolved[: max(1, min(int(limit), 500))]
