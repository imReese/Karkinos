"""Manual review persistence for account-truth reconciliation items."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

MANUAL_REVIEW_SCHEMA_VERSION = "karkinos.account_truth.manual_review.v3"
MANUAL_REVIEW_STATUSES = (
    "accepted",
    "ignored",
    "known_difference",
    "ledger_candidate",
    "needs_investigation",
)

ManualReviewStatus = Literal[
    "accepted",
    "ignored",
    "known_difference",
    "ledger_candidate",
    "needs_investigation",
]


@dataclass(frozen=True)
class ManualReviewDecision:
    id: int
    import_run_id: str
    item_key: str
    category: str
    symbol: str
    review_status: ManualReviewStatus
    note: str
    reviewer: str
    evidence_fingerprint: str
    schema_version: str
    created_at: str
    updated_at: str


class ManualReviewRepository:
    """Persist human review decisions for reconciliation items."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def record_decision(
        self,
        *,
        import_run_id: str,
        item_key: str,
        category: str,
        review_status: str,
        symbol: str = "",
        note: str = "",
        reviewer: str = "local",
        evidence_fingerprint: str = "",
    ) -> ManualReviewDecision:
        if review_status not in MANUAL_REVIEW_STATUSES:
            raise ValueError(f"unsupported manual review status: {review_status}")

        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM reconciliation_review_decisions
                WHERE import_run_id = ?
                  AND item_key = ?
                LIMIT 1
                """,
                (import_run_id, item_key),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO reconciliation_review_decisions (
                    import_run_id, item_key, category, symbol, review_status,
                    note, reviewer, evidence_fingerprint, schema_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(import_run_id, item_key) DO UPDATE SET
                    category = excluded.category,
                    symbol = excluded.symbol,
                    review_status = excluded.review_status,
                    note = excluded.note,
                    reviewer = excluded.reviewer,
                    evidence_fingerprint = excluded.evidence_fingerprint,
                    schema_version = excluded.schema_version,
                    updated_at = excluded.updated_at
                """,
                (
                    import_run_id,
                    item_key,
                    category,
                    symbol,
                    review_status,
                    note,
                    reviewer,
                    evidence_fingerprint,
                    MANUAL_REVIEW_SCHEMA_VERSION,
                    created_at,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO reconciliation_review_history (
                    import_run_id, item_key, category, symbol, review_status,
                    note, reviewer, evidence_fingerprint, schema_version,
                    created_at, updated_at, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_run_id,
                    item_key,
                    category,
                    symbol,
                    review_status,
                    note,
                    reviewer,
                    evidence_fingerprint,
                    MANUAL_REVIEW_SCHEMA_VERSION,
                    created_at,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT *
                FROM reconciliation_review_decisions
                WHERE import_run_id = ?
                  AND item_key = ?
                LIMIT 1
                """,
                (import_run_id, item_key),
            ).fetchone()
        if row is None:
            raise RuntimeError("manual review decision was not persisted")
        return _decision_from_row(row)

    def list_decisions(self, import_run_id: str) -> list[ManualReviewDecision]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM reconciliation_review_decisions
                WHERE import_run_id = ?
                ORDER BY id ASC
                """,
                (import_run_id,),
            ).fetchall()
        return [_decision_from_row(row) for row in rows]

    def list_decision_history(
        self,
        import_run_id: str,
        *,
        item_key: str | None = None,
    ) -> list[ManualReviewDecision]:
        query = """
            SELECT history_id AS id, import_run_id, item_key, category, symbol,
                   review_status, note, reviewer, evidence_fingerprint,
                   schema_version, created_at, updated_at
            FROM reconciliation_review_history
            WHERE import_run_id = ?
        """
        params: list[str] = [import_run_id]
        if item_key is not None:
            query += " AND item_key = ?"
            params.append(item_key)
        query += " ORDER BY history_id ASC"
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_decision_from_row(row) for row in rows]

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS reconciliation_review_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_run_id TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    symbol TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    reviewer TEXT NOT NULL DEFAULT 'local',
                    evidence_fingerprint TEXT NOT NULL DEFAULT '',
                    schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(import_run_id, item_key)
                );

                CREATE INDEX IF NOT EXISTS idx_reconciliation_review_import_run
                    ON reconciliation_review_decisions(import_run_id);

                CREATE INDEX IF NOT EXISTS idx_reconciliation_review_status
                    ON reconciliation_review_decisions(review_status);

                CREATE TABLE IF NOT EXISTS reconciliation_review_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_run_id TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    symbol TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    reviewer TEXT NOT NULL DEFAULT 'local',
                    evidence_fingerprint TEXT NOT NULL DEFAULT '',
                    schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_reconciliation_review_history_item
                    ON reconciliation_review_history(import_run_id, item_key, history_id);
                """)
            columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(reconciliation_review_decisions)"
                ).fetchall()
            }
            if "evidence_fingerprint" not in columns:
                conn.execute(
                    "ALTER TABLE reconciliation_review_decisions "
                    "ADD COLUMN evidence_fingerprint TEXT NOT NULL DEFAULT ''"
                )
            conn.execute("""
                INSERT INTO reconciliation_review_history (
                    import_run_id, item_key, category, symbol, review_status,
                    note, reviewer, evidence_fingerprint, schema_version,
                    created_at, updated_at, recorded_at
                )
                SELECT current.import_run_id, current.item_key, current.category,
                       current.symbol, current.review_status, current.note,
                       current.reviewer, current.evidence_fingerprint,
                       current.schema_version, current.created_at,
                       current.updated_at, current.updated_at
                FROM reconciliation_review_decisions AS current
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM reconciliation_review_history AS history
                    WHERE history.import_run_id = current.import_run_id
                      AND history.item_key = current.item_key
                      AND history.updated_at = current.updated_at
                      AND history.evidence_fingerprint = current.evidence_fingerprint
                )
            """)
            conn.commit()


def _decision_from_row(row: sqlite3.Row) -> ManualReviewDecision:
    return ManualReviewDecision(
        id=int(row["id"]),
        import_run_id=str(row["import_run_id"]),
        item_key=str(row["item_key"]),
        category=str(row["category"]),
        symbol=str(row["symbol"] or ""),
        review_status=str(row["review_status"]),  # type: ignore[arg-type]
        note=str(row["note"] or ""),
        reviewer=str(row["reviewer"] or "local"),
        evidence_fingerprint=str(row["evidence_fingerprint"] or ""),
        schema_version=str(row["schema_version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
