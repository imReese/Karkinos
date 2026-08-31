"""Persistent idempotency claims shared by manual-ticket and OMS UoWs."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.content_identity import canonical_json


def get_order_state_command_claim(
    conn: sqlite3.Connection,
    command_key: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM order_state_command_claims
        WHERE command_key = ?
        LIMIT 1
        """,
        (command_key,),
    ).fetchone()


def require_matching_order_state_claim(
    claim: sqlite3.Row,
    *,
    command_type: str,
    command_key: str,
    command_fingerprint: str,
    aggregate_id: str,
) -> None:
    if str(claim["command_type"]) != command_type:
        raise ValueError("idempotency conflict: command type changed")
    if str(claim["command_key"]) != command_key:
        raise ValueError("idempotency conflict: command key changed")
    if str(claim["command_fingerprint"]) != command_fingerprint:
        raise ValueError("idempotency conflict: command payload fingerprint changed")
    if str(claim["aggregate_id"]) != aggregate_id:
        raise ValueError("idempotency conflict: aggregate identity changed")


def insert_order_state_command_claim(
    conn: sqlite3.Connection,
    *,
    command_type: str,
    command_key: str,
    command_fingerprint: str,
    aggregate_id: str,
    result: dict[str, Any],
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO order_state_command_claims (
            command_key, command_type, command_fingerprint,
            aggregate_id, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            command_key,
            command_type,
            command_fingerprint,
            aggregate_id,
            canonical_json(result),
            created_at,
        ),
    )


__all__ = [
    "get_order_state_command_claim",
    "insert_order_state_command_claim",
    "require_matching_order_state_claim",
]
