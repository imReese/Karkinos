"""Financial Facts database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.contracts.ledger_mutations import (
    LedgerAppendCommand,
    LedgerMutationResult,
    LedgerTradeSettlementCommand,
)
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
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.persistence.facades.base import DatabaseRepositoryAccess


class FinancialFactDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Latest Quotes ----------

    def persist_quote_ingestion_sync(
        self,
        command: QuoteIngestionCommand,
    ) -> dict[str, Any]:
        """Stage or atomically publish one complete quote observation."""

        return self._financial_facts.persist_quote_ingestion_sync(command)

    def upsert_latest_quote_sync(
        self,
        *,
        symbol: str,
        asset_type: str = "stock",
        price: float,
        quote_timestamp: str,
        captured_at: str | None = None,
        previous_close: float | None = None,
        change: float | None = None,
        change_percent: float | None = None,
        volume: float | None = None,
        turnover: float | None = None,
        quote_source: str | None = None,
        provider_name: str | None = None,
        provider_status: str | None = None,
        quote_status: str = "live",
        stale_reason: str | None = None,
        captured_reason: str | None = None,
        nav_date: str | None = None,
        fetch_run_id: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Upsert the current materialized quote for one instrument."""
        return self._financial_facts.upsert_latest_quote_sync(
            symbol=symbol,
            asset_type=asset_type,
            price=price,
            quote_timestamp=quote_timestamp,
            captured_at=captured_at,
            previous_close=previous_close,
            change=change,
            change_percent=change_percent,
            volume=volume,
            turnover=turnover,
            quote_source=quote_source,
            provider_name=provider_name,
            provider_status=provider_status,
            quote_status=quote_status,
            stale_reason=stale_reason,
            captured_reason=captured_reason,
            nav_date=nav_date,
            fetch_run_id=fetch_run_id,
            metadata=metadata,
        )

    def get_latest_quote_sync(
        self, symbol: str, asset_type: str | None = None
    ) -> dict[str, Any] | None:
        """Read the materialized latest quote for one symbol."""
        return self._financial_facts.get_latest_quote_sync(symbol, asset_type)

    def list_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """List materialized latest quotes newest first."""
        return self._financial_facts.list_latest_quotes_sync()

    # ---------- Quote Snapshots ----------

    def save_quote_snapshot_sync(
        self,
        symbol: str,
        asset_class: str,
        price: float,
        volume: float | None,
        timestamp: str,
        quote_source: str | None = None,
        provider_name: str | None = None,
        quote_status: str | None = None,
        stale_reason: str | None = None,
        provider_status: str | None = None,
        captured_reason: str | None = None,
        nav_date: str | None = None,
        fetch_run_id: str | None = None,
    ) -> None:
        """同步写入实时行情快照（后台线程调用）。"""
        return self._financial_facts.save_quote_snapshot_sync(
            symbol,
            asset_class,
            price,
            volume,
            timestamp,
            quote_source,
            provider_name,
            quote_status,
            stale_reason,
            provider_status,
            captured_reason,
            nav_date,
            fetch_run_id,
        )

    async def get_latest_quote(
        self,
        symbol: str,
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        """获取单个精确标的身份的最新行情快照。"""
        return await self._financial_facts.get_latest_quote(
            symbol,
            instrument_type=instrument_type,
        )

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """同步获取各标的最新行情快照，供启动恢复使用。"""
        return self._financial_facts.get_latest_quotes_sync()

    def list_quote_snapshots_sync(
        self,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Page append-only quote observations for explicit audit workflows."""
        return self._financial_facts.list_quote_snapshots_sync(limit, offset)

    def list_quote_selection_candidates_sync(self) -> list[dict[str, Any]]:
        """List the bounded persisted frontier used by canonical valuation."""
        return self._financial_facts.list_quote_selection_candidates_sync()

    def get_recent_quote_snapshots_sync(
        self,
        symbol: str,
        limit: int = 2,
        *,
        instrument_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """同步获取单个标的最近的行情快照序列。"""
        return self._financial_facts.get_recent_quote_snapshots_sync(
            symbol,
            limit,
            instrument_type=instrument_type,
        )

    def get_historical_price_matrix_sync(
        self,
        *,
        instrument_keys: list[object] | None = None,
        symbols: list[str] | None = None,
        start_date: str,
        end_date: str,
        symbol_batch_size: int = 400,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read one bounded matrix of persisted historical price evidence."""

        return self._financial_facts.get_historical_price_matrix_sync(
            instrument_keys=instrument_keys,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            symbol_batch_size=symbol_batch_size,
        )

    def save_daily_close_snapshot_sync(
        self,
        *,
        symbol: str,
        asset_class: str,
        trade_date: str,
        close_price: float,
        source: str,
    ) -> None:
        """同步写入日收盘基准。"""
        return self._financial_facts.save_daily_close_snapshot_sync(
            symbol=symbol,
            asset_class=asset_class,
            trade_date=trade_date,
            close_price=close_price,
            source=source,
        )

    def get_latest_daily_close_before_sync(
        self,
        symbol: str,
        trade_date: str,
        instrument_type: str | None = None,
    ) -> dict[str, Any] | None:
        """获取某日之前最近一个交易日收盘基准。"""
        return self._financial_facts.get_latest_daily_close_before_sync(
            symbol,
            trade_date,
            instrument_type,
        )

    def get_latest_market_bar_before_date_sync(
        self,
        symbol: str,
        trade_date: str,
        frequency: str = "1d",
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        """Read the latest daily OHLC bar before trade_date from the data store."""
        return self._financial_facts.get_latest_market_bar_before_date_sync(
            symbol,
            trade_date,
            frequency,
            instrument_type=instrument_type,
        )

    def get_market_bar_on_date_sync(
        self,
        symbol: str,
        trade_date: str,
        frequency: str = "1d",
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        """Read the daily OHLC bar on trade_date from the data store."""
        return self._financial_facts.get_market_bar_on_date_sync(
            symbol,
            trade_date,
            frequency,
            instrument_type=instrument_type,
        )

    def get_latest_quote_before_date_sync(
        self,
        symbol: str,
        trade_date: str,
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        """获取某日之前最近一个交易日的最后一条报价快照。"""
        return self._financial_facts.get_latest_quote_before_date_sync(
            symbol,
            trade_date,
            instrument_type=instrument_type,
        )

    # ---------- Portfolio Snapshots ----------

    def save_portfolio_snapshot_sync(
        self,
        cash: float,
        total_equity: float,
        positions_json: str,
        allocation_json: str,
    ) -> None:
        """同步写入组合快照（后台线程调用）。"""
        return self._financial_facts.save_portfolio_snapshot_sync(
            cash, total_equity, positions_json, allocation_json
        )

    # ---------- Cash Flows ----------

    def record_cash_flow_sync(self, command: CashFlowWrite) -> CashFlowWriteResult:
        """Commit one canonical cash-flow transaction."""

        return self._financial_facts.record_cash_flow_sync(command)

    def correct_cash_flow_sync(
        self, command: CashFlowCorrectionWrite
    ) -> CashFlowCorrectionResult:
        """Append an inverse ledger fact without deleting history."""

        return self._financial_facts.correct_cash_flow_sync(command)

    async def get_cash_flows(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出资金流水，最新优先。"""
        return await self._financial_facts.get_cash_flows(limit, offset)

    def get_cash_flows_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步列出资金流水，最新优先。"""
        return self._financial_facts.get_cash_flows_sync(limit, offset)

    # ---------- Trades ----------

    def record_manual_trade_sync(
        self,
        command: ManualTradeWrite,
    ) -> ManualTradeWriteResult:
        """Commit one canonical manual trade transaction."""

        return self._financial_facts.record_manual_trade_sync(command)

    def correct_manual_trade_sync(
        self,
        command: ManualTradeCorrectionWrite,
    ) -> ManualTradeCorrectionResult:
        """Append an exact correction while retaining original history."""

        return self._financial_facts.correct_manual_trade_sync(command)

    async def get_trades(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出交易记录，最新优先。"""
        return await self._financial_facts.get_trades(limit, offset)

    def get_trades_sync(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """同步列出交易记录，最新优先。"""
        return self._financial_facts.get_trades_sync(limit, offset)

    # ---------- Pending Fund Orders ----------

    def create_pending_fund_order_sync(
        self,
        command: PendingFundOrderWrite,
    ) -> PendingFundOrderWriteResult:
        """Create or replay one pending fund order."""

        return self._financial_facts.create_pending_fund_order_sync(command)

    def get_pending_fund_orders_sync(
        self, status: str = "pending"
    ) -> list[dict[str, Any]]:
        """同步读取待确认基金申购。"""
        return self._financial_facts.get_pending_fund_orders_sync(status)

    def confirm_pending_fund_order_sync(
        self,
        command: PendingFundConfirmationWrite,
    ) -> PendingFundConfirmationResult:
        """Atomically confirm one pending fund order."""

        return self._financial_facts.confirm_pending_fund_order_sync(command)

    async def get_total_deposits(self) -> float:
        """所有入金总额（deposit - withdraw）。"""
        return await self._financial_facts.get_total_deposits()

    def get_total_deposits_sync(self) -> float:
        """同步版本，供后台线程调用。"""
        return self._financial_facts.get_total_deposits_sync()

    # ---------- Ledger Entries ----------

    def append_ledger_entry_sync(
        self,
        command: LedgerAppendCommand,
    ) -> LedgerMutationResult:
        """Append or replay one explicit operator ledger request atomically."""

        return self._financial_facts.append_ledger_entry_sync(command)

    def settle_ledger_trade_sync(
        self,
        command: LedgerTradeSettlementCommand,
    ) -> LedgerMutationResult:
        """CAS-confirm or replay one explicit operator settlement request."""

        return self._financial_facts.settle_ledger_trade_sync(command)

    def insert_ledger_entry_sync(
        self,
        *,
        entry_type: str,
        timestamp: str,
        amount: float | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        quantity: float | None = None,
        price: float | None = None,
        commission: float = 0.0,
        gross_amount: float | None = None,
        net_cash_impact: float | None = None,
        fee_breakdown_json: str | None = None,
        fee_rule_id: str | None = None,
        fee_rule_version: str | None = None,
        cost_basis_method: str | None = None,
        asset_class: str = "stock",
        note: str = "",
        source: str = "manual",
        source_ref: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """同步写入账本事件。"""
        return self._financial_facts.insert_ledger_entry_sync(
            entry_type=entry_type,
            timestamp=timestamp,
            amount=amount,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=price,
            commission=commission,
            gross_amount=gross_amount,
            net_cash_impact=net_cash_impact,
            fee_breakdown_json=fee_breakdown_json,
            fee_rule_id=fee_rule_id,
            fee_rule_version=fee_rule_version,
            cost_basis_method=cost_basis_method,
            asset_class=asset_class,
            note=note,
            source=source,
            source_ref=source_ref,
            created_at=created_at,
        )

    def get_ledger_entries_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步列出账本事件，最新优先。"""
        return self._financial_facts.get_ledger_entries_sync(limit, offset)

    def get_all_ledger_entries_sync(self) -> list[dict[str, Any]]:
        """Read one complete ledger snapshot for a bounded evaluation."""

        return self._financial_facts.get_all_ledger_entries_sync()

    def get_ledger_entry_sync(self, entry_id: int) -> dict[str, Any] | None:
        """Read one ledger event by id."""
        return self._financial_facts.get_ledger_entry_sync(entry_id)

    def confirm_ledger_trade_settlement_sync(
        self,
        *,
        entry_id: int,
        commission: float,
        net_cash_impact: float,
        fee_breakdown_json: str,
        settled_at: str,
        settlement_source: str,
        settlement_source_ref: str,
        settlement_note: str = "",
        fee_rule_id: str = "broker_settlement_confirmation",
        fee_rule_version: str = "broker_settlement_confirmation.v1",
    ) -> dict[str, Any]:
        """Confirm broker-settled trade costs while preserving the estimate."""
        return self._financial_facts.confirm_ledger_trade_settlement_sync(
            entry_id=entry_id,
            commission=commission,
            net_cash_impact=net_cash_impact,
            fee_breakdown_json=fee_breakdown_json,
            settled_at=settled_at,
            settlement_source=settlement_source,
            settlement_source_ref=settlement_source_ref,
            settlement_note=settlement_note,
            fee_rule_id=fee_rule_id,
            fee_rule_version=fee_rule_version,
        )
