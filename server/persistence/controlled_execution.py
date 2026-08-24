"""SQLite repository for controlled submission, reconciliation clearance, posting, and correction."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from server.persistence.connection import DateTimeNow, SQLiteRepository
from server.persistence.database_support import (
    account_truth_review_identity_from_connection,
    action_task_event_payload,
    apply_manual_confirmation_readiness,
    controlled_broker_submit_rejection,
    controlled_lifecycle_invalidated_clearance_rows,
    controlled_session_authority_rejection,
    controlled_session_budget_rejection,
    controlled_session_gate_snapshot_rejection,
    controlled_session_pause_rejection,
    controlled_session_rate_admission_rejection,
    controlled_submission_clearance_rejection,
    controlled_submission_ledger_correction_rejection,
    controlled_submission_ledger_posting_rejection,
    decimal_values_equal,
    event_log_response,
    event_matches_signal_journal_entry,
    fill_event_payload,
    json_dict,
    json_list,
    latest_quote_event_payload,
    latest_signal_journal_event,
    manual_order_event_payload,
    metadata_payload_value,
    normalize_timestamp,
    order_event_payload,
    paper_shadow_run_review_next_step,
    quote_observation_rank,
    risk_decision_journal_response,
    serialize_metadata_json,
    stable_json_fingerprint,
    validate_paper_shadow_run_review_transition,
    verify_controlled_ledger_entry,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)

logger = logging.getLogger(__name__)


class ValuationFacts(Protocol):
    """Persisted-fact reads required to revalidate a correction in-transaction."""

    def list_latest_quotes_sync(self) -> list[dict[str, Any]]: ...

    def list_quote_snapshots_sync(self) -> list[dict[str, Any]]: ...

    def get_market_bar_on_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_latest_market_bar_before_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_latest_daily_close_before_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_latest_quote_before_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None: ...

    def get_ledger_entries_sync(
        self, *, limit: int = 500, offset: int = 0
    ) -> list[dict[str, Any]]: ...


class ControlledExecutionRepository(SQLiteRepository):
    """Own controlled submission, reconciliation clearance, posting, and correction."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        valuation_facts: ValuationFacts,
        now: DateTimeNow | None = None,
    ) -> None:
        super().__init__(database_path, now=now)
        self._valuation_facts = valuation_facts

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

    def get_controlled_submission_reconciliation_clearance_sync(
        self,
        clearance_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM controlled_submission_reconciliation_clearances
                WHERE clearance_id = ? LIMIT 1
                """,
                (clearance_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_submission_reconciliation_clearance_for_intent_sync(
        self,
        submit_intent_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM controlled_submission_reconciliation_clearances
                WHERE submit_intent_id = ? LIMIT 1
                """,
                (submit_intent_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_reconciliation_clearances_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM controlled_submission_reconciliation_clearances
                ORDER BY cleared_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_submission_ledger_posting_sync(
        self,
        posting_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable controlled-order ledger posting."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_postings
                WHERE posting_id = ? LIMIT 1
                """,
                (posting_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_account_truth_review_identity_sync(
        self,
        import_run_id: str,
    ) -> dict[str, Any]:
        """Fingerprint current manual-review decisions for one broker import."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return account_truth_review_identity_from_connection(
                conn,
                import_run_id=import_run_id,
            )

    def get_controlled_submission_ledger_posting_for_clearance_sync(
        self,
        clearance_id: str,
    ) -> dict[str, Any] | None:
        """Read the exactly-once posting associated with one clearance."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_postings
                WHERE clearance_id = ? LIMIT 1
                """,
                (clearance_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_ledger_postings_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable controlled-order ledger postings, newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_postings
                ORDER BY applied_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_submission_ledger_correction_sync(
        self,
        correction_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable compensating correction."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_corrections
                WHERE correction_id = ? LIMIT 1
                """,
                (correction_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_submission_ledger_correction_for_posting_sync(
        self,
        posting_id: str,
    ) -> dict[str, Any] | None:
        """Read the exactly-once correction associated with one posting."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_corrections
                WHERE posting_id = ? LIMIT 1
                """,
                (posting_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_submission_ledger_corrections_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable compensating corrections, newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_submission_ledger_corrections
                ORDER BY applied_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_controlled_submission_ledger_correction_sync(
        self,
        *,
        correction: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-derive and atomically append one exact correction event."""
        from server.projections.controlled_ledger_correction import (
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
            CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
            build_controlled_ledger_correction_plan,
            correction_plan_fingerprint,
        )
        from server.projections.valuation_snapshot import (
            build_current_valuation_snapshot,
            ledger_identity_from_rows,
        )

        requested = dict(correction)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_corrections
                    WHERE correction_id = ? OR posting_id = ?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (requested["correction_id"], requested["posting_id"]),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["correction_id"]) == requested["correction_id"]
                        and str(existing["correction_fingerprint"])
                        == requested["correction_fingerprint"]
                        and str(existing["posting_id"]) == requested["posting_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "applied",
                            "blockers": [],
                            "reused": True,
                            "correction": dict(existing),
                        }
                    conn.rollback()
                    return controlled_submission_ledger_correction_rejection(
                        requested,
                        ["controlled_ledger_correction_conflict"],
                    )

                posting = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE posting_id = ? LIMIT 1
                    """,
                    (requested["posting_id"],),
                ).fetchone()
                blockers: list[str] = []
                if posting is None:
                    blockers.append("controlled_ledger_correction_posting_missing")
                else:
                    if str(posting["status"]) != "applied":
                        blockers.append("controlled_ledger_correction_posting_changed")
                    if (
                        str(posting["posting_fingerprint"])
                        != requested["posting_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_posting_fingerprint_changed"
                        )
                    posting_entry_ids = sorted(
                        int(item)
                        for item in json_list(posting["ledger_entry_ids_json"])
                    )
                    if posting_entry_ids != sorted(
                        int(item) for item in requested["original_ledger_entry_ids"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_original_entry_ids_changed"
                        )
                    posting_fields = {
                        "account_truth_import_run_id": "account_truth_import_run_id",
                        "account_truth_file_fingerprint": (
                            "account_truth_file_fingerprint"
                        ),
                        "account_truth_source_fingerprint": (
                            "account_truth_source_fingerprint"
                        ),
                        "account_truth_review_fingerprint": (
                            "account_truth_review_fingerprint"
                        ),
                    }
                    for request_field, posting_field in posting_fields.items():
                        if str(requested.get(request_field) or "") != str(
                            posting[posting_field] or ""
                        ):
                            blockers.append(
                                f"controlled_ledger_correction_{request_field}_changed"
                            )

                import_row = conn.execute(
                    """
                    SELECT * FROM broker_import_runs
                    WHERE import_run_id = ? LIMIT 1
                    """,
                    (requested["account_truth_import_run_id"],),
                ).fetchone()
                if import_row is None:
                    blockers.append("controlled_ledger_correction_import_missing")
                else:
                    if str(import_row["validation_status"]) != "pass":
                        blockers.append("controlled_ledger_correction_import_not_pass")
                    if (
                        str(import_row["file_fingerprint"])
                        != requested["account_truth_file_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_correction_import_fingerprint_changed"
                        )
                review_identity = account_truth_review_identity_from_connection(
                    conn,
                    import_run_id=requested["account_truth_import_run_id"],
                )
                if (
                    review_identity["fingerprint"]
                    != requested["account_truth_review_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_account_truth_review_changed"
                    )

                ledger_rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM ledger_entries ORDER BY id ASC"
                    ).fetchall()
                ]
                ledger_identity = ledger_identity_from_rows(ledger_rows)
                if int(ledger_identity["ledger_cutoff_id"]) != int(
                    requested["pre_ledger_cutoff_id"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_pre_ledger_cutoff_changed"
                    )
                if (
                    str(ledger_identity["ledger_fingerprint"])
                    != requested["pre_ledger_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_pre_ledger_fingerprint_changed"
                    )
                current_valuation = build_current_valuation_snapshot(
                    self._valuation_facts,
                    persist=False,
                )
                valuation_fields = (
                    "snapshot_id",
                    "as_of",
                    "status",
                    "ledger_cutoff_id",
                    "ledger_fingerprint",
                )
                request_fields = {
                    "snapshot_id": "pre_valuation_snapshot_id",
                    "as_of": "pre_valuation_as_of",
                    "status": "pre_valuation_status",
                    "ledger_cutoff_id": "pre_ledger_cutoff_id",
                    "ledger_fingerprint": "pre_ledger_fingerprint",
                }
                for valuation_field in valuation_fields:
                    request_field = request_fields[valuation_field]
                    if str(current_valuation.get(valuation_field) or "") != str(
                        requested.get(request_field) or ""
                    ):
                        blockers.append(
                            "controlled_ledger_correction_pre_valuation_"
                            f"{valuation_field}_changed"
                        )

                original_ids = sorted(
                    int(item) for item in requested["original_ledger_entry_ids"]
                )
                original_rows = [
                    row
                    for row in ledger_rows
                    if int(row.get("id") or 0) in set(original_ids)
                ]
                if len(original_rows) != len(original_ids):
                    blockers.append(
                        "controlled_ledger_correction_original_entry_missing"
                    )
                if (
                    stable_json_fingerprint(original_rows)
                    != requested["original_ledger_entry_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_original_entry_changed"
                    )
                try:
                    derived_plan = build_controlled_ledger_correction_plan(
                        ledger_rows=ledger_rows,
                        original_entry_ids=original_ids,
                        posting_id=requested["posting_id"],
                    )
                except ValueError as exc:
                    blockers.append(str(exc))
                    derived_plan = {}
                if derived_plan != requested.get("correction_plan"):
                    blockers.append("controlled_ledger_correction_plan_changed")
                if (
                    correction_plan_fingerprint(derived_plan)
                    != requested["plan_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_correction_plan_fingerprint_changed"
                    )
                if blockers:
                    conn.rollback()
                    return controlled_submission_ledger_correction_rejection(
                        requested,
                        blockers,
                    )

                before = derived_plan["position_before"]
                after = derived_plan["position_after"]
                quantity_delta = Decimal(after["quantity"]) - Decimal(
                    before["quantity"]
                )
                correction_payload_json = _serialize_event_payload_json(derived_plan)
                cursor = conn.execute(
                    """
                    INSERT INTO ledger_entries (
                        entry_type, timestamp, amount, symbol, direction,
                        quantity, price, commission, correction_payload_json,
                        asset_class, note, source, source_ref, created_at
                    ) VALUES (?, ?, ?, ?, NULL, ?, NULL, 0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
                        normalize_timestamp(derived_plan["effective_at"]),
                        float(Decimal(derived_plan["cash_delta"])),
                        derived_plan["symbol"],
                        float(quantity_delta),
                        correction_payload_json,
                        derived_plan["asset_class"],
                        (
                            "Append-only correction derived from canonical replay; "
                            f"original posting {requested['posting_id']}."
                        ),
                        CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
                        requested["correction_id"],
                        requested["applied_at"],
                    ),
                )
                correction_entry_id = int(cursor.lastrowid or 0)
                stored_payload = dict(requested.get("payload") or {})
                stored_payload.update(
                    {
                        "correction_ledger_entry_id": correction_entry_id,
                        "post_ledger_cutoff_id": correction_entry_id,
                    }
                )
                insert_event_sync(
                    conn,
                    event_type="portfolio.ledger_entry.recorded",
                    timestamp=normalize_timestamp(derived_plan["effective_at"]),
                    entity_type="portfolio",
                    entity_id="default",
                    source="ledger_entries",
                    source_ref=str(correction_entry_id),
                    payload={
                        "entry_id": correction_entry_id,
                        "entry_type": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE,
                        "timestamp": normalize_timestamp(derived_plan["effective_at"]),
                        "symbol": derived_plan["symbol"],
                        "source": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
                        "source_ref": requested["correction_id"],
                        "correction_plan": derived_plan,
                    },
                )
                conn.execute(
                    """
                    INSERT INTO controlled_submission_ledger_corrections (
                        correction_id, correction_fingerprint, posting_id,
                        posting_fingerprint, original_ledger_entry_ids_json,
                        original_ledger_entry_fingerprint, reason_code,
                        account_truth_import_run_id,
                        account_truth_file_fingerprint,
                        account_truth_source_fingerprint,
                        account_truth_review_fingerprint,
                        pre_valuation_snapshot_id, pre_valuation_as_of,
                        pre_valuation_status, pre_ledger_cutoff_id,
                        pre_ledger_fingerprint, plan_fingerprint, operator_id,
                        operator_approval_id, status,
                        correction_ledger_entry_id, post_ledger_cutoff_id,
                        applied_at_epoch_ms, applied_at, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["correction_id"],
                        requested["correction_fingerprint"],
                        requested["posting_id"],
                        requested["posting_fingerprint"],
                        _serialize_event_payload_json(original_ids),
                        requested["original_ledger_entry_fingerprint"],
                        requested["reason_code"],
                        requested["account_truth_import_run_id"],
                        requested["account_truth_file_fingerprint"],
                        requested["account_truth_source_fingerprint"],
                        requested["account_truth_review_fingerprint"],
                        requested["pre_valuation_snapshot_id"],
                        requested["pre_valuation_as_of"],
                        requested["pre_valuation_status"],
                        int(requested["pre_ledger_cutoff_id"]),
                        requested["pre_ledger_fingerprint"],
                        requested["plan_fingerprint"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        correction_entry_id,
                        correction_entry_id,
                        int(requested["applied_at_epoch_ms"]),
                        requested["applied_at"],
                        _serialize_event_payload_json(stored_payload),
                        requested["applied_at"],
                    ),
                )
                insert_event_sync(
                    conn,
                    event_type="controlled_broker.ledger_corrected",
                    timestamp=requested["applied_at"],
                    entity_type="controlled_submission_ledger_correction",
                    entity_id=requested["correction_id"],
                    source=CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
                    source_ref=requested["posting_id"],
                    payload=stored_payload,
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_corrections
                    WHERE correction_id = ? LIMIT 1
                    """,
                    (requested["correction_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "applied",
                    "blockers": [],
                    "reused": False,
                    "correction": dict(saved) if saved is not None else {},
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
                return controlled_submission_ledger_correction_rejection(
                    requested,
                    ["controlled_ledger_correction_transaction_unavailable"],
                )

    def record_controlled_submission_ledger_posting_sync(
        self,
        *,
        posting: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify and atomically post exact cleared fills to the ledger once."""
        requested = dict(posting)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE posting_id = ? OR clearance_id = ?
                       OR submit_intent_id = ? OR order_id = ?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (
                        requested["posting_id"],
                        requested["clearance_id"],
                        requested["submit_intent_id"],
                        requested["order_id"],
                    ),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["posting_id"]) == requested["posting_id"]
                        and str(existing["posting_fingerprint"])
                        == requested["posting_fingerprint"]
                        and str(existing["clearance_id"]) == requested["clearance_id"]
                    ):
                        conn.commit()
                        return {
                            "status": "applied",
                            "blockers": [],
                            "reused": True,
                            "posting": dict(existing),
                        }
                    conn.rollback()
                    return controlled_submission_ledger_posting_rejection(
                        requested,
                        ["controlled_ledger_posting_conflict"],
                    )

                clearance = conn.execute(
                    """
                    SELECT * FROM controlled_submission_reconciliation_clearances
                    WHERE clearance_id = ? LIMIT 1
                    """,
                    (requested["clearance_id"],),
                ).fetchone()
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
                if clearance is None:
                    blockers.append("controlled_ledger_posting_clearance_missing")
                else:
                    clearance_fields = {
                        "clearance_fingerprint": "clearance_fingerprint",
                        "submit_intent_id": "submit_intent_id",
                        "order_id": "order_id",
                        "broker_order_id": "broker_order_id",
                        "terminal_status": "terminal_status",
                        "clearance_reconciliation_run_id": (
                            "clearance_reconciliation_run_id"
                        ),
                        "broker_evidence_fingerprint": ("broker_evidence_fingerprint"),
                        "account_truth_import_run_id": ("account_truth_import_run_id"),
                        "account_truth_file_fingerprint": (
                            "account_truth_file_fingerprint"
                        ),
                        "account_truth_source_fingerprint": (
                            "account_truth_source_fingerprint"
                        ),
                        "lifecycle_observation_id": "lifecycle_observation_id",
                        "lifecycle_evidence_fingerprint": (
                            "lifecycle_evidence_fingerprint"
                        ),
                        "lifecycle_source_sequence": "lifecycle_source_sequence",
                        "operator_id": "operator_id",
                    }
                    for request_field, clearance_field in clearance_fields.items():
                        if str(requested.get(request_field) or "") != str(
                            clearance[clearance_field] or ""
                        ):
                            blockers.append(
                                "controlled_ledger_posting_clearance_"
                                f"{request_field}_changed"
                            )
                    if str(clearance["status"]) != "cleared":
                        blockers.append(
                            "controlled_ledger_posting_clearance_not_cleared"
                        )
                if intent is None:
                    blockers.append("controlled_ledger_posting_intent_missing")
                else:
                    if str(intent["status"]) != "submitted":
                        blockers.append("controlled_ledger_posting_intent_changed")
                    if str(intent["order_id"]) != requested["order_id"]:
                        blockers.append(
                            "controlled_ledger_posting_intent_order_changed"
                        )
                    if str(intent["broker_order_id"]) != requested["broker_order_id"]:
                        blockers.append(
                            "controlled_ledger_posting_intent_broker_order_changed"
                        )
                    if str(intent["client_order_id"]) != requested["client_order_id"]:
                        blockers.append(
                            "controlled_ledger_posting_intent_client_order_changed"
                        )
                if order is None:
                    blockers.append("controlled_ledger_posting_order_missing")
                elif str(order["status"]) != requested["terminal_status"]:
                    blockers.append("controlled_ledger_posting_order_status_changed")
                if latest_item is None:
                    blockers.append("controlled_ledger_posting_reconciliation_missing")
                else:
                    if (
                        str(latest_item["run_id"])
                        != requested["clearance_reconciliation_run_id"]
                    ):
                        blockers.append(
                            "controlled_ledger_posting_reconciliation_superseded"
                        )
                    if str(latest_item["item_status"]) != (
                        "controlled_submission_reconciliation_cleared"
                    ):
                        blockers.append(
                            "controlled_ledger_posting_reconciliation_changed"
                        )

                invalidated = controlled_lifecycle_invalidated_clearance_rows(conn)
                if any(
                    str(item.get("order_id") or "") == requested["order_id"]
                    for item in invalidated
                ):
                    blockers.append(
                        "controlled_ledger_posting_lifecycle_clearance_invalidated"
                    )

                import_row = conn.execute(
                    """
                    SELECT * FROM broker_import_runs
                    WHERE import_run_id = ? LIMIT 1
                    """,
                    (requested["account_truth_import_run_id"],),
                ).fetchone()
                if import_row is None:
                    blockers.append("controlled_ledger_posting_import_missing")
                else:
                    if str(import_row["validation_status"]) != "pass":
                        blockers.append("controlled_ledger_posting_import_not_pass")
                    if (
                        str(import_row["file_fingerprint"])
                        != requested["account_truth_file_fingerprint"]
                    ):
                        blockers.append(
                            "controlled_ledger_posting_import_fingerprint_changed"
                        )
                review_identity = account_truth_review_identity_from_connection(
                    conn,
                    import_run_id=requested["account_truth_import_run_id"],
                )
                if (
                    review_identity["fingerprint"]
                    != requested["account_truth_review_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_account_truth_review_changed"
                    )

                from server.projections.valuation_snapshot import (
                    ledger_identity_from_rows,
                )

                ledger_rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM ledger_entries ORDER BY id ASC"
                    ).fetchall()
                ]
                ledger_identity = ledger_identity_from_rows(ledger_rows)
                if int(ledger_identity["ledger_cutoff_id"]) != int(
                    requested["pre_ledger_cutoff_id"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_pre_ledger_cutoff_changed"
                    )
                if (
                    str(ledger_identity["ledger_fingerprint"])
                    != requested["pre_ledger_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_pre_ledger_fingerprint_changed"
                    )

                entries = requested.get("ledger_entries")
                entries = entries if isinstance(entries, list) else []
                if len(entries) != int(requested["ledger_entry_count"]):
                    blockers.append("controlled_ledger_posting_entry_count_changed")
                if (
                    stable_json_fingerprint(entries)
                    != requested["ledger_entry_fingerprint"]
                ):
                    blockers.append(
                        "controlled_ledger_posting_entry_fingerprint_changed"
                    )
                clearance_fill_count = (
                    int(clearance["fill_count"]) if clearance is not None else -1
                )
                if len(entries) != clearance_fill_count:
                    blockers.append("controlled_ledger_posting_clearance_fill_changed")
                if requested["terminal_status"] == "filled" and not entries:
                    blockers.append("controlled_ledger_posting_filled_without_entries")

                verified_entries: list[dict[str, Any]] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        blockers.append("controlled_ledger_posting_entry_invalid")
                        continue
                    entry_blockers = verify_controlled_ledger_entry(
                        conn,
                        entry=entry,
                        request=requested,
                    )
                    blockers.extend(entry_blockers)
                    verified_entries.append(entry)
                if blockers:
                    conn.rollback()
                    return controlled_submission_ledger_posting_rejection(
                        requested,
                        blockers,
                    )

                ledger_entry_ids: list[int] = []
                for entry in verified_entries:
                    normalized_timestamp = normalize_timestamp(entry["timestamp"])
                    cursor = conn.execute(
                        """
                        INSERT INTO ledger_entries (
                            entry_type, timestamp, amount, symbol, direction,
                            quantity, price, commission, gross_amount,
                            net_cash_impact, fee_breakdown_json, fee_rule_id,
                            fee_rule_version, settlement_status, settled_at,
                            settlement_source, settlement_source_ref,
                            settlement_note, cost_basis_method, asset_class,
                            note, source, source_ref, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry["entry_type"],
                            normalized_timestamp,
                            float(Decimal(entry["amount"])),
                            entry["symbol"],
                            entry["direction"],
                            float(Decimal(entry["quantity"])),
                            float(Decimal(entry["price"])),
                            float(Decimal(entry["commission"])),
                            float(Decimal(entry["gross_amount"])),
                            float(Decimal(entry["net_cash_impact"])),
                            serialize_metadata_json(entry["fee_breakdown"]),
                            entry["fee_rule_id"],
                            entry["fee_rule_version"],
                            entry["settlement_status"],
                            normalize_timestamp(entry["settled_at"]),
                            entry["settlement_source"],
                            entry["settlement_source_ref"],
                            entry["settlement_note"],
                            entry["cost_basis_method"],
                            entry["asset_class"],
                            entry["note"],
                            entry["source"],
                            entry["source_ref"],
                            requested["applied_at"],
                        ),
                    )
                    entry_id = int(cursor.lastrowid or 0)
                    ledger_entry_ids.append(entry_id)
                    insert_event_sync(
                        conn,
                        event_type="portfolio.ledger_entry.recorded",
                        timestamp=normalized_timestamp,
                        entity_type="portfolio",
                        entity_id="default",
                        source="ledger_entries",
                        source_ref=str(entry_id),
                        payload={"entry_id": entry_id, **entry},
                    )

                post_cutoff_id = (
                    ledger_entry_ids[-1]
                    if ledger_entry_ids
                    else int(requested["pre_ledger_cutoff_id"])
                )
                stored_payload = dict(requested.get("payload") or {})
                stored_payload.update(
                    {
                        "ledger_entry_ids": ledger_entry_ids,
                        "post_ledger_cutoff_id": post_cutoff_id,
                    }
                )
                conn.execute(
                    """
                    INSERT INTO controlled_submission_ledger_postings (
                        posting_id, posting_fingerprint, clearance_id,
                        clearance_fingerprint, submit_intent_id, order_id,
                        broker_order_id, client_order_id, terminal_status,
                        clearance_reconciliation_run_id,
                        broker_evidence_fingerprint,
                        account_truth_import_run_id,
                        account_truth_file_fingerprint,
                        account_truth_source_fingerprint,
                        account_truth_review_fingerprint,
                        lifecycle_observation_id,
                        lifecycle_evidence_fingerprint,
                        lifecycle_source_sequence, pre_valuation_snapshot_id,
                        pre_valuation_as_of, pre_valuation_status,
                        pre_ledger_cutoff_id, pre_ledger_fingerprint,
                        operator_id, operator_approval_id, status,
                        ledger_entry_count, ledger_entry_fingerprint,
                        ledger_entry_ids_json, post_ledger_cutoff_id,
                        applied_at_epoch_ms, applied_at, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["posting_id"],
                        requested["posting_fingerprint"],
                        requested["clearance_id"],
                        requested["clearance_fingerprint"],
                        requested["submit_intent_id"],
                        requested["order_id"],
                        requested["broker_order_id"],
                        requested["client_order_id"],
                        requested["terminal_status"],
                        requested["clearance_reconciliation_run_id"],
                        requested["broker_evidence_fingerprint"],
                        requested["account_truth_import_run_id"],
                        requested["account_truth_file_fingerprint"],
                        requested["account_truth_source_fingerprint"],
                        requested["account_truth_review_fingerprint"],
                        requested["lifecycle_observation_id"],
                        requested["lifecycle_evidence_fingerprint"],
                        int(requested["lifecycle_source_sequence"]),
                        requested["pre_valuation_snapshot_id"],
                        requested["pre_valuation_as_of"],
                        requested["pre_valuation_status"],
                        int(requested["pre_ledger_cutoff_id"]),
                        requested["pre_ledger_fingerprint"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        len(ledger_entry_ids),
                        requested["ledger_entry_fingerprint"],
                        _serialize_event_payload_json(ledger_entry_ids),
                        post_cutoff_id,
                        int(requested["applied_at_epoch_ms"]),
                        requested["applied_at"],
                        _serialize_event_payload_json(stored_payload),
                        requested["applied_at"],
                    ),
                )
                insert_event_sync(
                    conn,
                    event_type="controlled_broker.ledger_posted",
                    timestamp=requested["applied_at"],
                    entity_type="controlled_submission_ledger_posting",
                    entity_id=requested["posting_id"],
                    source="controlled_submission_ledger_posting",
                    source_ref=requested["clearance_id"],
                    payload=stored_payload,
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_submission_ledger_postings
                    WHERE posting_id = ? LIMIT 1
                    """,
                    (requested["posting_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "applied",
                    "blockers": [],
                    "reused": False,
                    "posting": dict(saved) if saved is not None else {},
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
                return controlled_submission_ledger_posting_rejection(
                    requested,
                    ["controlled_ledger_posting_transaction_unavailable"],
                )

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
