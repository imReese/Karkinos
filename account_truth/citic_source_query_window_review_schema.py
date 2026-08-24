"""SQLite schema ownership for CITIC query-window reviews."""

from __future__ import annotations

import sqlite3


class CiticSourceQueryWindowReviewSchemaMixin:
    def _ensure_schema(self) -> None:
        if not self._path.is_file():
            raise self._rejection_type("citic_source_query_window_intake_missing")
        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                if self._schema_state(conn) == "incomplete":
                    raise self._rejection_type(
                        "citic_source_query_window_review_schema_incompatible"
                    )
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS citic_source_query_window_reviews (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        review_id TEXT NOT NULL UNIQUE,
                        schema_version TEXT NOT NULL,
                        intake_id TEXT NOT NULL,
                        file_fingerprint TEXT NOT NULL,
                        source_preview_fingerprint TEXT NOT NULL,
                        query_start_date TEXT NOT NULL,
                        query_end_date TEXT NOT NULL,
                        query_window_attested INTEGER NOT NULL CHECK(
                            query_window_attested = 1
                        ),
                        decision TEXT NOT NULL CHECK(
                            decision IN ('accepted', 'revoked')
                        ),
                        supersedes_review_id TEXT,
                        reviewer TEXT NOT NULL,
                        review_fingerprint TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(intake_id)
                            REFERENCES citic_source_intakes(intake_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_citic_query_window_latest
                    ON citic_source_query_window_reviews(intake_id, id DESC);
                """)
                if self._schema_state(conn) != "complete":
                    raise self._rejection_type(
                        "citic_source_query_window_review_schema_incompatible"
                    )
                conn.commit()
        except self._rejection_type:
            raise
        except sqlite3.DatabaseError as exc:
            raise self._rejection_type(
                "citic_source_query_window_review_store_unreadable"
            ) from exc

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        table_name = "citic_source_query_window_reviews"
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if table_name not in tables:
            return "absent"
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        required = {
            "id",
            "review_id",
            "schema_version",
            "intake_id",
            "file_fingerprint",
            "source_preview_fingerprint",
            "query_start_date",
            "query_end_date",
            "query_window_attested",
            "decision",
            "supersedes_review_id",
            "reviewer",
            "review_fingerprint",
            "created_at",
        }
        return "complete" if required.issubset(columns) else "incomplete"
