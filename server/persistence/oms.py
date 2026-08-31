"""SQLite repository for OMS orders and their append-only transitions."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any

from server.contracts.content_identity import canonical_json
from server.contracts.order_state import (
    OmsOrderCommand,
    OmsTransitionCommand,
    command_identity,
)
from server.persistence.connection import SQLiteRepository
from server.persistence.event_log import insert_event_sync
from server.persistence.order_state_claims import (
    get_order_state_command_claim,
    insert_order_state_command_claim,
    require_matching_order_state_claim,
)


class OmsRepository(SQLiteRepository):
    """Own OMS orders and their append-only transitions."""

    def create_oms_order_sync(self, command: OmsOrderCommand) -> dict[str, Any]:
        """Atomically create one immutable OMS order and initial transition."""
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            order = create_oms_order_in_transaction(
                conn,
                command,
                now=self._now().isoformat(),
            )
            conn.commit()
            return dict(order)

    def transition_oms_order_sync(
        self,
        command: OmsTransitionCommand,
    ) -> dict[str, Any]:
        """Atomically compare-and-set an OMS order and append its transition."""
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            updated = transition_oms_order_in_transaction(
                conn,
                command,
                now=self._now().isoformat(),
            )
            conn.commit()
            return dict(updated)

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one OMS order by its stable order ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_oms_order_by_intent_key_sync(
        self, intent_key: str
    ) -> dict[str, Any] | None:
        """Read one OMS order by its idempotency key."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE intent_key = ?",
                (intent_key,),
            ).fetchone()
            return dict(row) if row else None

    def list_oms_transitions_sync(self, order_id: str) -> list[dict[str, Any]]:
        """List OMS transitions for one order in chronological order."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM oms_transitions
                WHERE order_id = ?
                ORDER BY id ASC
                """,
                (order_id,),
            ).fetchall()
            return [dict(row) for row in rows]


