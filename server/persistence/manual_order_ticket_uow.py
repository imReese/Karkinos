"""Atomic manual-ticket projection and lifecycle writes."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from server.contracts.content_identity import canonical_json
from server.contracts.order_state import (
    ManualOrderStateCommand,
    ManualOrderTicketCommand,
    command_identity,
)
from server.persistence.connection import DateTimeNow
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_fact_event_payloads import (
    action_task_event_payload,
    manual_order_event_payload,
    order_event_payload,
)
from server.persistence.order_state_claims import (
    get_order_state_command_claim,
    insert_order_state_command_claim,
    require_matching_order_state_claim,
)

_ACTION_COLUMNS = """
    id, source_signal_id, symbol, title, detail, direction, urgency,
    target_weight, price, strategy_id, timestamp, asset_class, status,
    created_at, updated_at
"""


class ManualOrderTicketUnitOfWorkMixin:
    """Persist every manual-ticket projection through one SQLite transaction."""

    _path: Path
    _now: DateTimeNow

    def create_manual_order_ticket_sync(
        self,
        command: ManualOrderTicketCommand,
    ) -> dict[str, Any]:
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            claim = get_order_state_command_claim(conn, command.idempotency_key)
            if claim is not None:
                require_matching_order_state_claim(
                    claim,
                    command_type="manual_order_ticket.create",
                    command_key=command.idempotency_key,
                    command_fingerprint=command.fingerprint,
                    aggregate_id=command.order_id,
                )
                replay_existing = _require_manual_order(conn, command.order_id)
                result = _replay_manual_ticket(conn, command, replay_existing)
                conn.commit()
                return result
            existing = _manual_order(conn, command.order_id)
            if existing is not None:
                raise ValueError(
                    "idempotency conflict: manual order exists without command claim"
                )
            if _order(conn, command.order_id) is not None:
                raise ValueError(
                    "idempotency conflict: shared order exists without command claim"
                )

            action: sqlite3.Row | None = None
            if command.action_id is not None:
                action = conn.execute(
                    f"SELECT {_ACTION_COLUMNS} FROM action_tasks WHERE id = ? LIMIT 1",
                    (command.action_id,),
                ).fetchone()
                if action is None:
                    raise KeyError(f"action task not found: {command.action_id}")
                if str(action["status"]) != command.expected_action_status:
                    raise RuntimeError(
                        "manual ticket action compare-and-set conflict: "
                        f"expected {command.expected_action_status}, "
                        f"got {action['status']}"
                    )
                _require_action_matches_command(action, command)
            else:
                _require_risk_decision_matches_command(conn, command)

            now = self._now().isoformat()
            identity = command_identity(
                command_type="manual_order_ticket.create",
                idempotency_key=command.idempotency_key,
                fingerprint=command.fingerprint,
            )
            stored_payload = {**command.payload, "command_identity": identity}
            payload_json = canonical_json(stored_payload)

            conn.execute(
                """
                INSERT INTO manual_orders (
                    order_id, timestamp, symbol, side, order_type, quantity, price,
                    intent_id, risk_decision_id, execution_mode, status, payload_json,
                    note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    command.order_id,
                    command.timestamp,
                    command.symbol,
                    command.side.lower(),
                    command.order_type.lower(),
                    float(command.quantity),
                    command.price,
                    command.intent_id,
                    command.risk_decision_id,
                    command.execution_mode,
                    command.status,
                    payload_json,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, timestamp, symbol, side, order_type, quantity, price,
                    asset_class, intent_id, risk_decision_id, execution_mode, status,
                    source, source_ref, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command.order_id,
                    command.timestamp,
                    command.symbol,
                    command.side.lower(),
                    command.order_type.lower(),
                    float(command.quantity),
                    command.price,
                    command.asset_class,
                    command.intent_id,
                    command.risk_decision_id,
                    command.execution_mode,
                    command.status,
                    command.source,
                    command.source_ref,
                    payload_json,
                    now,
                    now,
                ),
            )
            if command.action_id is not None:
                action_update = conn.execute(
                    """
                    UPDATE action_tasks
                    SET status = 'pending_manual_confirmation', updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (now, command.action_id, command.expected_action_status),
                )
                if action_update.rowcount != 1:
                    raise RuntimeError("manual ticket action compare-and-set failed")

            manual = _require_manual_order(conn, command.order_id)
            order = _require_order(conn, command.order_id)
            updated_action = (
                _require_action(conn, command.action_id)
                if command.action_id is not None
                else None
            )
            _insert_manual_event(
                conn,
                row=manual,
                event_type="order.submitted",
                timestamp=command.timestamp,
                identity=identity,
            )
            _insert_order_event(
                conn,
                row=order,
                event_type="order.recorded",
                timestamp=command.timestamp,
                identity=identity,
            )
            if updated_action is not None:
                _insert_action_event(
                    conn,
                    row=updated_action,
                    timestamp=now,
                    identity=identity,
                )
            insert_order_state_command_claim(
                conn,
                command_type="manual_order_ticket.create",
                command_key=command.idempotency_key,
                command_fingerprint=command.fingerprint,
                aggregate_id=command.order_id,
                result=dict(manual),
                created_at=now,
            )
            conn.commit()
            return dict(manual)

    def transition_manual_order_sync(
        self,
        command: ManualOrderStateCommand,
    ) -> dict[str, Any]:
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            claim = get_order_state_command_claim(conn, command.idempotency_key)
            if claim is not None:
                require_matching_order_state_claim(
                    claim,
                    command_type="manual_order_ticket.transition",
                    command_key=command.idempotency_key,
                    command_fingerprint=command.fingerprint,
                    aggregate_id=command.order_id,
                )
                replay = _replay_manual_transition(conn, command)
                conn.commit()
                return replay

            manual = _manual_order(conn, command.order_id)
            if manual is None:
                raise KeyError(f"manual order not found: {command.order_id}")
            order = _order(conn, command.order_id)
            if order is None:
                raise RuntimeError(
                    "manual order is missing its shared order projection"
                )
            _require_expected_status(manual, command.expected_from, projection="manual")
            _require_expected_status(order, command.expected_from, projection="shared")
            if command.action_id is not None:
                action = _require_action(conn, command.action_id)
                if str(action["status"]) != command.expected_action_status:
                    raise RuntimeError(
                        "manual order action compare-and-set conflict: "
                        f"expected {command.expected_action_status}, got {action['status']}"
                    )

            now = self._now().isoformat()
            manual_update = conn.execute(
                """
                UPDATE manual_orders
                SET status = ?, note = ?, updated_at = ?
                WHERE order_id = ? AND status = ?
                """,
                (
                    command.to_status,
                    command.note,
                    now,
                    command.order_id,
                    command.expected_from,
                ),
            )
            order_update = conn.execute(
                """
                UPDATE orders
                SET status = ?, updated_at = ?
                WHERE order_id = ? AND status = ?
                """,
                (
                    command.to_status,
                    now,
                    command.order_id,
                    command.expected_from,
                ),
            )
            if manual_update.rowcount != 1 or order_update.rowcount != 1:
                raise RuntimeError("manual order compare-and-set failed")
            if command.action_id is not None:
                action_update = conn.execute(
                    """
                    UPDATE action_tasks
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        command.action_to_status,
                        now,
                        command.action_id,
                        command.expected_action_status,
                    ),
                )
                if action_update.rowcount != 1:
                    raise RuntimeError("manual order action compare-and-set failed")

            identity = command_identity(
                command_type="manual_order_ticket.transition",
                idempotency_key=command.idempotency_key,
                fingerprint=command.fingerprint,
            )
            updated_manual = _require_manual_order(conn, command.order_id)
            updated_order = _require_order(conn, command.order_id)
            _insert_manual_event(
                conn,
                row=updated_manual,
                event_type="order.status_changed",
                timestamp=now,
                identity=identity,
            )
            _insert_order_event(
                conn,
                row=updated_order,
                event_type="order.status_changed",
                timestamp=now,
                identity=identity,
                note=command.note,
            )
            if command.action_id is not None:
                _insert_action_event(
                    conn,
                    row=_require_action(conn, command.action_id),
                    timestamp=now,
                    identity=identity,
                )
            insert_order_state_command_claim(
                conn,
                command_type="manual_order_ticket.transition",
                command_key=command.idempotency_key,
                command_fingerprint=command.fingerprint,
                aggregate_id=command.order_id,
                result=dict(updated_manual),
                created_at=now,
            )
            conn.commit()
            return dict(updated_manual)


