"""Atomic unit of work for canonical manual portfolio trades."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from server.contracts.portfolio_mutations import PortfolioMutationConflict
from server.contracts.portfolio_trades import (
    ManualTradeCorrectionResult,
    ManualTradeCorrectionWrite,
    ManualTradeWrite,
    ManualTradeWriteResult,
)
from server.persistence.event_log import serialize_event_payload_json
from server.persistence.financial_facts_ledger import (
    insert_ledger_entry_on_connection,
)
from server.persistence.portfolio_mutation_claims import (
    claim_portfolio_mutation,
    complete_portfolio_mutation,
    validate_portfolio_mutation_valuation,
)
from server.persistence.portfolio_trade_repository import (
    insert_asset_identity_if_missing,
    insert_trade_projection,
    load_trade_ledger_entry,
    load_trade_projection,
    validate_manual_trade_write,
    validate_trade_projection,
)
from server.persistence.valuation_transaction import ValuationTransactionWriter

FailureInjector = Callable[[str], None]


class ManualTradeUnitOfWork:
    """Commit ledger authority and the legacy read projection together."""

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

    def record(self, command: ManualTradeWrite) -> ManualTradeWriteResult:
        """Append one canonical trade and its compatibility projection atomically."""

        validate_manual_trade_write(command)
        created_at = self._now()
        with sqlite3.connect(self._database_path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = claim_portfolio_mutation(
                    conn,
                    command=command,
                    mutation_kind="manual_trade.record",
                    created_at=created_at,
                )
                if replay is not None:
                    result = _replay_manual_trade_record(conn, replay, command)
                    conn.rollback()
                    return result
                self._inject("after_claim")
                insert_asset_identity_if_missing(
                    conn,
                    symbol=command.symbol,
                    asset_class=command.asset_class,
                    display_name=command.display_name,
                    created_at=created_at,
                )
                self._inject("after_asset_identity")
                trade_id = insert_trade_projection(
                    conn,
                    command,
                    created_at=created_at,
                )
                self._inject("after_trade_projection")
                ledger_entry_id = insert_ledger_entry_on_connection(
                    conn,
                    entry_type=f"trade_{command.direction}",
                    timestamp=command.timestamp,
                    amount=command.gross_amount,
                    symbol=command.symbol,
                    direction=command.direction,
                    quantity=command.quantity,
                    price=command.price,
                    commission=command.commission,
                    gross_amount=command.gross_amount,
                    net_cash_impact=command.net_cash_impact,
                    fee_breakdown_json=command.fee_breakdown_json,
                    fee_rule_id=command.fee_rule_id,
                    fee_rule_version=command.fee_rule_version,
                    cost_basis_method=command.cost_basis_method,
                    asset_class=command.asset_class,
                    note=command.note,
                    source="portfolio_trade",
                    source_ref=f"trade:{trade_id}",
                    created_at=created_at,
                )
                self._inject("after_ledger_entry")
                trade = load_trade_projection(conn, trade_id)
                if trade is None:
                    raise RuntimeError("manual trade projection could not be reloaded")
                ledger = load_trade_ledger_entry(conn, trade_id)
                if ledger is None:
                    raise RuntimeError("canonical manual trade ledger entry is missing")
                validate_trade_projection(trade, ledger)
                _validate_manual_trade_ledger(ledger, command)
                valuation = self._valuation_transaction_writer(
                    conn,
                    candidate_ledger_rows=[ledger],
                )
                self._inject("after_valuation")
                complete_portfolio_mutation(
                    conn,
                    command_id=command.command_id,
                    result={
                        "trade_id": trade_id,
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
        return ManualTradeWriteResult(
            trade=trade,
            ledger_entry_id=ledger_entry_id,
        )

    def correct(
        self,
        command: ManualTradeCorrectionWrite,
    ) -> ManualTradeCorrectionResult:
        """Append an exact replay-derived correction; never delete source history."""

        from server.projections.manual_trade_correction import (
            MANUAL_TRADE_CORRECTION_ENTRY_TYPE,
            MANUAL_TRADE_CORRECTION_SOURCE,
            build_manual_trade_correction_plan,
        )

        trade_id = command.trade_id
        if trade_id <= 0:
            raise ValueError("trade_id must be positive")
        created_at = self._now()
        with sqlite3.connect(self._database_path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = claim_portfolio_mutation(
                    conn,
                    command=command,
                    mutation_kind="manual_trade.correct",
                    created_at=created_at,
                )
                if replay is not None:
                    result = _replay_manual_trade_correction(
                        conn,
                        replay,
                        trade_id=trade_id,
                    )
                    conn.rollback()
                    return result
                self._inject("after_claim")
                trade = load_trade_projection(conn, trade_id)
                if trade is None:
                    raise KeyError(f"manual trade not found: {trade_id}")
                original = load_trade_ledger_entry(conn, trade_id)
                if original is None:
                    raise RuntimeError(
                        "manual trade has no canonical ledger owner; migration required"
                    )
                validate_trade_projection(trade, original)
                existing = conn.execute(
                    """
                    SELECT id, entry_type, symbol, correction_payload_json
                    FROM ledger_entries
                    WHERE source = ? AND source_ref = ?
                    LIMIT 1
                    """,
                    (MANUAL_TRADE_CORRECTION_SOURCE, f"trade:{trade_id}"),
                ).fetchone()
                if existing is not None:
                    raise PortfolioMutationConflict(
                        "manual trade was already corrected by another command"
                    )

                ledger_rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM ledger_entries ORDER BY timestamp ASC, id ASC"
                    ).fetchall()
                ]
                plan = build_manual_trade_correction_plan(
                    ledger_rows=ledger_rows,
                    original_entry_id=int(original["id"]),
                    trade_id=trade_id,
                )
                before = plan["position_before"]
                after = plan["position_after"]
                quantity_delta = Decimal(str(after["quantity"])) - Decimal(
                    str(before["quantity"])
                )
                correction_id = insert_ledger_entry_on_connection(
                    conn,
                    entry_type=MANUAL_TRADE_CORRECTION_ENTRY_TYPE,
                    timestamp=str(plan["effective_at"]),
                    amount=float(Decimal(str(plan["cash_delta"]))),
                    symbol=str(plan["symbol"]),
                    quantity=float(quantity_delta),
                    commission=0.0,
                    correction_payload_json=serialize_event_payload_json(plan),
                    asset_class=str(plan["asset_class"]),
                    note=(
                        "Append-only correction derived from canonical replay; "
                        f"manual trade {trade_id}."
                    ),
                    source=MANUAL_TRADE_CORRECTION_SOURCE,
                    source_ref=f"trade:{trade_id}",
                    created_at=created_at,
                )
                self._inject("after_correction_entry")
                correction = conn.execute(
                    "SELECT * FROM ledger_entries WHERE id = ?",
                    (correction_id,),
                ).fetchone()
                if correction is None:
                    raise RuntimeError("manual trade correction could not be reloaded")
                valuation = self._valuation_transaction_writer(
                    conn,
                    candidate_ledger_rows=[dict(correction)],
                )
                self._inject("after_valuation")
                complete_portfolio_mutation(
                    conn,
                    command_id=command.command_id,
                    result={
                        "trade_id": trade_id,
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
        return ManualTradeCorrectionResult(
            trade_id=trade_id,
            correction_ledger_entry_id=correction_id,
        )

    def _inject(self, stage: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage)


def _validate_existing_correction(
    correction: dict[str, Any],
    *,
    trade_id: int,
    original_entry_id: int,
) -> None:
    from server.projections.manual_trade_correction import (
        MANUAL_TRADE_CORRECTION_ENTRY_TYPE,
        MANUAL_TRADE_CORRECTION_PLAN_SCHEMA_VERSION,
        MANUAL_TRADE_CORRECTION_SOURCE,
    )

    try:
        import json

        payload = json.loads(str(correction["correction_payload_json"]))
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("existing manual trade correction is invalid") from None
    if (
        correction.get("entry_type") != MANUAL_TRADE_CORRECTION_ENTRY_TYPE
        or correction.get("source") != MANUAL_TRADE_CORRECTION_SOURCE
        or correction.get("source_ref") != f"trade:{trade_id}"
        or payload.get("schema_version") != MANUAL_TRADE_CORRECTION_PLAN_SCHEMA_VERSION
        or str(payload.get("trade_id") or "") != str(trade_id)
        or payload.get("original_ledger_entry_ids") != [original_entry_id]
        or correction.get("symbol") != payload.get("symbol")
        or payload.get("arbitrary_financial_input_used") is not False
    ):
        raise RuntimeError("existing manual trade correction is invalid")


def _replay_manual_trade_record(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    command: ManualTradeWrite,
) -> ManualTradeWriteResult:
    try:
        trade_id = int(payload["trade_id"])
        ledger_entry_id = int(payload["ledger_entry_id"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("manual trade mutation result is invalid") from None
    trade = load_trade_projection(conn, trade_id)
    ledger = load_trade_ledger_entry(conn, trade_id)
    if trade is None or ledger is None or int(ledger["id"]) != ledger_entry_id:
        raise RuntimeError("manual trade mutation result drifted")
    validate_trade_projection(trade, ledger)
    _validate_manual_trade_ledger(ledger, command)
    validate_portfolio_mutation_valuation(conn, payload)
    return ManualTradeWriteResult(
        trade=trade,
        ledger_entry_id=ledger_entry_id,
        replayed=True,
    )


def _replay_manual_trade_correction(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    trade_id: int,
) -> ManualTradeCorrectionResult:
    try:
        stored_trade_id = int(payload["trade_id"])
        correction_id = int(payload["correction_ledger_entry_id"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("manual trade correction result is invalid") from None
    if stored_trade_id != trade_id:
        raise RuntimeError("manual trade correction result drifted")
    trade = load_trade_projection(conn, trade_id)
    original = load_trade_ledger_entry(conn, trade_id)
    correction = conn.execute(
        "SELECT * FROM ledger_entries WHERE id = ?",
        (correction_id,),
    ).fetchone()
    if trade is None or original is None or correction is None:
        raise RuntimeError("manual trade correction result drifted")
    validate_trade_projection(trade, original)
    _validate_existing_correction(
        dict(correction),
        trade_id=trade_id,
        original_entry_id=int(original["id"]),
    )
    validate_portfolio_mutation_valuation(conn, payload)
    return ManualTradeCorrectionResult(
        trade_id=trade_id,
        correction_ledger_entry_id=correction_id,
        replayed=True,
    )


def _validate_manual_trade_ledger(
    ledger: dict[str, Any],
    command: ManualTradeWrite,
) -> None:
    checks = {
        "gross_amount": Decimal(str(ledger.get("gross_amount")))
        == Decimal(str(command.gross_amount)),
        "amount": Decimal(str(ledger.get("amount")))
        == Decimal(str(command.gross_amount)),
        "net_cash_impact": Decimal(str(ledger.get("net_cash_impact")))
        == Decimal(str(command.net_cash_impact)),
        "fee_breakdown_json": str(ledger.get("fee_breakdown_json") or "")
        == command.fee_breakdown_json,
        "fee_rule_id": str(ledger.get("fee_rule_id") or "") == command.fee_rule_id,
        "fee_rule_version": str(ledger.get("fee_rule_version") or "")
        == command.fee_rule_version,
        "cost_basis_method": str(ledger.get("cost_basis_method") or "")
        == command.cost_basis_method,
        "note": str(ledger.get("note") or "") == command.note,
    }
    drifted = [field for field, matches in checks.items() if not matches]
    if drifted:
        raise RuntimeError("manual trade ledger drifted: " + ",".join(drifted))


__all__ = ["ManualTradeUnitOfWork"]
