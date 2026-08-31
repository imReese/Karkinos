"""SQLite schema ownership for CITIC canonical-source resolutions."""

from __future__ import annotations

import sqlite3


class CiticSourceCanonicalResolutionSchemaMixin:
    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            schema_state = self._schema_state(conn)
            if schema_state == "partial":
                raise self._rejection_type(
                    "citic_source_canonical_resolution_schema_incompatible"
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS citic_source_canonical_resolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resolution_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    source_preview_fingerprints_json TEXT NOT NULL,
                    source_set_fingerprint TEXT NOT NULL,
                    scope_review_id TEXT NOT NULL,
                    scope_review_import_run_id TEXT NOT NULL,
                    scope_review_fingerprint TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('accepted', 'revoked')),
                    reviewer TEXT NOT NULL,
                    resolution_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
            conn.commit()

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("citic_source_canonical_resolutions",),
        ).fetchone()
        if row is None:
            return "absent"
        columns = {
            str(item[1])
            for item in conn.execute(
                "PRAGMA table_info(citic_source_canonical_resolutions)"
            ).fetchall()
        }
        required = {
            "id",
            "resolution_id",
            "schema_version",
            "source_preview_fingerprints_json",
            "source_set_fingerprint",
            "scope_review_id",
            "scope_review_import_run_id",
            "scope_review_fingerprint",
            "decision",
            "reviewer",
            "resolution_fingerprint",
            "created_at",
        }
        return "complete" if required.issubset(columns) else "partial"