def _replay_manual_ticket(
    conn: sqlite3.Connection,
    command: ManualOrderTicketCommand,
    manual: sqlite3.Row,
) -> dict[str, Any]:
    payload = _json_object(manual["payload_json"])
    _require_same_identity(payload.get("command_identity"), command)
    order = _require_order(conn, command.order_id)
    _require_manual_projection_matches(manual, order, command, payload)
    expected_events = [
        ("manual_orders", command.order_id),
        ("orders", command.order_id),
    ]
    if command.action_id is not None:
        expected_events.append(("action_tasks", str(command.action_id)))
    else:
        _require_risk_decision_matches_command(conn, command)
    for source, source_ref in expected_events:
        identity = _find_event_identity(
            conn,
            source=source,
            source_ref=source_ref,
            idempotency_key=command.idempotency_key,
        )
        if identity is None:
            raise RuntimeError("manual ticket command claim is missing an audit event")
        _require_same_identity(identity, command)
    return dict(manual)


def _replay_manual_transition(
    conn: sqlite3.Connection,
    command: ManualOrderStateCommand,
) -> dict[str, Any]:
    expected_events = [
        ("manual_orders", command.order_id),
        ("orders", command.order_id),
    ]
    if command.action_id is not None:
        expected_events.append(("action_tasks", str(command.action_id)))
    for source, source_ref in expected_events:
        identity = _find_event_identity(
            conn,
            source=source,
            source_ref=source_ref,
            idempotency_key=command.idempotency_key,
        )
        if identity is None:
            raise RuntimeError("manual order command claim is missing an audit event")
        _require_same_identity(identity, command)
    manual = _require_manual_order(conn, command.order_id)
    order = _require_order(conn, command.order_id)
    if str(manual["status"]) != command.to_status or str(order["status"]) != (
        command.to_status
    ):
        raise RuntimeError("manual order replay found drifted projections")
    if command.action_id is not None:
        action = _require_action(conn, command.action_id)
        if str(action["status"]) != command.action_to_status:
            raise RuntimeError("manual order replay found drifted action projection")
    return dict(manual)


