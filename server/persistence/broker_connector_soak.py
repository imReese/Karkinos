"""Persistence adapters for broker connector soak observations and sequences."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from server.persistence.event_log import insert_event_sync
from server.projections.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
    captured_after_state,
    source_contract_is_partial,
    source_sequence_evidence,
    source_sequence_has_invalid_source,
    strict_nonnegative_int,
    with_source_sequence,
)

SourceSequenceStateWriter = Callable[..., None]


class BrokerConnectorSoakObservationRepository:
    """Own idempotent event writes and the atomic source-sequence checkpoint."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def list(self, *, limit: int) -> list[dict[str, Any]]:
        return self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=limit,
        )

    def record(
        self,
        *,
        payload: dict[str, Any],
        observed_at: datetime,
        source_contract_required: bool,
        advance_state: SourceSequenceStateWriter,
    ) -> tuple[dict[str, Any], bool]:
        contract = payload.get("source_contract")
        if source_contract_required and isinstance(contract, dict) and contract:
            db_path = getattr(self._db, "_path", None)
            if db_path is None:
                payload = with_source_sequence(
                    payload,
                    evidence=source_sequence_evidence(
                        contract,
                        status="blocked",
                        expected_previous_cursor=None,
                        accepted=False,
                        state_advanced=False,
                    ),
                    blockers=["source_sequence_persistence_unavailable"],
                )
            else:
                return record_sequenced_soak_observation(
                    db_path=Path(db_path),
                    payload=payload,
                    observed_at=observed_at,
                    advance_state=advance_state,
                )
        observation_id = str(payload["observation_id"])
        existing = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return existing[0], True
        self._db.append_event_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            timestamp=observed_at.isoformat(),
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            source_ref=str(payload.get("connector_id") or observation_id),
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("broker connector soak observation was not recorded")
        return saved[0], False


def record_sequenced_soak_observation(
    *,
    db_path: Path,
    payload: dict[str, Any],
    observed_at: datetime,
    advance_state: SourceSequenceStateWriter,
) -> tuple[dict[str, Any], bool]:
    with sqlite3.connect(db_path, timeout=2) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 2000")
        conn.execute("BEGIN IMMEDIATE")
        ensure_source_sequence_schema(conn)
        evidence, sequence_blockers = evaluate_source_sequence(conn, payload)
        finalized = with_source_sequence(
            payload,
            evidence=evidence,
            blockers=sequence_blockers,
        )
        observation_id = str(finalized["observation_id"])
        existing = event_row(conn, observation_id=observation_id)
        if existing is not None:
            conn.commit()
            return dict(existing), True

        cursor = insert_event_sync(
            conn,
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            timestamp=observed_at.isoformat(),
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            source_ref=str(finalized.get("connector_id") or observation_id),
            payload=finalized,
        )
        if evidence["state_advanced"]:
            advance_state(
                conn,
                payload=finalized,
                evidence=evidence,
                observed_at=observed_at,
            )
        saved = conn.execute(
            "SELECT * FROM event_log WHERE id = ?",
            (int(cursor.lastrowid or 0),),
        ).fetchone()
        if saved is None:
            raise RuntimeError("broker connector soak observation was not recorded")
        conn.commit()
        return dict(saved), False


