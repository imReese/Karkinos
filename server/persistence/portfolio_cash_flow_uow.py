"""Atomic unit of work for ledger-owned portfolio cash flows."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from server.contracts.portfolio_cash_flows import (
    CashFlowCorrectionResult,
    CashFlowCorrectionWrite,
    CashFlowWrite,
    CashFlowWriteResult,
)
from server.contracts.portfolio_mutations import PortfolioMutationConflict
from server.persistence.financial_facts_ledger import (
    insert_ledger_entry_on_connection,
)
from server.persistence.portfolio_cash_flow_repository import (
    cash_flow_entry_type,
    insert_cash_flow_projection,
    load_cash_flow_ledger_entry,
    load_cash_flow_projection,
    reversed_cash_flow_entry_type,
    validate_cash_flow_projection,
    validate_cash_flow_write,
)
from server.persistence.portfolio_mutation_claims import (
    claim_portfolio_mutation,
    complete_portfolio_mutation,
    validate_portfolio_mutation_valuation,
)
from server.persistence.valuation_transaction import ValuationTransactionWriter

FailureInjector = Callable[[str], None]


class PortfolioCashFlowUnitOfWork:
    """Commit canonical ledger, compatibility projection, and valuation together."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        now: Callable[[], str],
        valuation_transaction_writer: ValuationTransactionWriter,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._now = now
        self._valuation_transaction_writer = valuation_transaction_writer
        self._failure_injector = failure_injector

    def record(self, command: CashFlowWrite) -> CashFlowWriteResult:
        validate_cash_flow_write(command)
        created_at = self._now()
        with sqlite3.connect(self._database_path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = claim_portfolio_mutation(
                    conn,
                    command=command,
                    mutation_kind="cash_flow.record",
                    created_at=created_at,
                )
                if replay is not None:
                    result = _replay_cash_flow_record(conn, replay)
                    conn.rollback()
                    return result
                self._inject("after_claim")
                cash_flow_id = insert_cash_flow_projection(
                    conn,
                    command,
                    created_at=created_at,
                )
                self._inject("after_cash_flow_projection")
                ledger_entry_id = insert_ledger_entry_on_connection(
                    conn,
                    entry_type=cash_flow_entry_type(command.flow_type),
                    timestamp=command.timestamp,
                    amount=command.amount,
                    asset_class="cash",
                    note=command.note,
                    source="portfolio_cash_flow",
                    source_ref=f"cash_flow:{cash_flow_id}",
                    created_at=created_at,
                )
                self._inject("after_ledger_entry")
                cash_flow = load_cash_flow_projection(conn, cash_flow_id)
                ledger = load_cash_flow_ledger_entry(conn, cash_flow_id)
                if cash_flow is None or ledger is None:
                    raise RuntimeError("cash-flow facts could not be reloaded")
                validate_cash_flow_projection(cash_flow, ledger)
                valuation = self._valuation_transaction_writer(
                    conn,
                    candidate_ledger_rows=[ledger],
                )
                self._inject("after_valuation")
                complete_portfolio_mutation(
                    conn,
                    command_id=command.command_id,
                    result={
                        "cash_flow_id": cash_flow_id,
                        "ledger_entry_id": ledger_entry_id,
                        "valuation_snapshot_id": valuation["snapshot_id"],
                        "valuation_snapshot_status": valuation["status"],
                    },
                    completed_at=self._now(),
                )
                self._inject("after_claim_completion")
                self._inject("before_record_commit")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return CashFlowWriteResult(
            cash_flow=cash_flow,
            ledger_entry_id=ledger_entry_id,
        )

    def correct(self, command: CashFlowCorrectionWrite) -> CashFlowCorrectionResult:
        cash_flow_id = command.cash_flow_id
        if cash_flow_id <= 0:
            raise ValueError("cash_flow_id must be positive")
        created_at = self._now()
        with sqlite3.connect(self._database_path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = claim_portfolio_mutation(
                    conn,
                    command=command,
                    mutation_kind="cash_flow.correct",
                    created_at=created_at,
                )
                if replay is not None:
                    result = _replay_cash_flow_correction(
                        conn,
                        replay,
                        cash_flow_id=cash_flow_id,
                    )
                    conn.rollback()
                    return result
                self._inject("after_claim")
                cash_flow = load_cash_flow_projection(conn, cash_flow_id)
                if cash_flow is None:
                    raise KeyError(f"cash flow not found: {cash_flow_id}")
                original = load_cash_flow_ledger_entry(conn, cash_flow_id)
                if original is None:
                    raise RuntimeError(
                        "cash flow has no canonical ledger owner; migration required"
                    )
                validate_cash_flow_projection(cash_flow, original)
                existing = conn.execute(
                    """
                    SELECT * FROM ledger_entries
                    WHERE source = 'portfolio_cash_flow_correction'
                      AND source_ref = ?
                    LIMIT 1
                    """,
                    (f"cash_flow:{cash_flow_id}",),
                ).fetchone()
                if existing is not None:
                    raise PortfolioMutationConflict(
                        "cash flow was already corrected by another command"
                    )
                correction_id = insert_ledger_entry_on_connection(
                    conn,
                    entry_type=reversed_cash_flow_entry_type(
                        str(original["entry_type"])
                    ),
                    timestamp=created_at,
                    amount=float(original["amount"]),
                    asset_class="cash",
                    note=(
                        "Append-only reversal of canonical cash flow "
                        f"{cash_flow_id}."
                    ),
                    source="portfolio_cash_flow_correction",
                    source_ref=f"cash_flow:{cash_flow_id}",
                    created_at=created_at,
                )
                self._inject("after_correction_entry")
                correction = conn.execute(
                    "SELECT * FROM ledger_entries WHERE id = ?",
                    (correction_id,),
                ).fetchone()
                if correction is None:
                    raise RuntimeError("cash-flow correction could not be reloaded")
                valuation = self._valuation_transaction_writer(
                    conn,
                    candidate_ledger_rows=[dict(correction)],
                )
                self._inject("after_valuation")
                complete_portfolio_mutation(
                    conn,
                    command_id=command.command_id,
                    result={
                        "cash_flow_id": cash_flow_id,
                        "correction_ledger_entry_id": correction_id,
                        "valuation_snapshot_id": valuation["snapshot_id"],
                        "valuation_snapshot_status": valuation["status"],
                    },
                    completed_at=self._now(),
                )
                self._inject("after_claim_completion")
                self._inject("before_correction_commit")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return CashFlowCorrectionResult(
            cash_flow_id=cash_flow_id,
            correction_ledger_entry_id=correction_id,
        )

    def _inject(self, stage: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage)


def _validate_existing_correction(
    correction: dict[str, object],
    original: dict[str, object],
    *,
    cash_flow_id: int,
) -> None:
    if (
        correction.get("entry_type")
        != reversed_cash_flow_entry_type(str(original["entry_type"]))
        or correction.get("source") != "portfolio_cash_flow_correction"
        or correction.get("source_ref") != f"cash_flow:{cash_flow_id}"
        or float(correction.get("amount") or 0.0)
        != float(original.get("amount") or 0.0)
        or str(correction.get("asset_class") or "") != "cash"
    ):
        raise RuntimeError("existing cash-flow correction is invalid")


def _replay_cash_flow_record(
    conn: sqlite3.Connection,
    payload: dict[str, object],
) -> CashFlowWriteResult:
    try:
        cash_flow_id = int(payload["cash_flow_id"])
        ledger_entry_id = int(payload["ledger_entry_id"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("cash-flow mutation result is invalid") from None
    cash_flow = load_cash_flow_projection(conn, cash_flow_id)
    ledger = load_cash_flow_ledger_entry(conn, cash_flow_id)
    if cash_flow is None or ledger is None or int(ledger["id"]) != ledger_entry_id:
        raise RuntimeError("cash-flow mutation result drifted")
    validate_cash_flow_projection(cash_flow, ledger)
    validate_portfolio_mutation_valuation(conn, payload)
    return CashFlowWriteResult(
        cash_flow=cash_flow,
        ledger_entry_id=ledger_entry_id,
        replayed=True,
    )


def _replay_cash_flow_correction(
    conn: sqlite3.Connection,
    payload: dict[str, object],
    *,
    cash_flow_id: int,
) -> CashFlowCorrectionResult:
    try:
        stored_cash_flow_id = int(payload["cash_flow_id"])
        correction_id = int(payload["correction_ledger_entry_id"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("cash-flow correction result is invalid") from None
    if stored_cash_flow_id != cash_flow_id:
        raise RuntimeError("cash-flow correction result drifted")
    cash_flow = load_cash_flow_projection(conn, cash_flow_id)
    original = load_cash_flow_ledger_entry(conn, cash_flow_id)
    correction = conn.execute(
        "SELECT * FROM ledger_entries WHERE id = ?",
        (correction_id,),
    ).fetchone()
    if cash_flow is None or original is None or correction is None:
        raise RuntimeError("cash-flow correction result drifted")
    validate_cash_flow_projection(cash_flow, original)
    _validate_existing_correction(
        dict(correction),
        original,
        cash_flow_id=cash_flow_id,
    )
    validate_portfolio_mutation_valuation(conn, payload)
    return CashFlowCorrectionResult(
        cash_flow_id=cash_flow_id,
        correction_ledger_entry_id=correction_id,
        replayed=True,
    )


__all__ = ["PortfolioCashFlowUnitOfWork"]
