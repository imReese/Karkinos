"""Atomic persistence for a complete paper-shadow simulation aggregate."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any

from server.contracts.content_identity import canonical_json
from server.contracts.paper_shadow import (
    PaperShadowFillFact,
    PaperShadowOrderFact,
    PaperShadowRunCommand,
)
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_fact_event_payloads import (
    fill_event_payload,
    order_event_payload,
)
from server.persistence.oms import (
    create_oms_order_in_transaction,
    transition_oms_order_in_transaction,
)

_COMMAND_TYPE = "paper_shadow_run.record"
_COMMAND_IDENTITY_KEY = "persistence_command_identity"


class PaperShadowRunUnitOfWorkMixin:
    """Write one simulation as a single immutable SQLite transaction."""

    _path: Any
    _now: Any

    def record_paper_shadow_run_sync(
        self,
        command: PaperShadowRunCommand,
    ) -> dict[str, Any]:
        now = self._now().isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            existing = _find_run(conn, command)
            if existing is not None:
                _require_exact_replay(conn, existing, command)
                conn.commit()
                return dict(existing)

            for order in command.orders:
                _insert_order_aggregate(conn, order, now=now)
            for fill in command.fills:
                _insert_fill(conn, fill, now=now)
            row = _insert_run(conn, command, now=now)
            conn.commit()
            return dict(row)


def _find_run(
    conn: sqlite3.Connection,
    command: PaperShadowRunCommand,
) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT * FROM paper_shadow_runs
        WHERE run_id = ? OR (plan_date = ? AND input_fingerprint = ?)
        ORDER BY CASE WHEN run_id = ? THEN 0 ELSE 1 END, id ASC
        LIMIT 1
        """,
        (
            command.run_id,
            command.plan_date,
            command.input_fingerprint,
            command.run_id,
        ),
    ).fetchone()
    if row is not None and str(row["run_id"]) != command.run_id:
        raise ValueError("paper-shadow idempotency conflict: run identity changed")
    return row


def _require_exact_replay(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    command: PaperShadowRunCommand,
) -> None:
    payload = _json_object(row["payload_json"])
    identity = payload.pop(_COMMAND_IDENTITY_KEY, None)
    if not isinstance(identity, dict):
        raise ValueError("paper-shadow idempotency conflict: command identity missing")
    if str(identity.get("command_type") or "") != _COMMAND_TYPE:
        raise ValueError("paper-shadow idempotency conflict: command type changed")
    if str(identity.get("idempotency_key") or "") != command.run_id:
        raise ValueError("paper-shadow idempotency conflict: command key changed")
    if str(identity.get("fingerprint") or "") != command.fingerprint:
        raise ValueError("paper-shadow idempotency conflict: command payload changed")

    payload.pop("review", None)
    row_fields = (
        (row["run_id"], command.run_id),
        (row["plan_date"], command.plan_date),
        (row["input_fingerprint"], command.input_fingerprint),
        (row["status"], command.status),
        (row["order_intent_count"], command.order_intent_count),
        (row["simulated_order_count"], command.simulated_order_count),
        (row["simulated_fill_count"], command.simulated_fill_count),
        (row["divergence_status"], command.divergence_status),
    )
    if any(str(actual) != str(expected) for actual, expected in row_fields):
        raise RuntimeError("paper-shadow replay found drifted run projection")
    if payload != command.payload:
        raise RuntimeError("paper-shadow replay found drifted run evidence")
    if _json_list(row["limitations_json"]) != list(command.limitations):
        raise RuntimeError("paper-shadow replay found drifted limitations")
    _require_order_facts(conn, command)
    _require_fill_facts(conn, command)


def _require_order_facts(
    conn: sqlite3.Connection,
    command: PaperShadowRunCommand,
) -> None:
    rows = conn.execute(
        "SELECT * FROM orders WHERE source = ? AND source_ref = ? ORDER BY order_id",
        ("paper_shadow_daily", command.run_id),
    ).fetchall()
    expected = {order.order_id: order for order in command.orders}
    if {str(row["order_id"]) for row in rows} != set(expected):
        raise RuntimeError("paper-shadow replay found drifted order membership")
    for row in rows:
        fact = expected[str(row["order_id"])]
        fields = (
            (row["timestamp"], fact.timestamp),
            (row["symbol"], fact.symbol),
            (row["side"], fact.side),
            (row["order_type"], fact.order_type),
            (row["asset_class"], fact.asset_class),
            (row["intent_id"], fact.intent_id),
            (row["risk_decision_id"], fact.risk_decision_id),
            (row["execution_mode"], fact.execution_mode),
            (row["status"], fact.status),
        )
        if any(str(actual or "") != str(value or "") for actual, value in fields):
            raise RuntimeError("paper-shadow replay found drifted order projection")
        if not _same_decimal(row["quantity"], fact.quantity) or not _same_decimal(
            row["price"], fact.price
        ):
            raise RuntimeError("paper-shadow replay found drifted order values")
        order_payload = _json_object(row["payload_json"])
        for key in (
            "run_id",
            "input_fingerprint",
            "order_intent_ref",
            "does_not_submit_broker_order",
            "does_not_mutate_production_ledger",
        ):
            if order_payload.get(key) != fact.payload.get(key):
                raise RuntimeError("paper-shadow replay found drifted order evidence")