def evaluate_source_sequence(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    contract_value = payload.get("source_contract")
    contract = contract_value if isinstance(contract_value, dict) else {}
    connector_id = str(payload.get("connector_id") or "")
    deployment_identity = str(contract.get("deployment_identity") or "")
    batch_id = str(contract.get("batch_id") or "")
    cursor_previous = strict_nonnegative_int(contract.get("cursor_previous"))
    cursor_current = strict_nonnegative_int(contract.get("cursor_current"))
    state = conn.execute(
        """
        SELECT *
        FROM broker_connector_soak_sequence_state
        WHERE connector_id = ?
        """,
        (connector_id,),
    ).fetchone()
    expected_previous = int(state["last_cursor"]) if state is not None else 0
    blockers: list[str] = []
    status = "blocked"
    accepted = False
    state_advanced = False

    if cursor_previous is None or cursor_current is None:
        blockers.append("source_sequence_cursor_invalid")
    elif cursor_current <= 0 or cursor_current != cursor_previous + 1:
        blockers.append("source_sequence_cursor_not_consecutive")
    elif state is not None and str(state["deployment_identity"]) != (
        deployment_identity
    ):
        blockers.append("source_sequence_deployment_drift")
    else:
        prior = conn.execute(
            """
            SELECT *
            FROM broker_connector_soak_sequence_batches
            WHERE connector_id = ?
              AND deployment_identity = ?
              AND cursor_current = ?
            """,
            (connector_id, deployment_identity, cursor_current),
        ).fetchone()
        if prior is not None:
            if str(prior["batch_id"]) == batch_id and str(
                prior["snapshot_fingerprint"]
            ) == str(payload.get("snapshot_fingerprint") or ""):
                status = "replayed"
                accepted = True
            elif cursor_current < expected_previous:
                blockers.append("source_sequence_cursor_out_of_order")
            else:
                blockers.append("source_sequence_cursor_evidence_conflict")
        elif cursor_previous < expected_previous:
            blockers.append("source_sequence_cursor_out_of_order")
        elif cursor_previous > expected_previous:
            blockers.append("source_sequence_cursor_gap")
        else:
            reused_batch = conn.execute(
                """
                SELECT cursor_current
                FROM broker_connector_soak_sequence_batches
                WHERE connector_id = ?
                  AND deployment_identity = ?
                  AND batch_id = ?
                LIMIT 1
                """,
                (connector_id, deployment_identity, batch_id),
            ).fetchone()
            if reused_batch is not None:
                blockers.append("source_sequence_batch_reused")
            elif source_sequence_has_invalid_source(payload):
                if source_contract_is_partial(contract):
                    blockers.append("source_sequence_partial_batch")
                else:
                    blockers.append("source_sequence_source_invalid")
            elif state is not None and not captured_after_state(payload, state):
                blockers.append("source_sequence_time_out_of_order")
            else:
                status = "initial" if state is None else "advanced"
                accepted = True
                state_advanced = True

    return (
        source_sequence_evidence(
            contract,
            status=status,
            expected_previous_cursor=expected_previous,
            accepted=accepted,
            state_advanced=state_advanced,
        ),
        blockers,
    )


def advance_source_sequence_state(
    conn: sqlite3.Connection,
    *,
    payload: dict[str, Any],
    evidence: dict[str, Any],
    observed_at: datetime,
) -> None:
    connector_id = str(payload.get("connector_id") or "")
    deployment_identity = str(evidence["deployment_identity"])
    batch_id = str(evidence["batch_id"])
    cursor_previous = int(evidence["cursor_previous"])
    cursor_current = int(evidence["cursor_current"])
    snapshot_fingerprint = str(payload.get("snapshot_fingerprint") or "")
    captured_at = str(payload.get("source_captured_at") or "")
    observation_id = str(payload.get("observation_id") or "")
    conn.execute(
        """
        INSERT INTO broker_connector_soak_sequence_batches (
            connector_id, deployment_identity, cursor_previous,
            cursor_current, batch_id, snapshot_fingerprint,
            source_captured_at, observation_id, accepted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            connector_id,
            deployment_identity,
            cursor_previous,
            cursor_current,
            batch_id,
            snapshot_fingerprint,
            captured_at,
            observation_id,
            observed_at.isoformat(),
        ),
    )
    conn.execute(
        """
        INSERT INTO broker_connector_soak_sequence_state (
            connector_id, deployment_identity, last_cursor, last_batch_id,
            last_snapshot_fingerprint, last_source_captured_at,
            last_observation_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(connector_id) DO UPDATE SET
            deployment_identity = excluded.deployment_identity,
            last_cursor = excluded.last_cursor,
            last_batch_id = excluded.last_batch_id,
            last_snapshot_fingerprint = excluded.last_snapshot_fingerprint,
            last_source_captured_at = excluded.last_source_captured_at,
            last_observation_id = excluded.last_observation_id,
            updated_at = excluded.updated_at
        """,
        (
            connector_id,
            deployment_identity,
            cursor_current,
            batch_id,
            snapshot_fingerprint,
            captured_at,
            observation_id,
            observed_at.isoformat(),
        ),
    )


def ensure_source_sequence_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS broker_connector_soak_sequence_state (
            connector_id TEXT PRIMARY KEY,
            deployment_identity TEXT NOT NULL,
            last_cursor INTEGER NOT NULL CHECK(last_cursor > 0),
            last_batch_id TEXT NOT NULL,
            last_snapshot_fingerprint TEXT NOT NULL,
            last_source_captured_at TEXT NOT NULL,
            last_observation_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS broker_connector_soak_sequence_batches (
            connector_id TEXT NOT NULL,
            deployment_identity TEXT NOT NULL,
            cursor_previous INTEGER NOT NULL CHECK(cursor_previous >= 0),
            cursor_current INTEGER NOT NULL CHECK(cursor_current > 0),
            batch_id TEXT NOT NULL,
            snapshot_fingerprint TEXT NOT NULL,
            source_captured_at TEXT NOT NULL,
            observation_id TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            PRIMARY KEY(connector_id, deployment_identity, cursor_current),
            UNIQUE(connector_id, deployment_identity, batch_id)
        )
        """)


def event_row(conn: sqlite3.Connection, *, observation_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM event_log
        WHERE event_type = ?
          AND entity_type = ?
          AND entity_id = ?
          AND source = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            observation_id,
            BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        ),
    ).fetchone()


__all__ = [
    "BrokerConnectorSoakObservationRepository",
    "advance_source_sequence_state",
    "ensure_source_sequence_schema",
    "evaluate_source_sequence",
    "event_row",
    "record_sequenced_soak_observation",
]
