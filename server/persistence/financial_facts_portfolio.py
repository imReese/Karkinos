"""Portfolio snapshot, cash-flow, trade, and pending-order facts."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from server.contracts.portfolio_cash_flows import (
    CashFlowCorrectionResult,
    CashFlowCorrectionWrite,
    CashFlowWrite,
    CashFlowWriteResult,
)
from server.contracts.portfolio_trades import (
    ManualTradeCorrectionResult,
    ManualTradeCorrectionWrite,
    ManualTradeWrite,
    ManualTradeWriteResult,
    PendingFundConfirmationResult,
    PendingFundConfirmationWrite,
    PendingFundOrderWrite,
    PendingFundOrderWriteResult,
)
from server.persistence.database_serialization import metadata_payload_value
from server.persistence.event_log import insert_event_sync
from server.persistence.manual_trade_uow import ManualTradeUnitOfWork
from server.persistence.pending_fund_confirmation_uow import (
    PendingFundConfirmationUnitOfWork,
)
from server.persistence.portfolio_cash_flow_repository import (
    load_cash_flow_ledger_entry,
    validate_cash_flow_projection,
)
from server.persistence.portfolio_cash_flow_uow import PortfolioCashFlowUnitOfWork
from server.persistence.portfolio_trade_repository import (
    load_trade_ledger_entry,
    validate_trade_projection,
)


class PortfolioFactsRepositoryMixin:
    def save_portfolio_snapshot_sync(
        self,
        cash: float,
        total_equity: float,
        positions_json: str,
        allocation_json: str,
    ) -> None:
        """同步写入组合快照（后台线程调用）。"""
        timestamp = self._now().isoformat()
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                """INSERT INTO portfolio_snapshots
                   (timestamp, cash, total_equity, positions_json, allocation_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    cash,
                    total_equity,
                    positions_json,
                    allocation_json,
                ),
            )
            snapshot_id = cursor.lastrowid or 0
            insert_event_sync(
                conn,
                event_type="portfolio.snapshot.created",
                timestamp=timestamp,
                entity_type="portfolio",
                entity_id="default",
                source="portfolio_snapshots",
                source_ref=str(snapshot_id),
                payload={
                    "snapshot_id": snapshot_id,
                    "portfolio_id": "default",
                    "timestamp": timestamp,
                    "cash": cash,
                    "total_equity": total_equity,
                    "positions": metadata_payload_value(positions_json),
                    "allocation": metadata_payload_value(allocation_json),
                },
            )
            conn.commit()

    def record_cash_flow_sync(self, command: CashFlowWrite) -> CashFlowWriteResult:
        """Commit one canonical cash flow and its compatibility projection."""

        return self._cash_flow_uow().record(command)

    def correct_cash_flow_sync(
        self, command: CashFlowCorrectionWrite
    ) -> CashFlowCorrectionResult:
        """Append one inverse ledger fact without deleting source history."""

        return self._cash_flow_uow().correct(command)

    async def get_cash_flows(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List active, ledger-validated compatibility projections."""

        return await asyncio.to_thread(self.get_cash_flows_sync, limit, offset)

    def get_cash_flows_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List active cash-flow projections and fail closed on drift."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT flow.*
                FROM cash_flows AS flow
                WHERE NOT EXISTS (
                    SELECT 1 FROM ledger_entries AS correction
                    WHERE correction.source = 'portfolio_cash_flow_correction'
                      AND correction.source_ref = 'cash_flow:' || flow.id
                )
                ORDER BY flow.id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                cash_flow = dict(row)
                ledger = load_cash_flow_ledger_entry(conn, int(cash_flow["id"]))
                if ledger is None:
                    raise RuntimeError(
                        "cash flow has no canonical ledger owner; migration required"
                    )
                validate_cash_flow_projection(cash_flow, ledger)
                result.append(cash_flow)
            return result

    def record_manual_trade_sync(
        self,
        command: ManualTradeWrite,
    ) -> ManualTradeWriteResult:
        """Commit one canonical trade and its compatibility projection."""

        return self._manual_trade_uow().record(command)

    def correct_manual_trade_sync(
        self,
        command: ManualTradeCorrectionWrite,
    ) -> ManualTradeCorrectionResult:
        """Append a replay-derived correction without deleting history."""

        return self._manual_trade_uow().correct(command)

    async def get_trades(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List compatibility projections only after canonical-ledger validation."""

        return await asyncio.to_thread(self.get_trades_sync, limit, offset)

    def get_trades_sync(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List ledger-backed trade projections and fail closed on drift."""

        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT trade.*
                FROM trades AS trade
                WHERE NOT EXISTS (
                    SELECT 1 FROM ledger_entries AS correction
                    WHERE correction.source = 'manual_trade_correction'
                      AND correction.source_ref = 'trade:' || trade.id
                )
                ORDER BY trade.id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                trade = dict(row)
                ledger = load_trade_ledger_entry(conn, int(trade["id"]))
                if ledger is None:
                    raise RuntimeError(
                        "manual trade has no canonical ledger owner; migration required"
                    )
                validate_trade_projection(trade, ledger)
                result.append(trade)
            return result

    def create_pending_fund_order_sync(
        self,
        command: PendingFundOrderWrite,
    ) -> PendingFundOrderWriteResult:
        """Create or replay one restart-stable pending fund subscription."""

        return self._pending_fund_uow().create_pending(command)

    def get_pending_fund_orders_sync(
        self, status: str = "pending"
    ) -> list[dict[str, Any]]:
        """同步读取待确认基金申购。"""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM pending_fund_orders
                WHERE status = ?
                ORDER BY submitted_at ASC, id ASC
                """,
                (status,),
            ).fetchall()
            return [dict(row) for row in rows]

    def confirm_pending_fund_order_sync(
        self,
        command: PendingFundConfirmationWrite,
    ) -> PendingFundConfirmationResult:
        """Atomically publish one resolved pending fund subscription."""

        return self._pending_fund_uow().confirm(command)

    def _manual_trade_uow(self) -> ManualTradeUnitOfWork:
        return ManualTradeUnitOfWork(
            self._path,
            now=lambda: self._now().isoformat(),
            valuation_transaction_writer=self._valuation_transaction_writer,
        )

    def _pending_fund_uow(self) -> PendingFundConfirmationUnitOfWork:
        return PendingFundConfirmationUnitOfWork(
            self._path,
            now=lambda: self._now().isoformat(),
            valuation_transaction_writer=self._valuation_transaction_writer,
        )

    def _cash_flow_uow(self) -> PortfolioCashFlowUnitOfWork:
        return PortfolioCashFlowUnitOfWork(
            self._path,
            now=lambda: self._now().isoformat(),
            valuation_transaction_writer=self._valuation_transaction_writer,
        )

    async def get_total_deposits(self) -> float:
        """Read canonical net external contributions."""

        return await asyncio.to_thread(self.get_total_deposits_sync)

    def get_total_deposits_sync(self) -> float:
        """Read net deposits from canonical ledger facts only."""
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute("""
                SELECT COALESCE(SUM(
                    CASE
                        WHEN entry_type IN ('cash_deposit', 'deposit') THEN amount
                        WHEN entry_type IN (
                            'cash_withdrawal', 'cash_withdraw', 'withdraw'
                        ) THEN -amount
                        ELSE 0
                    END
                ), 0)
                FROM ledger_entries
                """)
            row = cursor.fetchone()
            return float(row[0]) if row else 0.0


__all__ = ["PortfolioFactsRepositoryMixin"]
