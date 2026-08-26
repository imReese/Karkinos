"""Valuation snapshot persistence capability."""

from __future__ import annotations

import sqlite3
from datetime import timezone
from typing import Any

from server.persistence.database_serialization import serialize_metadata_json


def insert_valuation_snapshot_on_connection(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    """Insert or verify one immutable content-addressed valuation identity."""

    quotes_json = serialize_metadata_json(payload.get("quotes") or [])
    metadata_json = serialize_metadata_json(payload.get("metadata") or {})
    existing = conn.execute(
        "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
        (payload["snapshot_id"],),
    ).fetchone()
    if existing is not None:
        expected = {
            "as_of": payload["as_of"],
            "trade_date": payload["trade_date"],
            "valuation_policy": payload["valuation_policy"],
            "ledger_cutoff_id": int(payload.get("ledger_cutoff_id") or 0),
            "ledger_fingerprint": payload["ledger_fingerprint"],
            "quote_set_fingerprint": payload["quote_set_fingerprint"],
            "status": payload["status"],
            "quotes_json": quotes_json,
            "metadata_json": metadata_json,
        }
        if any(existing[key] != value for key, value in expected.items()):
            raise ValueError("valuation snapshot identity conflict")
        return dict(existing)
    conn.execute(
        """
        INSERT INTO valuation_snapshots (
            snapshot_id, as_of, trade_date, valuation_policy,
            ledger_cutoff_id, ledger_fingerprint, quote_set_fingerprint,
            status, quotes_json, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["snapshot_id"],
            payload["as_of"],
            payload["trade_date"],
            payload["valuation_policy"],
            int(payload.get("ledger_cutoff_id") or 0),
            payload["ledger_fingerprint"],
            payload["quote_set_fingerprint"],
            payload["status"],
            quotes_json,
            metadata_json,
            created_at,
        ),
    )
    row = conn.execute(
        "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
        (payload["snapshot_id"],),
    ).fetchone()
    if row is None:
        raise RuntimeError("valuation snapshot persistence failed")
    return dict(row)


def publish_valuation_control_on_connection(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    updated_at: str,
    quote_fetch_run_id: str | None = None,
) -> None:
    """Publish the exact valuation identity inside the caller-owned transaction."""

    conn.execute(
        """
        INSERT INTO runtime_controls (key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (
            "valuation_snapshot_publication",
            serialize_metadata_json(
                {
                    "status": "ready",
                    "snapshot_id": payload["snapshot_id"],
                    "valuation_snapshot_status": payload["status"],
                    "as_of": payload["as_of"],
                    "quote_fetch_run_id": quote_fetch_run_id,
                }
            ),
            updated_at,
        ),
    )


class ValuationFactsRepositoryMixin:
    def save_valuation_snapshot_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable, content-addressed valuation snapshot."""
        now = self._now(timezone.utc).isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = insert_valuation_snapshot_on_connection(
                conn,
                payload,
                created_at=now,
            )
            conn.commit()
            return row

    def publish_current_valuation_snapshot_sync(self) -> dict[str, Any]:
        """Atomically publish the immutable snapshot for committed facts."""
        try:
            with sqlite3.connect(self._path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("BEGIN IMMEDIATE")
                snapshot = self._valuation_transaction_writer(conn)
                conn.commit()
        except Exception as exc:
            self._runtime_controls.set_value(
                "valuation_snapshot_publication",
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "reason": "valuation_snapshot_publication_failed",
                },
            )
            raise
        return snapshot

    def get_valuation_snapshot_sync(self, snapshot_id: str) -> dict[str, Any] | None:
        """Read one immutable valuation snapshot by content id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            return dict(row) if row else None


__all__ = [
    "ValuationFactsRepositoryMixin",
    "insert_valuation_snapshot_on_connection",
    "publish_valuation_control_on_connection",
]
