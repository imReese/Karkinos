"""SQLite repository and atomic UoW for the legacy fund duplicate repair."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Generic, TypeVar

from server.persistence.event_log import serialize_event_payload_json
from server.persistence.financial_facts_ledger import insert_ledger_entry_on_connection
from server.persistence.valuation_transaction import ValuationTransactionWriter
from server.projections.legacy_fund_trade_duplicate_correction import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    legacy_fund_trade_duplicate_source_ref,
)

_REQUIRED_LEDGER_COLUMNS = frozenset(
    {
        "id",
        "entry_type",
        "timestamp",
        "amount",
        "symbol",
        "direction",
        "quantity",
        "price",
        "commission",
        "gross_amount",
        "net_cash_impact",
        "fee_breakdown_json",
        "fee_rule_id",
        "fee_rule_version",
        "estimated_commission",
        "estimated_net_cash_impact",
        "estimated_fee_breakdown_json",
        "estimated_fee_rule_id",
        "estimated_fee_rule_version",
        "settlement_status",
        "settled_at",
        "settlement_source",
        "settlement_source_ref",
        "settlement_note",
        "cost_basis_method",
        "correction_payload_json",
        "asset_class",
        "note",
        "source",
        "source_ref",
        "created_at",
    }
)
_REQUIRED_TRADE_COLUMNS = frozenset(
    {
        "id",
        "timestamp",
        "symbol",
        "direction",
        "quantity",
        "price",
        "commission",
        "asset_class",
        "note",
        "created_at",
    }
)

FailureInjector = Callable[[str], None]
TransactionResult = TypeVar("TransactionResult")


class LegacyFundTradeDuplicateRepairBlocked(RuntimeError):
    """Raised before commit when the bounded repair cannot be proven safe."""

    def __init__(self, *blockers: str) -> None:
        normalized = tuple(sorted(set(blockers))) or (
            "legacy_fund_trade_duplicate_repair_blocked",
        )
        super().__init__(",".join(normalized))
        self.blockers = normalized


@dataclass(frozen=True, slots=True)
class LegacyFundTradeDuplicateTransactionDecision(Generic[TransactionResult]):
    value: TransactionResult
    commit: bool


class LegacyFundTradeDuplicateRepairUnitOfWork:
    """Expose only repair-scoped persistence operations inside one transaction."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        database_path: Path,
        created_at: str,
        valuation_transaction_writer: ValuationTransactionWriter | None,
        failure_injector: FailureInjector | None,
    ) -> None:
        self._conn = conn
        self._database_path = database_path
        self._created_at = created_at
        self._valuation_transaction_writer = valuation_transaction_writer
        self._failure_injector = failure_injector

    def read_snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        _require_schema(self._conn)
        return _load_ledger_rows(self._conn), _load_trade_rows(self._conn)

    def read_ledger_rows(self) -> list[dict[str, Any]]:
        return _load_ledger_rows(self._conn)

    def append_correction(
        self,
        *,
        plan: dict[str, Any],
        repair_fingerprint: str,
        group_fingerprint: str,
        correction_index: int,
    ) -> dict[str, Any]:
        before = plan["position_before"]
        after = plan["position_after"]
        quantity_delta = Decimal(str(after["quantity"])) - Decimal(
            str(before["quantity"])
        )
        correction_id = insert_ledger_entry_on_connection(
            self._conn,
            entry_type=LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
            timestamp=str(plan["effective_at"]),
            amount=float(Decimal(str(plan["cash_delta"]))),
            symbol=str(plan["symbol"]),
            quantity=float(quantity_delta),
            commission=0.0,
            correction_payload_json=serialize_event_payload_json(plan),
            asset_class="fund",
            note=(
                "Append-only replay correction for a fingerprint-bound "
                "legacy fund trade duplicate group."
            ),
            source=LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
            source_ref=legacy_fund_trade_duplicate_source_ref(
                repair_fingerprint,
                group_fingerprint,
            ),
            created_at=self._created_at,
        )
        row = self._conn.execute(
            "SELECT * FROM ledger_entries WHERE id = ?",
            (correction_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("correction row could not be reloaded")
        self._inject(f"after_correction_entry_{correction_index}")
        return dict(row)

    def corrections_validated(self) -> None:
        self._inject("after_correction_validation")

    def publish_valuation(
        self,
        *,
        candidate_ledger_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        writer = self._valuation_transaction_writer
        if writer is not None:
            valuation = writer(
                self._conn,
                candidate_ledger_rows=candidate_ledger_rows,
            )
        else:
            from server.db import AppDatabase
            from server.persistence.financial_facts_valuation_composition import (
                build_and_publish_transaction_valuation,
            )

            valuation = build_and_publish_transaction_valuation(
                AppDatabase(self._database_path),
                self._conn,
                candidate_ledger_rows=candidate_ledger_rows,
                now=_parse_aware_datetime(self._created_at),
            )
        self._inject("after_valuation")
        return valuation

    def _inject(self, stage: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage)


def _parse_aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RuntimeError("legacy duplicate repair timestamp must be timezone-aware")
    return parsed


class LegacyFundTradeDuplicateRepairPersistence:
    """Own SQLite snapshots and the immediate append-only unit of work."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        now: Callable[[], str],
        valuation_transaction_writer: ValuationTransactionWriter | None = None,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._now = now
        self._valuation_transaction_writer = valuation_transaction_writer
        self._failure_injector = failure_injector

    def read_snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read candidate facts through a SQLite-enforced read-only handle."""

        with _connect(self._database_path, mode="ro") as conn:
            conn.execute("PRAGMA query_only=ON")
            _require_schema(conn)
            return _load_ledger_rows(conn), _load_trade_rows(conn)

    def run_immediate(
        self,
        operation: Callable[
            [LegacyFundTradeDuplicateRepairUnitOfWork],
            LegacyFundTradeDuplicateTransactionDecision[TransactionResult],
        ],
    ) -> TransactionResult:
        """Run an operation under one fail-closed ``BEGIN IMMEDIATE`` boundary."""

        with _connect(self._database_path, mode="rw") as conn:
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._inject("after_begin")
                unit_of_work = LegacyFundTradeDuplicateRepairUnitOfWork(
                    conn,
                    database_path=self._database_path,
                    created_at=self._now(),
                    valuation_transaction_writer=self._valuation_transaction_writer,
                    failure_injector=self._failure_injector,
                )
                decision = operation(unit_of_work)
                if decision.commit:
                    self._inject("before_commit")
                    conn.commit()
                else:
                    conn.rollback()
            except Exception:
                conn.rollback()
                raise
        return decision.value

    def _inject(self, stage: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage)


def _require_schema(conn: sqlite3.Connection) -> None:
    for table, required in (
        ("ledger_entries", _REQUIRED_LEDGER_COLUMNS),
        ("trades", _REQUIRED_TRADE_COLUMNS),
    ):
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if not required.issubset(columns):
            raise LegacyFundTradeDuplicateRepairBlocked(
                "legacy_fund_trade_duplicate_database_schema_incompatible"
            )


def _load_ledger_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM ledger_entries ORDER BY timestamp ASC, id ASC"
        ).fetchall()
    ]


def _load_trade_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [
        dict(row)
        for row in conn.execute("SELECT * FROM trades ORDER BY id ASC").fetchall()
    ]


def _connect(path: Path, *, mode: str) -> sqlite3.Connection:
    if mode not in {"ro", "rw"}:
        raise ValueError("SQLite mode must be ro or rw")
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode={mode}", uri=True, timeout=2
    )
    conn.row_factory = sqlite3.Row
    return conn


__all__ = [
    "LegacyFundTradeDuplicateRepairBlocked",
    "LegacyFundTradeDuplicateRepairPersistence",
    "LegacyFundTradeDuplicateRepairUnitOfWork",
    "LegacyFundTradeDuplicateTransactionDecision",
]
