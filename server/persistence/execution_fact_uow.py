"""Immutable standalone order/fill fact writers with exact replay semantics."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from server.persistence.database_serialization import (
    decimal_values_equal,
    serialize_metadata_json,
)
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_fact_event_payloads import (
    fill_event_payload,
    order_event_payload,
)


class ExecutionFactUnitOfWorkMixin:
    """Create immutable execution facts without overwrite-style upserts."""

    _path: Any
    _now: Any

    def record_order_sync(
        self,
        *,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        asset_class: str = "stock",
        intent_id: str | None = None,
        risk_decision_id: str | None = None,
        execution_mode: str = "paper",
        status: str = "submitted",
        source: str = "execution",
        source_ref: str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> int:
        """Create or exactly replay one immutable shared order fact."""
        now = self._now().isoformat()
        payload_json = serialize_metadata_json(payload) or "{}"
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if existing is not None:
                _require_order_replay(
                    existing,
                    timestamp=timestamp,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    asset_class=asset_class,
                    intent_id=intent_id,
                    risk_decision_id=risk_decision_id,
                    execution_mode=execution_mode,
                    status=status,
                    source=source,
                    source_ref=source_ref,
                    payload_json=payload_json,
                )
                conn.commit()
                return int(existing["id"])
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, timestamp, symbol, side, order_type, quantity, price,
                    asset_class, intent_id, risk_decision_id, execution_mode, status,
                    source, source_ref, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    order_type,
                    quantity,
                    price,
                    asset_class,
                    intent_id,
                    risk_decision_id,
                    execution_mode,
                    status,
                    source,
                    source_ref,
                    payload_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("order fact was not persisted")
            insert_event_sync(
                conn,
                event_type="order.recorded",
                timestamp=row["timestamp"],
                entity_type="order",
                entity_id=row["order_id"],
                source="orders",
                source_ref=row["order_id"],
                payload=order_event_payload(row),
            )
            conn.commit()
            return int(row["id"])

    def record_fill_sync(
        self,
        *,
        fill_id: str,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        fill_price: float,
        fill_quantity: float,
        commission: float = 0.0,
        slippage: float = 0.0,
        asset_class: str = "stock",
        execution_mode: str = "paper",
        provider_name: str | None = None,
        broker_order_id: str | None = None,
        source: str = "execution",
        source_ref: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> int:
        """Create or exactly replay one immutable paper/live fill fact."""
        now = self._now().isoformat()
        metadata_json = serialize_metadata_json(metadata)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM fills WHERE fill_id = ?",
                (fill_id,),
            ).fetchone()
            if existing is not None:
                _require_fill_replay(
                    existing,
                    order_id=order_id,
                    timestamp=timestamp,
                    symbol=symbol,
                    side=side,
                    fill_price=fill_price,
                    fill_quantity=fill_quantity,
                    commission=commission,
                    slippage=slippage,
                    asset_class=asset_class,
                    execution_mode=execution_mode,
                    provider_name=provider_name,
                    broker_order_id=broker_order_id,
                    source=source,
                    source_ref=source_ref,
                    metadata_json=metadata_json,
                )
                conn.commit()
                return int(existing["id"])
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
                    fill_id,
                    order_id,
                    timestamp,
                    symbol,
                    side,
                    fill_price,
                    fill_quantity,
                    commission,
                    slippage,
                    asset_class,
                    execution_mode,
                    provider_name,
                    broker_order_id,
                    source,
                    source_ref,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM fills WHERE fill_id = ?",
                (fill_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("fill fact was not persisted")
            insert_event_sync(
                conn,
                event_type="order.fill.recorded",
                timestamp=row["timestamp"],
                entity_type="fill",
                entity_id=row["fill_id"],
                source="fills",
                source_ref=row["fill_id"],
                payload=fill_event_payload(row),
            )
            conn.commit()
            return int(row["id"])


def _require_order_replay(
    row: sqlite3.Row,
    *,
    timestamp: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: float | None,
    asset_class: str,
    intent_id: str | None,
    risk_decision_id: str | None,
    execution_mode: str,
    status: str,
    source: str,
    source_ref: str | None,
    payload_json: str,
) -> None:
    fields = (
        (row["timestamp"], timestamp),
        (row["symbol"], symbol),
        (row["side"], side),
        (row["order_type"], order_type),
        (row["asset_class"], asset_class),
        (row["intent_id"], intent_id),
        (row["risk_decision_id"], risk_decision_id),
        (row["execution_mode"], execution_mode),
        (row["status"], status),
        (row["source"], source),
        (row["source_ref"], source_ref),
    )
    if any(str(actual or "") != str(expected or "") for actual, expected in fields):
        raise ValueError("order idempotency conflict: fact payload changed")
    if not decimal_values_equal(row["quantity"], quantity) or not (
        (row["price"] is None and price is None)
        or decimal_values_equal(row["price"], price)
    ):
        raise ValueError("order idempotency conflict: numeric fact changed")
    if not _serialized_values_equal(row["payload_json"], payload_json):
        raise ValueError("order idempotency conflict: evidence changed")


def _require_fill_replay(
    row: sqlite3.Row,
    *,
    order_id: str,
    timestamp: str,
    symbol: str,
    side: str,
    fill_price: float,
    fill_quantity: float,
    commission: float,
    slippage: float,
    asset_class: str,
    execution_mode: str,
    provider_name: str | None,
    broker_order_id: str | None,
    source: str,
    source_ref: str | None,
    metadata_json: str | None,
) -> None:
    fields = (
        (row["order_id"], order_id),
        (row["timestamp"], timestamp),
        (row["symbol"], symbol),
        (row["side"], side),
        (row["asset_class"], asset_class),
        (row["execution_mode"], execution_mode),
        (row["provider_name"], provider_name),
        (row["broker_order_id"], broker_order_id),
        (row["source"], source),
        (row["source_ref"], source_ref),
    )
    if any(str(actual or "") != str(expected or "") for actual, expected in fields):
        raise ValueError("fill idempotency conflict: fact payload changed")
    values = (
        (row["fill_price"], fill_price),
        (row["fill_quantity"], fill_quantity),
        (row["commission"], commission),
        (row["slippage"], slippage),
    )
    if any(not decimal_values_equal(actual, expected) for actual, expected in values):
        raise ValueError("fill idempotency conflict: numeric fact changed")
    if not _serialized_values_equal(row["metadata_json"], metadata_json):
        raise ValueError("fill idempotency conflict: evidence changed")


def _serialized_values_equal(left: Any, right: Any) -> bool:
    return _deserialize(left) == _deserialize(right)


def _deserialize(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


__all__ = ["ExecutionFactUnitOfWorkMixin"]
