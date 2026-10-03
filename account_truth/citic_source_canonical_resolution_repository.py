"""Read repository for persisted CITIC canonical-source resolutions."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import re
    from pathlib import Path
    from typing import Protocol

    from account_truth.citic_source_canonical_resolution import (
        CiticSourceCanonicalResolution,
        CiticSourceCanonicalResolutionReadRejected,
        CiticSourceCanonicalResolutionRejected,
    )

    class CiticSourceCanonicalResolutionRepositoryAccess(Protocol):
        """Dependencies supplied by the concrete repository to its persistence mixins."""

        def _ensure_schema(self) -> None: ...

        _evidence_fingerprint: re.Pattern[str]

        @staticmethod
        def _latest_row(conn: sqlite3.Connection) -> sqlite3.Row | None: ...

        _path: Path
        _read_rejection_type: type[CiticSourceCanonicalResolutionReadRejected]
        _rejection_type: type[CiticSourceCanonicalResolutionRejected]

        def _resolution_fingerprint(self, payload: object) -> str: ...

        def _resolution_from_row(
            self, row: sqlite3.Row
        ) -> CiticSourceCanonicalResolution: ...

        def _resolution_json(self, value: object) -> str: ...

        _resolution_type: type[CiticSourceCanonicalResolution]

        @staticmethod
        def _schema_state(conn: sqlite3.Connection) -> str: ...

        def _source_set_fingerprint(
            self, source_preview_fingerprints: list[str]
        ) -> str: ...

        def get_latest(self) -> CiticSourceCanonicalResolution | None: ...


class CiticSourceCanonicalResolutionReadRepositoryMixin:
    def get_latest(
        self: CiticSourceCanonicalResolutionRepositoryAccess,
    ) -> CiticSourceCanonicalResolution | None:
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