def create_oms_order_in_transaction(
    conn: sqlite3.Connection,
    command: OmsOrderCommand,
    *,
    now: str,
) -> sqlite3.Row:
    """Apply one OMS creation command on the caller-owned transaction."""

    claim = get_order_state_command_claim(conn, command.idempotency_key)
    if claim is not None:
        require_matching_order_state_claim(
            claim,
            command_type="oms_order.create",
            command_key=command.idempotency_key,
            command_fingerprint=command.fingerprint,
            aggregate_id=command.order_id,
        )
        existing = _require_oms_order(conn, command.order_id)
        _require_oms_create_replay(conn, existing, command)
        return existing
    existing = conn.execute(
        "SELECT * FROM oms_orders WHERE intent_key = ? LIMIT 1",
        (command.idempotency_key,),
    ).fetchone()
    if existing is not None:
        raise ValueError("OMS idempotency conflict: order exists without command claim")
    collision = conn.execute(
        "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
        (command.order_id,),
    ).fetchone()
    if collision is not None:
        raise ValueError("OMS order idempotency conflict: order_id already exists")

    identity = command_identity(
        command_type="oms_order.create",
        idempotency_key=command.idempotency_key,
        fingerprint=command.fingerprint,
    )
    conn.execute(
        """
        INSERT INTO oms_orders (
            order_id, intent_key, symbol, side, asset_class, quantity,
            order_type, limit_price, status, broker_submission_enabled,
            source, source_ref, payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            command.order_id,
            command.idempotency_key,
            command.symbol,
            command.side.lower(),
            command.asset_class,
            float(command.quantity),
            command.order_type.lower(),
            command.limit_price,
            command.initial_status,
            1 if command.broker_submission_enabled else 0,
            command.source,
            command.source_ref,
            canonical_json({**command.payload, "command_identity": identity}),
            now,
            now,
        ),
    )
    cursor = conn.execute(
        """
        INSERT INTO oms_transitions (
            order_id, from_status, to_status, reason, actor,
            payload_json, transitioned_at, created_at
        ) VALUES (?, 'created', ?, ?, ?, ?, ?, ?)
        """,
        (
            command.order_id,
            command.initial_status,
            command.transition_reason,
            command.transition_actor,
            canonical_json(
                {**command.transition_payload, "command_identity": identity}
            ),
            now,
            now,
        ),
    )
    order = _require_oms_order(conn, command.order_id)
    transition = _require_oms_transition(
        conn,
        _required_lastrowid(cursor, entity="OMS initial transition"),
    )
    _insert_oms_event(
        conn,
        event_type="oms.order.created",
        timestamp=now,
        order=order,
        transition=transition,
        identity=identity,
    )
    insert_order_state_command_claim(
        conn,
        command_type="oms_order.create",
        command_key=command.idempotency_key,
        command_fingerprint=command.fingerprint,
        aggregate_id=command.order_id,
        result=dict(order),
        created_at=now,
    )
    return order


def transition_oms_order_in_transaction(
    conn: sqlite3.Connection,
    command: OmsTransitionCommand,
    *,
    now: str,
) -> sqlite3.Row:
    """Apply one OMS compare-and-set command on the caller-owned transaction."""

    claim = get_order_state_command_claim(conn, command.idempotency_key)
    if claim is not None:
        require_matching_order_state_claim(
            claim,
            command_type="oms_order.transition",
            command_key=command.idempotency_key,
            command_fingerprint=command.fingerprint,
            aggregate_id=command.order_id,
        )
        replay = _find_oms_transition_command(
            conn,
            order_id=command.order_id,
            idempotency_key=command.idempotency_key,
        )
        if replay is None:
            raise RuntimeError("OMS command claim is missing its transition")
        _require_oms_transition_replay(conn, replay, command)
        return _require_oms_order(conn, command.order_id)

    order = _require_oms_order(conn, command.order_id)
    if str(order["status"]) != command.expected_from:
        raise RuntimeError(
            "OMS transition compare-and-set conflict: "
            f"expected {command.expected_from}, got {order['status']}"
        )
    update = conn.execute(
        """
        UPDATE oms_orders
        SET status = ?, updated_at = ?
        WHERE order_id = ? AND status = ?
        """,
        (command.to_status, now, command.order_id, command.expected_from),
    )
    if update.rowcount != 1:
        raise RuntimeError("OMS transition compare-and-set failed")
    identity = command_identity(
        command_type="oms_order.transition",
        idempotency_key=command.idempotency_key,
        fingerprint=command.fingerprint,
    )
    cursor = conn.execute(
        """
        INSERT INTO oms_transitions (
            order_id, from_status, to_status, reason, actor,
            payload_json, transitioned_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            command.order_id,
            command.expected_from,
            command.to_status,
            command.reason,
            command.actor,
            canonical_json({**command.payload, "command_identity": identity}),
            now,
            now,
        ),
    )
    updated = _require_oms_order(conn, command.order_id)
    transition = _require_oms_transition(
        conn,
        _required_lastrowid(cursor, entity="OMS transition"),
    )
    _insert_oms_event(
        conn,
        event_type="oms.order.transitioned",
        timestamp=now,
        order=updated,
        transition=transition,
        identity=identity,
    )
    insert_order_state_command_claim(
        conn,
        command_type="oms_order.transition",
        command_key=command.idempotency_key,
        command_fingerprint=command.fingerprint,
        aggregate_id=command.order_id,
        result=dict(updated),
        created_at=now,
    )
    return updated


def _require_oms_create_replay(
    conn: sqlite3.Connection,
    existing: sqlite3.Row,
    command: OmsOrderCommand,
) -> None:
    payload = _json_object(existing["payload_json"])
    _require_command_identity(payload.get("command_identity"), command)
    base_payload = dict(payload)
    base_payload.pop("command_identity", None)
    fields = (
        (existing["order_id"], command.order_id),
        (existing["intent_key"], command.idempotency_key),
        (existing["symbol"], command.symbol),
        (existing["side"], command.side.lower()),
        (existing["asset_class"], command.asset_class),
        (existing["order_type"], command.order_type.lower()),
        (existing["source"], command.source),
        (existing["source_ref"], command.source_ref),
    )
    if any(str(actual or "") != str(expected or "") for actual, expected in fields):
        raise RuntimeError("OMS create replay found drifted order projection")
    if not _same_decimal(existing["quantity"], command.quantity) or not _same_decimal(
        existing["limit_price"], command.limit_price
    ):
        raise RuntimeError("OMS create replay found drifted order values")
    if bool(existing["broker_submission_enabled"]) != (
        command.broker_submission_enabled
    ):
        raise RuntimeError("OMS create replay found drifted broker authority")
    if base_payload != command.payload:
        raise RuntimeError("OMS create replay found drifted payload")
    initial = _find_oms_transition_command(
        conn,
        order_id=command.order_id,
        idempotency_key=command.idempotency_key,
    )
    if initial is None:
        raise RuntimeError("OMS create replay is missing its initial transition")
    _require_command_identity(
        _json_object(initial["payload_json"]).get("command_identity"),
        command,
    )
    initial_payload = _json_object(initial["payload_json"])
    initial_payload.pop("command_identity", None)
    initial_fields = (
        (initial["order_id"], command.order_id),
        (initial["from_status"], "created"),
        (initial["to_status"], command.initial_status),
        (initial["reason"], command.transition_reason),
        (initial["actor"], command.transition_actor),
    )
    if (
        any(
            str(actual or "") != str(expected or "")
            for actual, expected in initial_fields
        )
        or initial_payload != command.transition_payload
    ):
        raise RuntimeError("OMS create replay found drifted initial transition")
    _require_oms_event_command(
        conn,
        event_type="oms.order.created",
        order_id=command.order_id,
        command=command,
    )


