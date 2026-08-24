"""SQLite schema ownership for CITIC source intake reviews."""

from __future__ import annotations

import sqlite3


class CiticSourceIntakeSchemaMixin:
    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                    CREATE TABLE IF NOT EXISTS citic_source_intakes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        intake_id TEXT NOT NULL UNIQUE,
                        schema_version TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        file_fingerprint TEXT NOT NULL UNIQUE,
                        source_preview_fingerprint TEXT NOT NULL,
                        validation_status TEXT NOT NULL CHECK(validation_status = 'blocked'),
                        row_count INTEGER NOT NULL,
                        valid_row_count INTEGER NOT NULL,
                        invalid_row_count INTEGER NOT NULL,
                        duplicate_row_count INTEGER NOT NULL,
                        recognized_event_count INTEGER NOT NULL,
                        error_codes_json TEXT NOT NULL,
                        required_evidence_json TEXT NOT NULL,
                        limitations_json TEXT NOT NULL,
                        recordable_for_follow_up INTEGER NOT NULL CHECK(
                            recordable_for_follow_up IN (0, 1)
                        ),
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS citic_source_intake_reviews (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        review_id TEXT NOT NULL UNIQUE,
                        intake_id TEXT NOT NULL,
                        source_preview_fingerprint TEXT NOT NULL,
                        review_status TEXT NOT NULL CHECK(
                            review_status IN ('follow_up_required', 'rejected')
                        ),
                        reviewer TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(intake_id, review_status),
                        FOREIGN KEY(intake_id) REFERENCES citic_source_intakes(intake_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_citic_source_intakes_created
                    ON citic_source_intakes(created_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_citic_source_intake_reviews_latest
                    ON citic_source_intake_reviews(intake_id, id DESC);
                """)
            conn.commit()

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        required_tables = {
            "citic_source_intakes": {
                "id",
                "intake_id",
                "schema_version",
                "source_type",
                "file_fingerprint",
                "source_preview_fingerprint",
                "validation_status",
                "row_count",
                "valid_row_count",
                "invalid_row_count",
                "duplicate_row_count",
                "recognized_event_count",
                "error_codes_json",
                "required_evidence_json",
                "limitations_json",
                "recordable_for_follow_up",
                "created_at",
            },
            "citic_source_intake_reviews": {
                "id",
                "review_id",
                "intake_id",
                "source_preview_fingerprint",
                "review_status",
                "reviewer",
                "created_at",
            },
        }
        table_names = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        present = table_names.intersection(required_tables)
        if not present:
            return "absent"
        if present != set(required_tables):
            return "incomplete"
        for table_name, required_columns in required_tables.items():
            columns = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            if not required_columns.issubset(columns):
                return "incomplete"
        return "complete"
