"""SQLite schema and migration ownership for CITIC source-scope reviews."""

from __future__ import annotations

import sqlite3


class CiticSourceScopeReviewSchemaMixin:
    def _ensure_schema(self) -> None:
        if not self._path.is_file():
            raise self._rejection_type("citic_source_scope_intake_missing")
        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                schema_state = self._schema_state(conn)
                if schema_state == "incomplete":
                    raise self._rejection_type(
                        "citic_source_scope_review_schema_incompatible"
                    )
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS citic_source_scope_reviews (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        review_id TEXT NOT NULL UNIQUE,
                        schema_version TEXT NOT NULL,
                        intake_id TEXT NOT NULL,
                        file_fingerprint TEXT NOT NULL,
                        source_preview_fingerprint TEXT NOT NULL,
                        query_window_review_id TEXT NOT NULL,
                        query_window_review_fingerprint TEXT NOT NULL,
                        account_alias TEXT NOT NULL,
                        account_reference_hash TEXT NOT NULL,
                        account_type TEXT NOT NULL,
                        market_scopes_json TEXT NOT NULL,
                        asset_classes_json TEXT NOT NULL,
                        account_value_band TEXT NOT NULL,
                        business_types_json TEXT NOT NULL,
                        no_other_filters_attested INTEGER NOT NULL CHECK(
                            no_other_filters_attested = 1
                        ),
                        complete_returned_results_attested INTEGER NOT NULL CHECK(
                            complete_returned_results_attested = 1
                        ),
                        source_scope_attested INTEGER NOT NULL CHECK(
                            source_scope_attested = 1
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

                    CREATE INDEX IF NOT EXISTS idx_citic_source_scope_latest
                    ON citic_source_scope_reviews(intake_id, id DESC);
                """)
                if schema_state == "legacy_v1":
                    conn.execute(
                        "ALTER TABLE citic_source_scope_reviews "
                        "ADD COLUMN account_value_band TEXT"
                    )
                if self._schema_state(conn) != "complete":
                    raise self._rejection_type(
                        "citic_source_scope_review_schema_incompatible"
                    )
                conn.commit()
        except self._rejection_type:
            raise
        except sqlite3.DatabaseError as exc:
            raise self._rejection_type(
                "citic_source_scope_review_store_unreadable"
            ) from exc

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        table_name = "citic_source_scope_reviews"
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
        required_v1 = {
            "id",
            "review_id",
            "schema_version",
            "intake_id",
            "file_fingerprint",
            "source_preview_fingerprint",
            "query_window_review_id",
            "query_window_review_fingerprint",
            "account_alias",
            "account_reference_hash",
            "account_type",
            "market_scopes_json",
            "asset_classes_json",
            "business_types_json",
            "no_other_filters_attested",
            "complete_returned_results_attested",
            "source_scope_attested",
            "decision",
            "supersedes_review_id",
            "reviewer",
            "review_fingerprint",
            "created_at",
        }
        if not required_v1.issubset(columns):
            return "incomplete"
        return "complete" if "account_value_band" in columns else "legacy_v1"