def _require_fill_facts(
    conn: sqlite3.Connection,
    command: PaperShadowRunCommand,
) -> None:
    rows = conn.execute(
        "SELECT * FROM fills WHERE source = ? AND source_ref = ? ORDER BY fill_id",
        ("paper_shadow_daily", command.run_id),
    ).fetchall()
    expected = {fill.fill_id: fill for fill in command.fills}
    if {str(row["fill_id"]) for row in rows} != set(expected):
        raise RuntimeError("paper-shadow replay found drifted fill membership")
    for row in rows:
        fact = expected[str(row["fill_id"])]
        fields = (
            (row["order_id"], fact.order_id),
            (row["timestamp"], fact.timestamp),
            (row["symbol"], fact.symbol),
            (row["side"], fact.side),
            (row["asset_class"], fact.asset_class),
            (row["execution_mode"], fact.execution_mode),
            (row["provider_name"], fact.provider_name),
            (row["broker_order_id"], fact.broker_order_id),
        )
        if any(str(actual or "") != str(value or "") for actual, value in fields):
            raise RuntimeError("paper-shadow replay found drifted fill projection")
        values = (
            (row["fill_price"], fact.fill_price),
            (row["fill_quantity"], fact.fill_quantity),
            (row["commission"], fact.commission),
            (row["slippage"], fact.slippage),
        )
        if any(not _same_decimal(actual, value) for actual, value in values):
            raise RuntimeError("paper-shadow replay found drifted fill values")
        if _json_object(row["metadata_json"]) != fact.metadata:
            raise RuntimeError("paper-shadow replay found drifted fill evidence")


def _insert_order_aggregate(
    conn: sqlite3.Connection,
    fact: PaperShadowOrderFact,
    *,
    now: str,
) -> None:
    create_oms_order_in_transaction(conn, fact.oms_create, now=now)
    for transition in fact.oms_transitions:
        transition_oms_order_in_transaction(conn, transition, now=now)
    try:
        conn.execute(
            """
            INSERT INTO orders (
                order_id, timestamp, symbol, side, order_type, quantity, price,
                asset_class, intent_id, risk_decision_id, execution_mode, status,
                source, source_ref, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact.order_id,
                fact.timestamp,
                fact.symbol,
                fact.side,
                fact.order_type,
                fact.quantity,
                fact.price,
                fact.asset_class,
                fact.intent_id,
                fact.risk_decision_id,
                fact.execution_mode,
                fact.status,
                fact.source,
                fact.source_ref,
                canonical_json(fact.payload),
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("paper-shadow order identity already exists") from exc
    row = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?",
        (fact.order_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("paper-shadow order was not persisted")
    insert_event_sync(
        conn,
        event_type="order.recorded",
        timestamp=fact.timestamp,
        entity_type="order",
        entity_id=fact.order_id,
        source="orders",
        source_ref=fact.order_id,
        payload=order_event_payload(row),
    )


def _insert_fill(
    conn: sqlite3.Connection,
    fact: PaperShadowFillFact,
    *,
    now: str,
) -> None:
    try:
        conn.execute(
            """
            INSERT INTO fills (
                fill_id, order_id, timestamp, symbol, side, fill_price,
                fill_quantity, commission, slippage, asset_class,
                execution_mode, provider_name, broker_order_id, source,
                source_ref, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact.fill_id,
                fact.order_id,
                fact.timestamp,
                fact.symbol,
                fact.side,
                fact.fill_price,
                fact.fill_quantity,
                fact.commission,
                fact.slippage,
                fact.asset_class,
                fact.execution_mode,
                fact.provider_name,
                fact.broker_order_id,
                fact.source,
                fact.source_ref,
                canonical_json(fact.metadata),
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("paper-shadow fill identity already exists") from exc
    row = conn.execute(
        "SELECT * FROM fills WHERE fill_id = ?",
        (fact.fill_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("paper-shadow fill was not persisted")
    insert_event_sync(
        conn,
        event_type="order.fill.recorded",
        timestamp=fact.timestamp,
        entity_type="fill",
        entity_id=fact.fill_id,
        source="fills",
        source_ref=fact.fill_id,
        payload=fill_event_payload(row),
    )


def _insert_run(
    conn: sqlite3.Connection,
    command: PaperShadowRunCommand,
    *,
    now: str,
) -> sqlite3.Row:
    identity = {
        "command_type": _COMMAND_TYPE,
        "idempotency_key": command.run_id,
        "fingerprint": command.fingerprint,
    }
    payload = {**command.payload, _COMMAND_IDENTITY_KEY: identity}
    try:
        conn.execute(
            """
            INSERT INTO paper_shadow_runs (
                run_id, plan_date, input_fingerprint, status,
                order_intent_count, simulated_order_count, simulated_fill_count,
                divergence_status, next_manual_review_step, limitations_json,
                payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                command.run_id,
                command.plan_date,
                command.input_fingerprint,
                command.status,
                command.order_intent_count,
                command.simulated_order_count,
                command.simulated_fill_count,
                command.divergence_status,
                command.next_manual_review_step,
                canonical_json(list(command.limitations)),
                canonical_json(payload),
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("paper-shadow run identity already exists") from exc
    row = conn.execute(
        "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
        (command.run_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("paper-shadow run was not persisted")
    insert_event_sync(
        conn,
        event_type="paper_shadow_run.recorded",
        timestamp=now,
        entity_type="paper_shadow_run",
        entity_id=command.run_id,
        source="paper_shadow_runs",
        source_ref=command.run_id,
        payload={
            "run_id": command.run_id,
            "plan_date": command.plan_date,
            "input_fingerprint": command.input_fingerprint,
            "status": command.status,
            "simulated_order_count": command.simulated_order_count,
            "simulated_fill_count": command.simulated_fill_count,
            "command_identity": identity,
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        },
    )
    return row


def _same_decimal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


__all__ = ["PaperShadowRunUnitOfWorkMixin"]
