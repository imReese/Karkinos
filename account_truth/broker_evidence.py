"""SQLite staging store for broker evidence imports."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from account_truth.broker_statement import (
    BrokerEvidenceEvent,
    BrokerStatementPreview,
    ValidationStatus,
)

ACCOUNT_TRUTH_SCHEMA_VERSION = "karkinos.account_truth.broker_evidence.v1"


@dataclass(frozen=True)
class BrokerImportRun:
    import_run_id: str
    schema_version: str
    source_type: str
    source_name: str
    file_fingerprint: str
    row_count: int
    valid_row_count: int
    invalid_row_count: int
    row_duplicate_count: int
    file_duplicate_count: int
    validation_status: ValidationStatus
    limitations: list[str]
    duplicate_of_import_run_id: str | None
    created_at: str


@dataclass(frozen=True)
class StoredBrokerEvidenceEvent:
    import_run_id: str
    row_number: int
    row_fingerprint: str
    event_id: str
    event_type: str
    occurred_at: str
    settled_at: str
    symbol: str
    instrument_name: str
    asset_class: str
    currency: str
    quantity: str
    price: str
    gross_amount: str
    fee: str
    tax: str
    net_amount: str
    cash_balance: str | None
    position_quantity: str | None
    cost_basis: str | None
    note: str
    is_row_duplicate: bool
    duplicate_of_row_number: int | None


class BrokerEvidenceRepository:
    """Persist broker import runs and staged evidence events."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def save_preview(
        self,
        preview: BrokerStatementPreview,
        *,
        source_name: str = "",
    ) -> BrokerImportRun:
        created_at = datetime.now(UTC).isoformat()
        duplicate_of = self._find_existing_import_run(preview.file_fingerprint)
        file_duplicate_count = 1 if duplicate_of else 0
        validation_status = (
            "warning"
            if duplicate_of and preview.validation_status == "pass"
            else preview.validation_status
        )
        import_run = BrokerImportRun(
            import_run_id=f"import_{uuid.uuid4().hex}",
            schema_version=ACCOUNT_TRUTH_SCHEMA_VERSION,
            source_type=preview.source_type,
            source_name=source_name,
            file_fingerprint=preview.file_fingerprint,
            row_count=preview.row_count,
            valid_row_count=preview.valid_row_count,
            invalid_row_count=preview.invalid_row_count,
            row_duplicate_count=preview.duplicate_row_count,
            file_duplicate_count=file_duplicate_count,
            validation_status=validation_status,
            limitations=list(preview.limitations),
            duplicate_of_import_run_id=duplicate_of,
            created_at=created_at,
        )

        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                INSERT INTO broker_import_runs (
                    import_run_id, schema_version, source_type, source_name,
                    file_fingerprint, row_count, valid_row_count,
                    invalid_row_count, row_duplicate_count, file_duplicate_count,
                    validation_status, limitations_json,
                    duplicate_of_import_run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_run.import_run_id,
                    import_run.schema_version,
                    import_run.source_type,
                    import_run.source_name,
                    import_run.file_fingerprint,
                    import_run.row_count,
                    import_run.valid_row_count,
                    import_run.invalid_row_count,
                    import_run.row_duplicate_count,
                    import_run.file_duplicate_count,
                    import_run.validation_status,
                    json.dumps(import_run.limitations, ensure_ascii=False),
                    import_run.duplicate_of_import_run_id,
                    import_run.created_at,
                ),
            )
            if not duplicate_of and preview.validation_status != "blocked":
                conn.executemany(
                    """
                    INSERT INTO broker_evidence_events (
                        import_run_id, row_number, row_fingerprint, event_id,
                        event_type, occurred_at, settled_at, symbol,
                        instrument_name, asset_class, currency, quantity,
                        price, gross_amount, fee, tax, net_amount,
                        cash_balance, position_quantity, cost_basis, note,
                        is_row_duplicate, duplicate_of_row_number, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        self._event_insert_values(
                            event,
                            import_run_id=import_run.import_run_id,
                            created_at=created_at,
                        )
                        for event in preview.events
                    ],
                )
            conn.commit()
        return import_run

    def list_events(self, import_run_id: str) -> list[StoredBrokerEvidenceEvent]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM broker_evidence_events
                WHERE import_run_id = ?
                ORDER BY row_number ASC, id ASC
                """,
                (import_run_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_import_runs(self, *, limit: int = 50) -> list[BrokerImportRun]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM broker_import_runs
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._import_run_from_row(row) for row in rows]

    def get_import_run(self, import_run_id: str) -> BrokerImportRun | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM broker_import_runs
                WHERE import_run_id = ?
                LIMIT 1
                """,
                (import_run_id,),
            ).fetchone()
        return self._import_run_from_row(row) if row else None

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS broker_import_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_run_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    file_fingerprint TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    valid_row_count INTEGER NOT NULL,
                    invalid_row_count INTEGER NOT NULL,
                    row_duplicate_count INTEGER NOT NULL,
                    file_duplicate_count INTEGER NOT NULL,
                    validation_status TEXT NOT NULL,
                    limitations_json TEXT NOT NULL,
                    duplicate_of_import_run_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_broker_import_runs_fingerprint
                    ON broker_import_runs(file_fingerprint);

                CREATE TABLE IF NOT EXISTS broker_evidence_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_run_id TEXT NOT NULL,
                    row_number INTEGER NOT NULL,
                    row_fingerprint TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    settled_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    instrument_name TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    gross_amount TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    tax TEXT NOT NULL,
                    net_amount TEXT NOT NULL,
                    cash_balance TEXT,
                    position_quantity TEXT,
                    cost_basis TEXT,
                    note TEXT NOT NULL,
                    is_row_duplicate INTEGER NOT NULL,
                    duplicate_of_row_number INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(import_run_id)
                        REFERENCES broker_import_runs(import_run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_broker_evidence_events_import_run
                    ON broker_evidence_events(import_run_id);

                CREATE INDEX IF NOT EXISTS idx_broker_evidence_events_row_fingerprint
                    ON broker_evidence_events(row_fingerprint);
                """)
            conn.commit()

    def _find_existing_import_run(self, file_fingerprint: str) -> str | None:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                """
                SELECT import_run_id
                FROM broker_import_runs
                WHERE file_fingerprint = ?
                  AND file_duplicate_count = 0
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (file_fingerprint,),
            ).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _event_insert_values(
        event: BrokerEvidenceEvent,
        *,
        import_run_id: str,
        created_at: str,
    ) -> tuple[object, ...]:
        return (
            import_run_id,
            event.row_number,
            event.row_fingerprint,
            event.event_id,
            event.event_type,
            event.occurred_at,
            event.settled_at,
            event.symbol,
            event.instrument_name,
            event.asset_class,
            event.currency,
            _decimal_to_text(event.quantity),
            _decimal_to_text(event.price),
            _decimal_to_text(event.gross_amount),
            _decimal_to_text(event.fee),
            _decimal_to_text(event.tax),
            _decimal_to_text(event.net_amount),
            _optional_decimal_to_text(event.cash_balance),
            _optional_decimal_to_text(event.position_quantity),
            _optional_decimal_to_text(event.cost_basis),
            event.note,
            1 if event.is_duplicate else 0,
            event.duplicate_of_row_number,
            created_at,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> StoredBrokerEvidenceEvent:
        return StoredBrokerEvidenceEvent(
            import_run_id=str(row["import_run_id"]),
            row_number=int(row["row_number"]),
            row_fingerprint=str(row["row_fingerprint"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            occurred_at=str(row["occurred_at"]),
            settled_at=str(row["settled_at"]),
            symbol=str(row["symbol"]),
            instrument_name=str(row["instrument_name"]),
            asset_class=str(row["asset_class"]),
            currency=str(row["currency"]),
            quantity=str(row["quantity"]),
            price=str(row["price"]),
            gross_amount=str(row["gross_amount"]),
            fee=str(row["fee"]),
            tax=str(row["tax"]),
            net_amount=str(row["net_amount"]),
            cash_balance=row["cash_balance"],
            position_quantity=row["position_quantity"],
            cost_basis=row["cost_basis"],
            note=str(row["note"]),
            is_row_duplicate=bool(row["is_row_duplicate"]),
            duplicate_of_row_number=row["duplicate_of_row_number"],
        )

    @staticmethod
    def _import_run_from_row(row: sqlite3.Row) -> BrokerImportRun:
        return BrokerImportRun(
            import_run_id=str(row["import_run_id"]),
            schema_version=str(row["schema_version"]),
            source_type=str(row["source_type"]),
            source_name=str(row["source_name"] or ""),
            file_fingerprint=str(row["file_fingerprint"]),
            row_count=int(row["row_count"]),
            valid_row_count=int(row["valid_row_count"]),
            invalid_row_count=int(row["invalid_row_count"]),
            row_duplicate_count=int(row["row_duplicate_count"]),
            file_duplicate_count=int(row["file_duplicate_count"]),
            validation_status=str(row["validation_status"]),  # type: ignore[arg-type]
            limitations=json.loads(str(row["limitations_json"] or "[]")),
            duplicate_of_import_run_id=row["duplicate_of_import_run_id"],
            created_at=str(row["created_at"]),
        )


def _decimal_to_text(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal_to_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _decimal_to_text(value)
