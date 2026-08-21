"""SQLite staging store for broker evidence imports."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from account_truth.broker_statement import (
    BROKER_STATEMENT_EVENT_TYPES,
    BrokerEvidenceEvent,
    BrokerStatementPreview,
    ValidationStatus,
)

ACCOUNT_TRUTH_SCHEMA_VERSION = "karkinos.account_truth.broker_evidence.v2"
_SUPPORTED_ACCOUNT_TRUTH_SCHEMA_VERSIONS = {
    "karkinos.account_truth.broker_evidence.v1",
    ACCOUNT_TRUTH_SCHEMA_VERSION,
}
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_VALIDATION_STATUSES = {"pass", "warning", "blocked"}


class BrokerEvidenceReadRejected(RuntimeError):
    """Raised when persisted canonical broker evidence is unsafe to read."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
    transfer_fee: str
    cost_basis_method: str
    broker_order_id: str
    client_order_id: str


class BrokerEvidenceRepository:
    """Persist broker import runs and staged evidence events."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def save_preview(
        self,
        preview: BrokerStatementPreview,
        *,
        source_name: str = "",
    ) -> BrokerImportRun:
        self._ensure_schema()
        created_at = datetime.now(UTC).isoformat()
        existing_import_run_id = self._find_existing_import_run(
            preview.file_fingerprint
        )
        if existing_import_run_id is not None:
            return self._update_existing_import_run(
                existing_import_run_id,
                preview,
                source_name=source_name,
                updated_at=created_at,
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
            file_duplicate_count=0,
            validation_status=preview.validation_status,
            limitations=list(preview.limitations),
            duplicate_of_import_run_id=None,
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
            if preview.validation_status != "blocked":
                conn.executemany(
                    """
                    INSERT INTO broker_evidence_events (
                        import_run_id, row_number, row_fingerprint, event_id,
                        event_type, occurred_at, settled_at, symbol,
                        instrument_name, asset_class, currency, quantity,
                        price, gross_amount, fee, tax, net_amount,
                        cash_balance, position_quantity, cost_basis, note,
                        is_row_duplicate, duplicate_of_row_number, transfer_fee,
                        cost_basis_method, broker_order_id, client_order_id,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def _update_existing_import_run(
        self,
        import_run_id: str,
        preview: BrokerStatementPreview,
        *,
        source_name: str,
        updated_at: str,
    ) -> BrokerImportRun:
        # The same file fingerprint is an idempotent replay, not new evidence.
        # Preserve the first-seen timestamp so restart/polling cannot refresh
        # Account Truth freshness without a changed evidence file.
        with sqlite3.connect(self._path) as conn:
            existing_row = conn.execute(
                """
                SELECT validation_status
                FROM broker_import_runs
                WHERE import_run_id = ?
                LIMIT 1
                """,
                (import_run_id,),
            ).fetchone()
            if existing_row is None:
                raise RuntimeError(
                    "Broker import run disappeared during idempotent import"
                )
            previous_validation_status = str(existing_row[0])
            existing_event_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM broker_evidence_events
                    WHERE import_run_id = ?
                    """,
                    (import_run_id,),
                ).fetchone()[0]
            )
            if previous_validation_status == "blocked" and existing_event_count:
                raise BrokerEvidenceReadRejected(
                    "broker_evidence_replay_state_conflict"
                )
            if (
                previous_validation_status != "blocked"
                and preview.validation_status != "blocked"
                and existing_event_count != preview.valid_row_count
                and existing_event_count != 0
            ):
                raise BrokerEvidenceReadRejected(
                    "broker_evidence_replay_state_conflict"
                )
            conn.execute(
                """
                UPDATE broker_import_runs
                SET source_name = ?,
                    source_type = ?,
                    row_count = ?,
                    valid_row_count = ?,
                    invalid_row_count = ?,
                    row_duplicate_count = ?,
                    file_duplicate_count = 0,
                    validation_status = ?,
                    limitations_json = ?,
                    duplicate_of_import_run_id = NULL
                WHERE import_run_id = ?
                """,
                (
                    source_name,
                    preview.source_type,
                    preview.row_count,
                    preview.valid_row_count,
                    preview.invalid_row_count,
                    preview.duplicate_row_count,
                    preview.validation_status,
                    json.dumps(preview.limitations, ensure_ascii=False),
                    import_run_id,
                ),
            )
            if preview.validation_status == "blocked":
                # A stricter parser may reject a previously accepted file with
                # the same content fingerprint.  Keep the first-seen import
                # identity, but never retain events that the current parser
                # refuses to stage.
                conn.execute(
                    "DELETE FROM broker_evidence_events WHERE import_run_id = ?",
                    (import_run_id,),
                )
            elif previous_validation_status == "blocked" or existing_event_count == 0:
                # The same bytes may become valid after a parser contract fix.
                # Also recover a completely empty batch left by the legacy
                # blocked-to-pass replay bug. Never use replay to silently
                # repair a partial non-blocked batch.
                conn.executemany(
                    """
                    INSERT INTO broker_evidence_events (
                        import_run_id, row_number, row_fingerprint, event_id,
                        event_type, occurred_at, settled_at, symbol,
                        instrument_name, asset_class, currency, quantity,
                        price, gross_amount, fee, tax, net_amount,
                        cash_balance, position_quantity, cost_basis, note,
                        is_row_duplicate, duplicate_of_row_number, transfer_fee,
                        cost_basis_method, broker_order_id, client_order_id,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        self._event_insert_values(
                            event,
                            import_run_id=import_run_id,
                            created_at=updated_at,
                        )
                        for event in preview.events
                    ],
                )
            conn.commit()

        existing = self.get_import_run(import_run_id)
        if existing is None:
            raise RuntimeError("Broker import run disappeared during idempotent import")
        return existing

    def list_events(self, import_run_id: str) -> list[StoredBrokerEvidenceEvent]:
        with self._read_connection() as conn:
            if conn is None:
                return []
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
        with self._read_connection() as conn:
            if conn is None:
                return []
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
        with self._read_connection() as conn:
            if conn is None:
                return None
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

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection | None]:
        if not self._path.is_file():
            yield None
            return
        try:
            read_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(read_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                schema_state = self._schema_state(conn)
                if schema_state == "absent":
                    yield None
                    return
                if schema_state != "complete":
                    raise BrokerEvidenceReadRejected(
                        "broker_evidence_schema_incomplete"
                    )
                yield conn
        except BrokerEvidenceReadRejected:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise BrokerEvidenceReadRejected(
                "broker_evidence_store_unreadable"
            ) from exc

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
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
                    transfer_fee TEXT NOT NULL DEFAULT '0',
                    cost_basis_method TEXT NOT NULL DEFAULT '',
                    broker_order_id TEXT NOT NULL DEFAULT '',
                    client_order_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(import_run_id)
                        REFERENCES broker_import_runs(import_run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_broker_evidence_events_import_run
                    ON broker_evidence_events(import_run_id);

                CREATE INDEX IF NOT EXISTS idx_broker_evidence_events_row_fingerprint
                    ON broker_evidence_events(row_fingerprint);
                """)
            self._ensure_event_component_columns(conn)
            conn.commit()

    @staticmethod
    def _schema_state(conn: sqlite3.Connection) -> str:
        required_tables = {
            "broker_import_runs": {
                "id",
                "import_run_id",
                "schema_version",
                "source_type",
                "source_name",
                "file_fingerprint",
                "row_count",
                "valid_row_count",
                "invalid_row_count",
                "row_duplicate_count",
                "file_duplicate_count",
                "validation_status",
                "limitations_json",
                "duplicate_of_import_run_id",
                "created_at",
            },
            "broker_evidence_events": {
                "id",
                "import_run_id",
                "row_number",
                "row_fingerprint",
                "event_id",
                "event_type",
                "occurred_at",
                "settled_at",
                "symbol",
                "instrument_name",
                "asset_class",
                "currency",
                "quantity",
                "price",
                "gross_amount",
                "fee",
                "tax",
                "net_amount",
                "cash_balance",
                "position_quantity",
                "cost_basis",
                "note",
                "is_row_duplicate",
                "duplicate_of_row_number",
                "transfer_fee",
                "cost_basis_method",
                "broker_order_id",
                "client_order_id",
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

    @staticmethod
    def _ensure_event_component_columns(conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA table_info(broker_evidence_events)").fetchall()
        columns = {str(row[1]) for row in rows}
        if "transfer_fee" not in columns:
            conn.execute(
                "ALTER TABLE broker_evidence_events "
                "ADD COLUMN transfer_fee TEXT NOT NULL DEFAULT '0'"
            )
        if "cost_basis_method" not in columns:
            conn.execute(
                "ALTER TABLE broker_evidence_events "
                "ADD COLUMN cost_basis_method TEXT NOT NULL DEFAULT ''"
            )
        if "broker_order_id" not in columns:
            conn.execute(
                "ALTER TABLE broker_evidence_events "
                "ADD COLUMN broker_order_id TEXT NOT NULL DEFAULT ''"
            )
        if "client_order_id" not in columns:
            conn.execute(
                "ALTER TABLE broker_evidence_events "
                "ADD COLUMN client_order_id TEXT NOT NULL DEFAULT ''"
            )

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
            _decimal_to_text(event.transfer_fee),
            event.cost_basis_method,
            event.broker_order_id,
            event.client_order_id,
            created_at,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> StoredBrokerEvidenceEvent:
        try:
            event = StoredBrokerEvidenceEvent(
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
                cash_balance=(
                    str(row["cash_balance"])
                    if row["cash_balance"] is not None
                    else None
                ),
                position_quantity=(
                    str(row["position_quantity"])
                    if row["position_quantity"] is not None
                    else None
                ),
                cost_basis=(
                    str(row["cost_basis"]) if row["cost_basis"] is not None else None
                ),
                note=str(row["note"]),
                is_row_duplicate=_stored_bool(row["is_row_duplicate"]),
                duplicate_of_row_number=(
                    int(row["duplicate_of_row_number"])
                    if row["duplicate_of_row_number"] is not None
                    else None
                ),
                transfer_fee=str(row["transfer_fee"]),
                cost_basis_method=str(row["cost_basis_method"] or ""),
                broker_order_id=str(row["broker_order_id"] or ""),
                client_order_id=str(row["client_order_id"] or ""),
            )
            _validate_stored_event(event)
            return event
        except BrokerEvidenceReadRejected:
            raise
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise BrokerEvidenceReadRejected("broker_evidence_record_invalid") from exc

    @staticmethod
    def _import_run_from_row(row: sqlite3.Row) -> BrokerImportRun:
        try:
            import_run = BrokerImportRun(
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
                limitations=_json_string_list(row["limitations_json"]),
                duplicate_of_import_run_id=(
                    str(row["duplicate_of_import_run_id"])
                    if row["duplicate_of_import_run_id"] is not None
                    else None
                ),
                created_at=str(row["created_at"]),
            )
            _validate_import_run(import_run)
            return import_run
        except BrokerEvidenceReadRejected:
            raise
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise BrokerEvidenceReadRejected("broker_evidence_record_invalid") from exc


def _json_string_list(raw_value: object) -> list[str]:
    parsed = json.loads(str(raw_value or "[]"))
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise BrokerEvidenceReadRejected("broker_evidence_record_invalid")
    return parsed


def _validate_import_run(import_run: BrokerImportRun) -> None:
    counts = (
        import_run.row_count,
        import_run.valid_row_count,
        import_run.invalid_row_count,
        import_run.row_duplicate_count,
        import_run.file_duplicate_count,
    )
    if (
        not import_run.import_run_id.strip()
        or import_run.schema_version not in _SUPPORTED_ACCOUNT_TRUTH_SCHEMA_VERSIONS
        or not import_run.source_type.strip()
        or not _FINGERPRINT_PATTERN.fullmatch(import_run.file_fingerprint)
        or any(value < 0 for value in counts)
        or import_run.row_duplicate_count > import_run.valid_row_count
        or import_run.validation_status not in _VALIDATION_STATUSES
        or not import_run.created_at.strip()
    ):
        raise BrokerEvidenceReadRejected("broker_evidence_record_invalid")


def _validate_stored_event(event: StoredBrokerEvidenceEvent) -> None:
    required_decimals = (
        event.quantity,
        event.price,
        event.gross_amount,
        event.fee,
        event.tax,
        event.net_amount,
        event.transfer_fee,
    )
    optional_decimals = (
        event.cash_balance,
        event.position_quantity,
        event.cost_basis,
    )
    if (
        not event.import_run_id.strip()
        or event.row_number <= 0
        or not _FINGERPRINT_PATTERN.fullmatch(event.row_fingerprint)
        or not event.event_id.strip()
        or event.event_type not in BROKER_STATEMENT_EVENT_TYPES
        or not event.occurred_at.strip()
        or not event.currency.strip()
        or any(not _is_finite_decimal(value) for value in required_decimals)
        or any(
            value is not None and not _is_finite_decimal(value)
            for value in optional_decimals
        )
        or (
            event.duplicate_of_row_number is not None
            and event.duplicate_of_row_number <= 0
        )
        or (event.is_row_duplicate != (event.duplicate_of_row_number is not None))
    ):
        raise BrokerEvidenceReadRejected("broker_evidence_record_invalid")


def _stored_bool(raw_value: object) -> bool:
    if raw_value not in {0, 1}:
        raise BrokerEvidenceReadRejected("broker_evidence_record_invalid")
    return bool(raw_value)


def _is_finite_decimal(raw_value: str) -> bool:
    try:
        return Decimal(raw_value).is_finite()
    except (ArithmeticError, ValueError):
        return False


def _decimal_to_text(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal_to_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _decimal_to_text(value)
