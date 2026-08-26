"""Explicit SQL fixtures for OMS facts that predate the command boundary."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.content_identity import canonical_json


def insert_historical_oms_order(
    database: Any,
    *,
    order_id: str,
    intent_key: str,
    symbol: str,
    side: str,
    asset_class: str,
    quantity: float,
    order_type: str,
    limit_price: float | None,
    status: str,
    source: str,
    source_ref: str | None = None,
    payload: dict[str, Any] | None = None,
    created_at: str = "2026-07-10T08:00:00+00:00",
) -> dict[str, Any]:
    """Seed an already-existing historical fact without a production write API."""

    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            INSERT INTO oms_orders (
                order_id, intent_key, symbol, side, asset_class, quantity,
                order_type, limit_price, status, broker_submission_enabled,
                source, source_ref, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                intent_key,
                symbol,
                side,
                asset_class,
                quantity,
                order_type,
                limit_price,
                status,
                source,
                source_ref,
                canonical_json(payload or {}),
                created_at,
                created_at,
            ),
        )
        conn.commit()
    order = database.get_oms_order_sync(order_id)
    if order is None:
        raise AssertionError(f"historical OMS fixture was not inserted: {order_id}")
    return order


__all__ = ["insert_historical_oms_order"]