def _find_oms_transition_command(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    idempotency_key: str,
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT * FROM oms_transitions
        WHERE order_id = ?
        ORDER BY id DESC
        """,
        (order_id,),
    ).fetchall()
    for row in rows:
        identity = _json_object(row["payload_json"]).get("command_identity")
        if isinstance(identity, dict) and identity.get("idempotency_key") == (
            idempotency_key
        ):
            return row
    return None


def _require_oms_transition_replay(
    conn: sqlite3.Connection,
    transition: sqlite3.Row,
    command: OmsTransitionCommand,
) -> None:
    payload = _json_object(transition["payload_json"])
    _require_command_identity(payload.get("command_identity"), command)
    payload.pop("command_identity", None)
    fields = (
        (transition["order_id"], command.order_id),
        (transition["from_status"], command.expected_from),
        (transition["to_status"], command.to_status),
        (transition["reason"], command.reason),
        (transition["actor"], command.actor),
    )
    if (
        any(str(actual or "") != str(expected or "") for actual, expected in fields)
        or payload != command.payload
    ):
        raise RuntimeError("OMS transition replay found drifted transition fact")
    _require_oms_event_command(
        conn,
        event_type="oms.order.transitioned",
        order_id=command.order_id,
        command=command,
    )


def _require_oms_event_command(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    order_id: str,
    command: OmsOrderCommand | OmsTransitionCommand,
) -> None:
    rows = conn.execute(
        """
        SELECT payload_json FROM event_log
        WHERE event_type = ? AND source = 'oms_orders' AND source_ref = ?
        ORDER BY id DESC
        """,
        (event_type, order_id),
    ).fetchall()
    for row in rows:
        identity = _json_object(row["payload_json"]).get("command_identity")
        if isinstance(identity, dict) and identity.get("idempotency_key") == (
            command.idempotency_key
        ):
            _require_command_identity(identity, command)
            return
    raise RuntimeError("OMS command claim is missing its audit event")


def _require_command_identity(identity: Any, command: Any) -> None:
    if not isinstance(identity, dict):
        raise ValueError("OMS idempotency conflict: command identity is missing")
    if str(identity.get("idempotency_key") or "") != command.idempotency_key:
        raise ValueError("OMS idempotency conflict: command key changed")
    if str(identity.get("fingerprint") or "") != command.fingerprint:
        raise ValueError("OMS idempotency conflict: command payload changed")


def _insert_oms_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    timestamp: str,
    order: sqlite3.Row,
    transition: sqlite3.Row,
    identity: dict[str, Any],
) -> None:
    insert_event_sync(
        conn,
        event_type=event_type,
        timestamp=timestamp,
        entity_type="oms_order",
        entity_id=str(order["order_id"]),
        source="oms_orders",
        source_ref=str(order["order_id"]),
        payload={
            "order_id": order["order_id"],
            "intent_key": order["intent_key"],
            "symbol": order["symbol"],
            "side": order["side"],
            "asset_class": order["asset_class"],
            "quantity": order["quantity"],
            "order_type": order["order_type"],
            "limit_price": order["limit_price"],
            "status": order["status"],
            "broker_submission_enabled": bool(order["broker_submission_enabled"]),
            "source": order["source"],
            "source_ref": order["source_ref"],
            "transition": {
                "id": transition["id"],
                "from_status": transition["from_status"],
                "to_status": transition["to_status"],
                "reason": transition["reason"],
                "actor": transition["actor"],
            },
            "command_identity": identity,
        },
    )


def _require_oms_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
        (order_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"OMS order not found: {order_id}")
    return row


def _require_oms_transition(
    conn: sqlite3.Connection,
    transition_id: int,
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM oms_transitions WHERE id = ? LIMIT 1",
        (transition_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("OMS transition was not persisted")
    return row


def _required_lastrowid(cursor: sqlite3.Cursor, *, entity: str) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError(f"{entity} did not return a row id")
    return row_id


def _same_decimal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
