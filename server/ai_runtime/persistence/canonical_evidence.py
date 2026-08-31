"""SQLite adapter for immutable canonical AI evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

CANONICAL_EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_canonical_evidence (
    reference_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    valuation_snapshot_id TEXT NOT NULL,
    ledger_cutoff_id INTEGER NOT NULL CHECK(ledger_cutoff_id >= 0),
    ledger_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    as_of TEXT NOT NULL,
    source_schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    record_fingerprint TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    persisted_facts_only INTEGER NOT NULL CHECK(persisted_facts_only = 1)
);

CREATE INDEX IF NOT EXISTS idx_ai_canonical_evidence_identity
ON ai_canonical_evidence(
    valuation_snapshot_id,
    ledger_cutoff_id,
    ledger_fingerprint,
    tool_name
);
"""


class CanonicalEvidenceSqliteRepository:
    """Own connections and SQL for ``ai_canonical_evidence``."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.executescript(CANONICAL_EVIDENCE_SCHEMA)

    def persist(self, values: Mapping[str, Any]) -> dict[str, Any] | None:
        """Insert once; return the existing row when the identity was present."""
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT * FROM ai_canonical_evidence WHERE reference_id = ?",
                (values["reference_id"],),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            conn.execute(
                """
                INSERT INTO ai_canonical_evidence (
                    reference_id, tool_name, kind, valuation_snapshot_id,
                    ledger_cutoff_id, ledger_fingerprint, status, as_of,
                    source_schema_version, payload_json, payload_fingerprint,
                    record_fingerprint, captured_at, persisted_facts_only
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    values["reference_id"],
                    values["tool_name"],
                    values["kind"],
                    values["valuation_snapshot_id"],
                    values["ledger_cutoff_id"],
                    values["ledger_fingerprint"],
                    values["status"],
                    values["as_of"],
                    values["source_schema_version"],
                    values["payload_json"],
                    values["payload_fingerprint"],
                    values["record_fingerprint"],
                    values["captured_at"],
                ),
            )
        return None

    def get(self, reference_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_canonical_evidence WHERE reference_id = ?",
                (reference_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_for_identity(
        self,
        *,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
    ) -> tuple[dict[str, Any], ...]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_canonical_evidence
                WHERE valuation_snapshot_id = ?
                  AND ledger_cutoff_id = ?
                  AND ledger_fingerprint = ?
                ORDER BY tool_name, reference_id
                """,
                (
                    valuation_snapshot_id,
                    ledger_cutoff_id,
                    ledger_fingerprint,
                ),
            ).fetchall()
        return tuple(dict(row) for row in rows)
