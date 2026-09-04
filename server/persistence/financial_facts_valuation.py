"""Valuation snapshot persistence capability."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from server.persistence.database_serialization import (
    metadata_payload_value,
    serialize_metadata_json,
)
from server.valuation_snapshot_contract import validate_valuation_snapshot

logger = logging.getLogger("server.persistence.financial_facts")

VALUATION_PUBLICATION_CONTROL_KEY = "valuation_snapshot_publication"
VALUATION_PUBLICATION_ATTEMPT_CONTROL_KEY = "valuation_snapshot_publication_attempt"


def insert_valuation_snapshot_on_connection(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    """Insert or verify one immutable content-addressed valuation identity."""

    validate_valuation_snapshot(payload)

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


def _upsert_runtime_control_on_connection(
    conn: sqlite3.Connection,
    *,
    key: str,
    value: dict[str, Any],
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO runtime_controls (key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (key, serialize_metadata_json(value), updated_at),
    )


def _ready_publication_on_connection(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value_json FROM runtime_controls WHERE key = ? LIMIT 1",
        (VALUATION_PUBLICATION_CONTROL_KEY,),
    ).fetchone()
    if row is None:
        return None
    value = metadata_payload_value(row["value_json"])
    if (
        not isinstance(value, dict)
        or value.get("status") != "ready"
        or not str(value.get("snapshot_id") or "").strip()
    ):
        return None
    return value


def record_valuation_publication_failure_on_connection(
    conn: sqlite3.Connection,
    *,
    updated_at: str,
    reason: str,
    error_type: str | None = None,
    quote_fetch_run_id: str | None = None,
    quote_fetch_run_status: str | None = None,
) -> None:
    """Record a failed attempt without destroying a verified current publication.

    A failed candidate transaction has not committed new authoritative facts, so
    an existing ready publication remains the last-known-good read pointer.  If
    no ready publication exists, the legacy publication key still records the
    failure so financial reads remain fail closed.
    """

    failure: dict[str, Any] = {
        "status": "failed",
        "reason": reason,
    }
    if error_type:
        failure["error_type"] = error_type
    if quote_fetch_run_id:
        failure["quote_fetch_run_id"] = quote_fetch_run_id
    if quote_fetch_run_status:
        failure["quote_fetch_run_status"] = quote_fetch_run_status

    _upsert_runtime_control_on_connection(
        conn,
        key=VALUATION_PUBLICATION_ATTEMPT_CONTROL_KEY,
        value=failure,
        updated_at=updated_at,
    )
    if _ready_publication_on_connection(conn) is not None:
        return
    _upsert_runtime_control_on_connection(
        conn,
        key=VALUATION_PUBLICATION_CONTROL_KEY,
        value=failure,
        updated_at=updated_at,
    )


def publish_valuation_control_on_connection(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    updated_at: str,
    quote_fetch_run_id: str | None = None,
) -> None:
    """Publish the exact valuation identity inside the caller-owned transaction."""

    publication = {
        "status": "ready",
        "snapshot_id": payload["snapshot_id"],
        "valuation_snapshot_status": payload["status"],
        "as_of": payload["as_of"],
        "quote_fetch_run_id": quote_fetch_run_id,
    }
    _upsert_runtime_control_on_connection(
        conn,
        key=VALUATION_PUBLICATION_CONTROL_KEY,
        value=publication,
        updated_at=updated_at,
    )
    _upsert_runtime_control_on_connection(
        conn,
        key=VALUATION_PUBLICATION_ATTEMPT_CONTROL_KEY,
        value={**publication, "status": "success"},
        updated_at=updated_at,
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

    def publish_current_valuation_snapshot_sync(
        self,
        *,
        valuation_policy: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically publish the immutable snapshot for committed facts."""
        try:
            with sqlite3.connect(self._path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("BEGIN IMMEDIATE")
                snapshot = self._valuation_transaction_writer(
                    conn,
                    valuation_policy=valuation_policy,
                    now=now,
                )
                conn.commit()
        except Exception as exc:
            failure_at = self._now(timezone.utc).isoformat()
            try:
                with sqlite3.connect(self._path, timeout=2) as conn:
                    conn.row_factory = sqlite3.Row
                    conn.execute("BEGIN IMMEDIATE")
                    record_valuation_publication_failure_on_connection(
                        conn,
                        updated_at=failure_at,
                        reason="valuation_snapshot_publication_failed",
                        error_type=type(exc).__name__,
                    )
                    conn.commit()
            except Exception:
                logger.warning(
                    "Failed to record valuation publication attempt failure",
                    exc_info=True,
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
    "VALUATION_PUBLICATION_ATTEMPT_CONTROL_KEY",
    "VALUATION_PUBLICATION_CONTROL_KEY",
    "ValuationFactsRepositoryMixin",
    "insert_valuation_snapshot_on_connection",
    "publish_valuation_control_on_connection",
    "record_valuation_publication_failure_on_connection",
]