def _require_same_identity(identity: Any, command: Any) -> None:
    if not isinstance(identity, dict):
        raise ValueError("idempotency conflict: persisted command identity is missing")
    if str(identity.get("idempotency_key") or "") != command.idempotency_key:
        raise ValueError("idempotency conflict: command key does not match")
    if str(identity.get("fingerprint") or "") != command.fingerprint:
        raise ValueError("idempotency conflict: command payload fingerprint changed")


def _require_action_matches_command(
    action: sqlite3.Row,
    command: ManualOrderTicketCommand,
) -> None:
    if str(action["symbol"]) != command.symbol:
        raise RuntimeError("manual ticket action symbol changed")
    if str(action["direction"]).lower() != command.side.lower():
        raise RuntimeError("manual ticket action side changed")
    if str(action["asset_class"]) != command.asset_class:
        raise RuntimeError("manual ticket action asset class changed")


def _require_risk_decision_matches_command(
    conn: sqlite3.Connection,
    command: ManualOrderTicketCommand,
) -> None:
    row = conn.execute(
        """
        SELECT decision_id, intent_id, passed, symbol, side, resulting_order_id
        FROM risk_decisions
        WHERE decision_id = ?
        LIMIT 1
        """,
        (command.risk_decision_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"risk decision not found: {command.risk_decision_id}")
    checks = (
        (row["decision_id"], command.risk_decision_id),
        (row["intent_id"], command.intent_id),
        (row["symbol"], command.symbol),
        (str(row["side"]).lower(), command.side.lower()),
        (row["resulting_order_id"], command.order_id),
    )
    if int(row["passed"] or 0) != 1 or any(
        str(actual or "") != str(expected or "") for actual, expected in checks
    ):
        raise RuntimeError("runtime manual ticket risk decision binding changed")


def _require_manual_projection_matches(
    manual: sqlite3.Row,
    order: sqlite3.Row,
    command: ManualOrderTicketCommand,
    payload: dict[str, Any],
) -> None:
    order_payload = _json_object(order["payload_json"])
    _require_same_identity(order_payload.get("command_identity"), command)
    checks = (
        (manual["timestamp"], command.timestamp),
        (manual["symbol"], command.symbol),
        (manual["side"], command.side.lower()),
        (manual["order_type"], command.order_type.lower()),
        (manual["execution_mode"], command.execution_mode),
        (manual["intent_id"], command.intent_id),
        (manual["risk_decision_id"], command.risk_decision_id),
        (order["timestamp"], command.timestamp),
        (order["symbol"], command.symbol),
        (order["side"], command.side.lower()),
        (order["order_type"], command.order_type.lower()),
        (order["execution_mode"], command.execution_mode),
        (order["intent_id"], command.intent_id),
        (order["risk_decision_id"], command.risk_decision_id),
        (order["asset_class"], command.asset_class),
        (order["source"], command.source),
        (order["source_ref"], command.source_ref),
    )
    if any(str(actual or "") != str(expected or "") for actual, expected in checks):
        raise RuntimeError("manual ticket replay found drifted order projections")
    if str(manual["status"]) != str(order["status"]):
        raise RuntimeError("manual ticket replay found drifted order statuses")
    values = (
        (manual["quantity"], command.quantity),
        (manual["price"], command.price),
        (order["quantity"], command.quantity),
        (order["price"], command.price),
    )
    if any(not _same_decimal(actual, expected) for actual, expected in values):
        raise RuntimeError("manual ticket replay found drifted order values")
    base_payload = dict(payload)
    base_payload.pop("command_identity", None)
    shared_payload = dict(order_payload)
    shared_payload.pop("command_identity", None)
    if base_payload != command.payload or shared_payload != command.payload:
        raise RuntimeError("manual ticket replay found drifted payload")


def _same_decimal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _find_event_identity(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_ref: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT payload_json FROM event_log
        WHERE source = ? AND source_ref = ?
        ORDER BY id DESC
        """,
        (source, source_ref),
    ).fetchall()
    for row in rows:
        identity = _json_object(row["payload_json"]).get("command_identity")
        if isinstance(identity, dict) and identity.get("idempotency_key") == (
            idempotency_key
        ):
            return identity
    return None


def _insert_manual_event(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    event_type: str,
    timestamp: str,
    identity: dict[str, Any],
) -> None:
    insert_event_sync(
        conn,
        event_type=event_type,
        timestamp=timestamp,
        entity_type="order",
        entity_id=str(row["order_id"]),
        source="manual_orders",
        source_ref=str(row["order_id"]),
        payload={**manual_order_event_payload(row), "command_identity": identity},
    )


def _insert_order_event(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    event_type: str,
    timestamp: str,
    identity: dict[str, Any],
    note: str | None = None,
) -> None:
    payload = {**order_event_payload(row), "command_identity": identity}
    if note is not None:
        payload["note"] = note
    insert_event_sync(
        conn,
        event_type=event_type,
        timestamp=timestamp,
        entity_type="order",
        entity_id=str(row["order_id"]),
        source="orders",
        source_ref=str(row["order_id"]),
        payload=payload,
    )


def _insert_action_event(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    timestamp: str,
    identity: dict[str, Any],
) -> None:
    insert_event_sync(
        conn,
        event_type="task.action.status_changed",
        timestamp=timestamp,
        entity_type="action_task",
        entity_id=str(row["id"]),
        source="action_tasks",
        source_ref=str(row["id"]),
        payload={**action_task_event_payload(row), "command_identity": identity},
    )


def _require_expected_status(
    row: sqlite3.Row,
    expected: str,
    *,
    projection: str,
) -> None:
    if str(row["status"]) != expected:
        raise RuntimeError(
            f"{projection} order compare-and-set conflict: "
            f"expected {expected}, got {row['status']}"
        )


def _manual_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM manual_orders WHERE order_id = ? LIMIT 1",
        (order_id,),
    ).fetchone()


def _order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM orders WHERE order_id = ? LIMIT 1",
        (order_id,),
    ).fetchone()


def _require_manual_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = _manual_order(conn, order_id)
    if row is None:
        raise KeyError(f"manual order not found: {order_id}")
    return row


def _require_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = _order(conn, order_id)
    if row is None:
        raise RuntimeError("manual order is missing its shared order projection")
    return row


def _require_action(conn: sqlite3.Connection, action_id: int) -> sqlite3.Row:
    row = conn.execute(
        f"SELECT {_ACTION_COLUMNS} FROM action_tasks WHERE id = ? LIMIT 1",
        (action_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"action task not found: {action_id}")
    return row


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["ManualOrderTicketUnitOfWorkMixin"]
