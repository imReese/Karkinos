"""SQLite repository for persisted runtime control key/value state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class RuntimeControlRepository:
    """Own runtime-control persistence without interpreting control authority."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def set_value(self, key: str, value: dict[str, Any]) -> None:
        with sqlite3.connect(self._database_path) as conn:
            conn.execute(
                """
                INSERT INTO runtime_controls (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    json.dumps(value, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def get_value(self, key: str) -> dict[str, Any] | None:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value_json FROM runtime_controls WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["value_json"])
