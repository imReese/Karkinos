"""Read repository for persisted CITIC canonical-source resolutions."""

from __future__ import annotations

import sqlite3


class CiticSourceCanonicalResolutionReadRepositoryMixin:
    def get_latest(self) -> object | None:
        if not self._path.is_file():
            return None
        try:
            read_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(read_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                schema_state = self._schema_state(conn)
                if schema_state == "absent":
                    return None
                if schema_state != "complete":
                    raise self._read_rejection_type(
                        "citic_source_canonical_resolution_schema_incomplete"
                    )
                row = self._latest_row(conn)
                return self._resolution_from_row(row) if row is not None else None
        except self._read_rejection_type:
            raise
        except sqlite3.Error as exc:
            raise self._read_rejection_type(
                "citic_source_canonical_resolution_store_unreadable"
            ) from exc

    @staticmethod
    def _latest_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
        return conn.execute("""
            SELECT * FROM citic_source_canonical_resolutions
            ORDER BY id DESC
            LIMIT 1
            """).fetchone()
