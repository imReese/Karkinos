"""Atomic, evidence-bound unit of work for pending fund subscriptions."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from server.contracts.portfolio_mutations import PortfolioMutationConflict
from server.contracts.portfolio_trades import (
    ManualTradeWrite,
    PendingFundConfirmationResult,
    PendingFundConfirmationWrite,
    PendingFundOrderWrite,
    PendingFundOrderWriteResult,
)
from server.contracts.quote_ingestion import PUBLISHED_QUOTE_RUN_STATUSES
from server.persistence.event_log import insert_event_sync
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
    load_pending_order,
    load_trade_ledger_entry,
    load_trade_projection,
    validate_manual_trade_write,
    validate_trade_projection,
)
from server.persistence.valuation_transaction import ValuationTransactionWriter

_CONFIRMED_FUND_NAV_SOURCES = {
    "eastmoney_fund_page",
    "tushare_fund_nav",
}
FailureInjector = Callable[[str], None]


class PendingFundConfirmationUnitOfWork:
    """Own pending creation and explicit evidence-bound confirmation."""

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

    def create_pending(
        self,
        command: PendingFundOrderWrite,
    ) -> PendingFundOrderWriteResult:
        """Create one request-idempotent pending subscription and asset identity."""

        _validate_pending_order(command)
        created_at = self._now()
        with sqlite3.connect(self._database_path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = claim_portfolio_mutation(
                    conn,
                    command=command,
                    mutation_kind="pending_fund_order.create",
                    created_at=created_at,
                )
                if replay is not None:
                    result = _replay_pending_creation(conn, replay, command)
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
                cursor = conn.execute(
                    """
                    INSERT INTO pending_fund_orders (
                        submitted_at, symbol, display_name, amount, commission,
                        asset_class, target_trade_date, status, note, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        command.submitted_at,
                        command.symbol,
                        command.display_name,
                        command.amount,
                        command.commission,
                        command.asset_class,
                        command.target_trade_date,
                        command.note,
                        created_at,
                        created_at,
                    ),
                )
                order_id = int(cursor.lastrowid or 0)
                self._inject("after_pending_order")
                insert_event_sync(
                    conn,
                    event_type="portfolio.pending_fund_order.created",
                    timestamp=command.submitted_at,
                    entity_type="pending_fund_order",
                    entity_id=str(order_id),
                    source="pending_fund_orders",
                    source_ref=str(order_id),
                    payload={
                        "order_id": order_id,
                        "command_id": command.command_id,
                        "operator_id": command.operator_id,
                        "symbol": command.symbol,
                        "asset_class": command.asset_class,
                        "target_trade_date": command.target_trade_date,
                        "status": "pending",
                    },
                )
                self._inject("after_pending_event")
                order = load_pending_order(conn, order_id)
                if order is None:
                    raise RuntimeError("pending fund order could not be reloaded")
                complete_portfolio_mutation(
                    conn,
                    command_id=command.command_id,
                    result={"order_id": order_id},
                    completed_at=self._now(),
                )
                self._inject("after_claim_completion")
                self._inject("before_pending_commit")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return PendingFundOrderWriteResult(order=order)

    def confirm(
        self,
        command: PendingFundConfirmationWrite,
    ) -> PendingFundConfirmationResult:
        """Confirm from immutable NAV evidence without provider or runtime input."""

        _validate_confirmation_request(command)
        created_at = self._now()
        with sqlite3.connect(self._database_path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = claim_portfolio_mutation(
                    conn,
                    command=command,
                    mutation_kind="pending_fund_order.confirm",
                    created_at=created_at,
                )
                order = load_pending_order(conn, command.order_id)
                if order is None:
                    raise KeyError(f"pending fund order not found: {command.order_id}")
                evidence = _load_confirmed_nav_evidence(conn, order, command)
                trade_command = _derive_confirmed_trade(order, evidence, command)
                validate_manual_trade_write(trade_command)
                if replay is not None:
                    result = _load_confirmed_result(
                        conn,
                        order,
                        evidence,
                        trade_command,
                        command,
                    )
                    if (
                        int(replay.get("order_id") or 0) != command.order_id
                        or int(replay.get("ledger_entry_id") or 0)
                        != result.ledger_entry_id
                        or int(replay.get("trade_id") or 0) != int(result.trade["id"])
                    ):
                        raise RuntimeError("pending fund confirmation result drifted")
                    validate_portfolio_mutation_valuation(conn, replay)
                    conn.rollback()
                    return result
                self._inject("after_claim")
                if order["status"] == "confirmed":
                    raise PortfolioMutationConflict(
                        "pending fund order was already confirmed by another command"
                    )
                if order["status"] != "pending":
                    raise RuntimeError(
                        f"pending fund order status is not confirmable: {order['status']}"
                    )

                insert_asset_identity_if_missing(
                    conn,
                    symbol=trade_command.symbol,
                    asset_class=trade_command.asset_class,
                    display_name=trade_command.display_name,
                    created_at=created_at,
                )
                self._inject("after_confirmation_asset_identity")
                trade_id = insert_trade_projection(
                    conn,
                    trade_command,
                    created_at=created_at,
                )
                self._inject("after_trade_projection")
                ledger_entry_id = insert_ledger_entry_on_connection(
                    conn,
                    entry_type="trade_buy",
                    timestamp=trade_command.timestamp,
                    amount=trade_command.gross_amount,
                    symbol=trade_command.symbol,
                    direction="buy",
                    quantity=trade_command.quantity,
                    price=trade_command.price,
                    commission=trade_command.commission,
                    gross_amount=trade_command.gross_amount,
                    net_cash_impact=trade_command.net_cash_impact,
                    fee_breakdown_json=trade_command.fee_breakdown_json,
                    fee_rule_id=trade_command.fee_rule_id,
                    fee_rule_version=trade_command.fee_rule_version,
                    cost_basis_method=trade_command.cost_basis_method,
                    asset_class=trade_command.asset_class,
                    note=trade_command.note,
                    source="portfolio_trade",
                    source_ref=f"trade:{trade_id}",
                    created_at=created_at,
                )
                self._inject("after_ledger_entry")
                cursor = conn.execute(
                    """
                    UPDATE pending_fund_orders
                    SET status = 'confirmed', confirmed_nav = ?,
                        confirmed_quantity = ?, confirmed_trade_date = ?,
                        trade_id = ?, confirmation_quote_snapshot_id = ?,
                        confirmation_fetch_run_id = ?, confirmed_by = ?,
                        confirmation_note = ?, updated_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (
                        trade_command.price,
                        trade_command.quantity,
                        evidence["nav_date"],
                        trade_id,
                        evidence["id"],
                        evidence["fetch_run_id"],
                        command.operator_id,
                        command.confirmation_note,
                        created_at,
                        command.order_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "pending fund order confirmation lost serialization"
                    )
                self._inject("after_pending_status")
                insert_event_sync(
                    conn,
                    event_type="portfolio.pending_fund_order.confirmed",
                    timestamp=created_at,
                    entity_type="pending_fund_order",
                    entity_id=str(command.order_id),
                    source="pending_fund_orders",
                    source_ref=str(command.order_id),
                    payload={
                        "order_id": command.order_id,
                        "trade_id": trade_id,
                        "ledger_entry_id": ledger_entry_id,
                        "symbol": trade_command.symbol,
                        "confirmed_trade_date": evidence["nav_date"],
                        "quote_snapshot_id": evidence["id"],
                        "fetch_run_id": evidence["fetch_run_id"],
                        "command_id": command.command_id,
                        "confirmed_by": command.operator_id,
                        "confirmation_note": command.confirmation_note,
                        "status": "confirmed",
                    },
                )
                self._inject("after_confirmation_event")
                confirmed_order = load_pending_order(conn, command.order_id)
                trade = load_trade_projection(conn, trade_id)
                ledger = load_trade_ledger_entry(conn, trade_id)
                if confirmed_order is None or trade is None or ledger is None:
                    raise RuntimeError("confirmed fund facts could not be reloaded")
                validate_trade_projection(trade, ledger)
                _validate_confirmed_ledger(ledger, trade_command)
                valuation = self._valuation_transaction_writer(
                    conn,
                    candidate_ledger_rows=[ledger],
                )
                self._inject("after_valuation")
                complete_portfolio_mutation(
                    conn,
                    command_id=command.command_id,
                    result={
                        "order_id": command.order_id,
                        "trade_id": trade_id,
                        "ledger_entry_id": ledger_entry_id,
                        "valuation_snapshot_id": valuation["snapshot_id"],
                        "valuation_snapshot_status": valuation["status"],
                    },
                    completed_at=self._now(),
                )
                self._inject("after_claim_completion")
                self._inject("before_confirmation_commit")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return PendingFundConfirmationResult(
            order=confirmed_order,
            trade=trade,
            ledger_entry_id=ledger_entry_id,
        )

    def _inject(self, stage: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage)


def _load_confirmed_nav_evidence(
    conn: sqlite3.Connection,
    order: dict[str, Any],
    command: PendingFundConfirmationWrite,
) -> dict[str, Any]:
    instrument_key = InstrumentKey.from_values(
        order["symbol"],
        InstrumentType.OPEN_END_FUND,
    )
    rows = conn.execute(
        """
        SELECT quote.*, run.status AS run_status, run.trigger AS run_trigger,
               run.metadata_json AS run_metadata_json
        FROM quote_snapshots AS quote
        JOIN quote_fetch_runs AS run ON run.run_id = quote.fetch_run_id
        WHERE quote.fetch_run_id = ?
          AND quote.symbol = ?
          AND quote.instrument_type = ?
        ORDER BY quote.id ASC
        """,
        (command.evidence_fetch_run_id, *instrument_key.storage_tuple()),
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError("confirmed NAV evidence must identify exactly one snapshot")
    evidence = dict(rows[0])
    try:
        metadata = json.loads(str(evidence.get("run_metadata_json") or "{}"))
    except json.JSONDecodeError:
        raise RuntimeError("confirmed NAV run metadata is invalid") from None
    if not isinstance(metadata, dict):
        raise RuntimeError("confirmed NAV run metadata is invalid")
    checks = {
        "run_status": str(evidence.get("run_status") or "")
        in PUBLISHED_QUOTE_RUN_STATUSES,
        "run_trigger": str(evidence.get("run_trigger") or "") == "fund_nav_sync",
        "confirmation_only": metadata.get("confirmation_only") is True,
        "manual_explicit_trigger": metadata.get("manual_explicit_trigger") is True,
        "quote_source": str(evidence.get("quote_source") or "").lower()
        in _CONFIRMED_FUND_NAV_SOURCES,
        "provider_status": str(evidence.get("provider_status") or "").lower() == "live",
        "quote_status": str(evidence.get("quote_status") or "").lower()
        in {"live", "confirmed"},
        "stale_reason": evidence.get("stale_reason") in {None, ""},
        "captured_reason": str(evidence.get("captured_reason") or "")
        == "fund_nav_sync",
        "nav_date": bool(str(evidence.get("nav_date") or "")),
        "price": float(evidence.get("price") or 0.0) > 0,
    }
    failed = [field for field, matches in checks.items() if not matches]
    if failed:
        raise RuntimeError(
            "confirmed NAV evidence is not authoritative: " + ",".join(failed)
        )
    if str(evidence["nav_date"]) < str(order["target_trade_date"]):
        raise RuntimeError("confirmed NAV evidence predates target trade date")
    return evidence


def _derive_confirmed_trade(
    order: dict[str, Any],
    evidence: dict[str, Any],
    command: PendingFundConfirmationWrite,
) -> ManualTradeWrite:
    amount = Decimal(str(order["amount"]))
    commission = Decimal(str(order.get("commission") or 0))
    net_amount = amount - commission
    price = Decimal(str(evidence["price"]))
    if net_amount <= 0 or price <= 0:
        raise RuntimeError("confirmed fund subscription economics are invalid")
    quantity = net_amount / price
    fee = _decimal_string(commission)
    fee_breakdown = json.dumps(
        {
            "commission": fee,
            "other_fees": "0",
            "stamp_tax": "0",
            "total_fee": fee,
            "transfer_fee": "0",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    evidence_note = (
        "Explicitly confirmed persisted fund NAV: "
        f"fetch_run_id={evidence['fetch_run_id']}; "
        f"quote_snapshot_id={evidence['id']}; "
        f"nav_date={evidence['nav_date']}; "
        f"confirmed_by={command.operator_id}."
    )
    note = " | ".join(
        part
        for part in (
            str(order.get("note") or "").strip(),
            command.confirmation_note.strip(),
            evidence_note,
        )
        if part
    )
    return ManualTradeWrite(
        command_id=command.command_id,
        operator_id=command.operator_id,
        timestamp=str(order["submitted_at"]),
        symbol=str(order["symbol"]),
        display_name=str(order["display_name"]),
        direction="buy",
        quantity=float(quantity),
        price=float(price),
        commission=float(commission),
        gross_amount=float(net_amount),
        net_cash_impact=-float(amount),
        fee_breakdown_json=fee_breakdown,
        fee_rule_id="manual_fee_input",
        fee_rule_version="manual_fee_input",
        asset_class="fund",
        note=note,
    )


def _load_confirmed_result(
    conn: sqlite3.Connection,
    order: dict[str, Any],
    evidence: dict[str, Any],
    trade_command: ManualTradeWrite,
    command: PendingFundConfirmationWrite,
) -> PendingFundConfirmationResult:
    trade_id = int(order.get("trade_id") or 0)
    if trade_id <= 0:
        raise RuntimeError("confirmed pending fund order has no trade projection")
    trade = load_trade_projection(conn, trade_id)
    ledger = load_trade_ledger_entry(conn, trade_id)
    if trade is None or ledger is None:
        raise RuntimeError("confirmed pending fund order facts are incomplete")
    validate_trade_projection(trade, ledger)
    _validate_confirmed_ledger(ledger, trade_command)
    checks = {
        "confirmed_nav": Decimal(str(order.get("confirmed_nav")))
        == Decimal(str(trade_command.price)),
        "confirmed_quantity": Decimal(str(order.get("confirmed_quantity")))
        == Decimal(str(trade_command.quantity)),
        "confirmed_trade_date": str(order.get("confirmed_trade_date") or "")
        == str(evidence["nav_date"]),
        "confirmation_quote_snapshot_id": int(
            order.get("confirmation_quote_snapshot_id") or 0
        )
        == int(evidence["id"]),
        "confirmation_fetch_run_id": str(order.get("confirmation_fetch_run_id") or "")
        == command.evidence_fetch_run_id,
        "confirmed_by": str(order.get("confirmed_by") or "") == command.operator_id,
        "confirmation_note": str(order.get("confirmation_note") or "")
        == command.confirmation_note,
    }
    if not all(checks.values()):
        drifted = [field for field, matches in checks.items() if not matches]
        raise RuntimeError(
            "confirmed pending fund order replay drifted: " + ",".join(drifted)
        )
    return PendingFundConfirmationResult(
        order=order,
        trade=trade,
        ledger_entry_id=int(ledger["id"]),
        replayed=True,
    )


def _validate_confirmed_ledger(
    ledger: dict[str, Any],
    trade: ManualTradeWrite,
) -> None:
    checks = {
        "gross_amount": Decimal(str(ledger.get("gross_amount")))
        == Decimal(str(trade.gross_amount)),
        "net_cash_impact": Decimal(str(ledger.get("net_cash_impact")))
        == Decimal(str(trade.net_cash_impact)),
        "fee_breakdown_json": str(ledger.get("fee_breakdown_json") or "")
        == trade.fee_breakdown_json,
        "fee_rule_id": str(ledger.get("fee_rule_id") or "") == trade.fee_rule_id,
        "fee_rule_version": str(ledger.get("fee_rule_version") or "")
        == trade.fee_rule_version,
        "cost_basis_method": str(ledger.get("cost_basis_method") or "")
        == trade.cost_basis_method,
        "note": str(ledger.get("note") or "") == trade.note,
    }
    drifted = [field for field, matches in checks.items() if not matches]
    if drifted:
        raise RuntimeError(
            "confirmed pending fund ledger drifted: " + ",".join(drifted)
        )


def _replay_pending_creation(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    command: PendingFundOrderWrite,
) -> PendingFundOrderWriteResult:
    try:
        order_id = int(payload["order_id"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("pending fund mutation result is invalid") from None
    order = load_pending_order(conn, order_id)
    if order is None:
        raise RuntimeError("pending fund mutation result drifted")
    checks = {
        "submitted_at": str(order.get("submitted_at") or "") == command.submitted_at,
        "symbol": str(order.get("symbol") or "") == command.symbol,
        "display_name": str(order.get("display_name") or "") == command.display_name,
        "amount": Decimal(str(order.get("amount"))) == Decimal(str(command.amount)),
        "commission": Decimal(str(order.get("commission")))
        == Decimal(str(command.commission)),
        "asset_class": str(order.get("asset_class") or "") == command.asset_class,
        "target_trade_date": str(order.get("target_trade_date") or "")
        == command.target_trade_date,
        "note": str(order.get("note") or "") == command.note,
    }
    if not all(checks.values()):
        raise RuntimeError("pending fund mutation result drifted")
    return PendingFundOrderWriteResult(order=order, replayed=True)


def _validate_pending_order(command: PendingFundOrderWrite) -> None:
    if not command.command_id.strip():
        raise ValueError("command_id is required")
    if not command.operator_id.strip():
        raise ValueError("operator_id is required")
    if not command.symbol.strip() or not command.display_name.strip():
        raise ValueError("pending fund identity is required")
    if command.asset_class != "fund":
        raise ValueError("pending subscriptions are fund-only")
    if not math.isfinite(command.amount) or not math.isfinite(command.commission):
        raise ValueError("pending fund financial values must be finite")
    if command.amount <= 0 or command.commission < 0:
        raise ValueError("pending fund amount must cover a non-negative commission")
    if command.amount <= command.commission:
        raise ValueError("pending fund net subscription amount must be positive")


def _validate_confirmation_request(command: PendingFundConfirmationWrite) -> None:
    if not command.command_id.strip():
        raise ValueError("command_id is required")
    if not command.operator_id.strip():
        raise ValueError("operator_id is required")
    if command.order_id <= 0:
        raise ValueError("order_id must be positive")
    if not command.evidence_fetch_run_id.strip():
        raise ValueError("evidence_fetch_run_id is required")


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


__all__ = ["PendingFundConfirmationUnitOfWork"]
