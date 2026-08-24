"""SQLite repository for immutable and superseded daily strategy artifacts."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from server.contracts.content_identity import canonical_json
from server.contracts.daily_strategy_artifacts import DailyStrategyArtifactRejected
from server.persistence.daily_strategy_backups import DailyStrategyBackupStore
from server.projections.daily_strategy_artifacts import selection_from_record


class DailyStrategyArtifactRepository:
    """Own the transactional identity and replacement boundary in SQLite."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        backup_store: DailyStrategyBackupStore,
    ) -> None:
        self._db_path = Path(db_path)
        self._backups = backup_store

    def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ai_shadow_research_daily_selections (
                    selection_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    winner_candidate_id TEXT,
                    expected_candidate_count INTEGER NOT NULL,
                    observed_candidate_count INTEGER NOT NULL,
                    selection_json TEXT NOT NULL,
                    selection_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_daily_backups (
                    backup_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    selection_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    artifact_fingerprint TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_superseded_daily_selections (
                    selection_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    winner_candidate_id TEXT,
                    expected_candidate_count INTEGER NOT NULL,
                    observed_candidate_count INTEGER NOT NULL,
                    selection_json TEXT NOT NULL,
                    selection_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    superseded_by_run_id TEXT NOT NULL,
                    superseded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_superseded_daily_backups (
                    backup_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL,
                    selection_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    artifact_fingerprint TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    superseded_by_run_id TEXT NOT NULL,
                    superseded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_daily_selection_date
                    ON ai_shadow_research_daily_selections(market_date DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_daily_backup_date
                    ON ai_shadow_research_daily_backups(market_date DESC);
            """)

    def record(
        self,
        *,
        selection: Mapping[str, Any],
        receipt: Mapping[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        """Atomically persist or idempotently replay one selection/receipt pair."""

        with sqlite3.connect(self._db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing_selection = conn.execute(
                "SELECT * FROM ai_shadow_research_daily_selections WHERE run_id=?",
                (selection["run_id"],),
            ).fetchone()
            existing_backup = conn.execute(
                "SELECT * FROM ai_shadow_research_daily_backups WHERE run_id=?",
                (selection["run_id"],),
            ).fetchone()
            if existing_selection is not None or existing_backup is not None:
                if (
                    existing_selection is None
                    or existing_backup is None
                    or existing_selection["selection_fingerprint"]
                    != selection["selection_fingerprint"]
                    or existing_backup["artifact_fingerprint"]
                    != receipt["artifact_fingerprint"]
                ):
                    raise DailyStrategyArtifactRejected("daily_artifact_conflict")
                return {
                    "selection_record": dict(existing_selection),
                    "backup_record": dict(existing_backup),
                    "reused": True,
                }
            self._supersede_authorized_market_date_artifacts(
                conn,
                replacement_selection=selection,
                superseded_at=created_at,
            )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_daily_selections
                (selection_id, run_id, market_date, status, winner_candidate_id,
                 expected_candidate_count, observed_candidate_count, selection_json,
                 selection_fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selection["selection_id"],
                    selection["run_id"],
                    selection["market_date"],
                    selection["status"],
                    selection["winner_candidate_id"],
                    selection["expected_candidate_count"],
                    selection["observed_candidate_count"],
                    canonical_json(selection),
                    selection["selection_fingerprint"],
                    created_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_daily_backups
                (backup_id, run_id, market_date, selection_id, relative_path,
                 artifact_fingerprint, byte_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt["backup_id"],
                    selection["run_id"],
                    selection["market_date"],
                    selection["selection_id"],
                    receipt["relative_path"],
                    receipt["artifact_fingerprint"],
                    receipt["byte_count"],
                    created_at,
                ),
            )
        return {
            "selection_record": dict(selection),
            "backup_record": dict(receipt),
            "reused": False,
        }

    def list_selection_records(
        self, *, limit: int = 20, superseded: bool = False
    ) -> list[dict[str, Any]]:
        query = (
            """
            SELECT * FROM ai_shadow_research_superseded_daily_selections
            ORDER BY market_date DESC, superseded_at DESC LIMIT ?
            """
            if superseded
            else """
            SELECT * FROM ai_shadow_research_daily_selections
            ORDER BY market_date DESC LIMIT ?
            """
        )
        return self._list_records(query=query, limit=limit)

    def list_backup_records(
        self, *, limit: int = 20, superseded: bool = False
    ) -> list[dict[str, Any]]:
        query = (
            """
            SELECT * FROM ai_shadow_research_superseded_daily_backups
            ORDER BY market_date DESC, superseded_at DESC LIMIT ?
            """
            if superseded
            else """
            SELECT * FROM ai_shadow_research_daily_backups
            ORDER BY market_date DESC LIMIT ?
            """
        )
        return self._list_records(query=query, limit=limit)

    def current_pair(
        self, *, run_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            with self._connect_readonly() as conn:
                selection = conn.execute(
                    "SELECT * FROM ai_shadow_research_daily_selections WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                backup = conn.execute(
                    "SELECT * FROM ai_shadow_research_daily_backups WHERE run_id=?",
                    (run_id,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None, None
        return (
            dict(selection) if selection is not None else None,
            dict(backup) if backup is not None else None,
        )

    def backup_record(self, *, run_id: str) -> dict[str, Any] | None:
        try:
            with self._connect_readonly() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_shadow_research_daily_backups WHERE run_id=?",
                    (run_id,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        return dict(row) if row is not None else None

    def _supersede_authorized_market_date_artifacts(
        self,
        conn: sqlite3.Connection,
        *,
        replacement_selection: Mapping[str, Any],
        superseded_at: str,
    ) -> None:
        market_date = str(replacement_selection.get("market_date") or "")
        replacement_run_id = str(replacement_selection.get("run_id") or "")
        existing_selection = conn.execute(
            "SELECT * FROM ai_shadow_research_daily_selections WHERE market_date=?",
            (market_date,),
        ).fetchone()
        if existing_selection is None:
            return
        try:
            authorization = conn.execute(
                """
                SELECT authorization.completed_run_id,
                       authorization.completed_selection_fingerprint,
                       consumption.consumed_rearm_evidence_fingerprint
                FROM ai_shadow_research_corrected_panel_rearm_consumptions
                     AS consumption
                JOIN ai_shadow_research_corrected_panel_rearm_authorizations
                     AS authorization
                  ON authorization.authorization_id=consumption.authorization_id
                WHERE consumption.replacement_run_id=?
                  AND authorization.market_date=?
                """,
                (replacement_run_id, market_date),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise DailyStrategyArtifactRejected(
                "daily_artifact_market_date_conflict"
            ) from exc
        if (
            authorization is None
            or existing_selection["run_id"] != authorization["completed_run_id"]
            or existing_selection["selection_fingerprint"]
            != authorization["completed_selection_fingerprint"]
            or not str(authorization["consumed_rearm_evidence_fingerprint"] or "")
        ):
            raise DailyStrategyArtifactRejected("daily_artifact_market_date_conflict")
        if (
            selection_from_record(dict(existing_selection)).get("integrity_status")
            != "verified"
        ):
            raise DailyStrategyArtifactRejected(
                "superseded_daily_selection_fingerprint_mismatch"
            )
        existing_backup = conn.execute(
            """
            SELECT * FROM ai_shadow_research_daily_backups
            WHERE run_id=? AND market_date=?
            """,
            (existing_selection["run_id"], market_date),
        ).fetchone()
        if (
            existing_backup is None
            or self._backups.project_receipt(dict(existing_backup)).get(
                "verification_status"
            )
            != "verified"
        ):
            raise DailyStrategyArtifactRejected("superseded_daily_backup_not_verified")
        self._archive_current_pair(
            conn,
            selection=existing_selection,
            backup=existing_backup,
            replacement_run_id=replacement_run_id,
            superseded_at=superseded_at,
        )

    @staticmethod
    def _archive_current_pair(
        conn: sqlite3.Connection,
        *,
        selection: sqlite3.Row,
        backup: sqlite3.Row,
        replacement_run_id: str,
        superseded_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ai_shadow_research_superseded_daily_selections
            (selection_id, run_id, market_date, status, winner_candidate_id,
             expected_candidate_count, observed_candidate_count, selection_json,
             selection_fingerprint, created_at, superseded_by_run_id,
             superseded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                selection["selection_id"],
                selection["run_id"],
                selection["market_date"],
                selection["status"],
                selection["winner_candidate_id"],
                selection["expected_candidate_count"],
                selection["observed_candidate_count"],
                selection["selection_json"],
                selection["selection_fingerprint"],
                selection["created_at"],
                replacement_run_id,
                superseded_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_superseded_daily_backups
            (backup_id, run_id, market_date, selection_id, relative_path,
             artifact_fingerprint, byte_count, created_at,
             superseded_by_run_id, superseded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                backup["backup_id"],
                backup["run_id"],
                backup["market_date"],
                backup["selection_id"],
                backup["relative_path"],
                backup["artifact_fingerprint"],
                backup["byte_count"],
                backup["created_at"],
                replacement_run_id,
                superseded_at,
            ),
        )
        conn.execute(
            "DELETE FROM ai_shadow_research_daily_backups WHERE run_id=?",
            (selection["run_id"],),
        )
        conn.execute(
            "DELETE FROM ai_shadow_research_daily_selections WHERE run_id=?",
            (selection["run_id"],),
        )

    def _list_records(self, *, query: str, limit: int) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(query, (limit,)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self._db_path.exists():
            raise sqlite3.OperationalError("daily artifact store is not initialized")
        conn = sqlite3.connect(
            f"file:{self._db_path.resolve()}?mode=ro", uri=True, timeout=30
        )
        conn.row_factory = sqlite3.Row
        return conn


__all__ = ["DailyStrategyArtifactRepository"]
