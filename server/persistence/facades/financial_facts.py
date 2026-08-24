"""Financial Facts database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.persistence.facades.base import DatabaseRepositoryAccess


class FinancialFactDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Latest Quotes ----------

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

    async def get_latest_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取单个标的最新行情快照。"""
        return await self._financial_facts.get_latest_quote(symbol)

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]:
        """同步获取各标的最新行情快照，供启动恢复使用。"""
        return self._financial_facts.get_latest_quotes_sync()

    def list_quote_snapshots_sync(self) -> list[dict[str, Any]]:
        """List append-only quote observations for canonical snapshot selection."""
        return self._financial_facts.list_quote_snapshots_sync()

    def get_recent_quote_snapshots_sync(
        self, symbol: str, limit: int = 2
    ) -> list[dict[str, Any]]:
        """同步获取单个标的最近的行情快照序列。"""
        return self._financial_facts.get_recent_quote_snapshots_sync(symbol, limit)

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
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None:
        """获取某日之前最近一个交易日收盘基准。"""
        return self._financial_facts.get_latest_daily_close_before_sync(
            symbol, trade_date
        )

    def get_latest_market_bar_before_date_sync(
        self, symbol: str, trade_date: str, frequency: str = "1d"
    ) -> dict[str, Any] | None:
        """Read the latest daily OHLC bar before trade_date from the data store."""
        return self._financial_facts.get_latest_market_bar_before_date_sync(
            symbol, trade_date, frequency
        )

    def get_market_bar_on_date_sync(
        self, symbol: str, trade_date: str, frequency: str = "1d"
    ) -> dict[str, Any] | None:
        """Read the daily OHLC bar on trade_date from the data store."""
        return self._financial_facts.get_market_bar_on_date_sync(
            symbol, trade_date, frequency
        )

    def get_latest_quote_before_date_sync(
        self, symbol: str, trade_date: str
    ) -> dict[str, Any] | None:
        """获取某日之前最近一个交易日的最后一条报价快照。"""
        return self._financial_facts.get_latest_quote_before_date_sync(
            symbol, trade_date
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

    async def add_cash_flow(
        self, timestamp: str, amount: float, flow_type: str = "deposit", note: str = ""
    ) -> int:
        """添加资金流水记录，返回 ID。"""
        return await self._financial_facts.add_cash_flow(
            timestamp, amount, flow_type, note
        )

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

    async def delete_cash_flow(self, flow_id: int) -> bool:
        """删除资金流水记录。"""
        return await self._financial_facts.delete_cash_flow(flow_id)

    # ---------- Trades ----------

    async def add_trade(
        self,
        timestamp: str,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        commission: float = 0.0,
        asset_class: str = "stock",
        note: str = "",
    ) -> int:
        """添加交易记录，返回 ID。"""
        return await self._financial_facts.add_trade(
            timestamp, symbol, direction, quantity, price, commission, asset_class, note
        )

    def add_trade_sync(
        self,
        *,
        timestamp: str,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        commission: float = 0.0,
        asset_class: str = "stock",
        note: str = "",
    ) -> int:
        """同步添加交易记录，供后台确认任务使用。"""
        return self._financial_facts.add_trade_sync(
            timestamp=timestamp,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=price,
            commission=commission,
            asset_class=asset_class,
            note=note,
        )

    async def get_trades(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出交易记录，最新优先。"""
        return await self._financial_facts.get_trades(limit, offset)

    def get_trades_sync(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """同步列出交易记录，最新优先。"""
        return self._financial_facts.get_trades_sync(limit, offset)

    async def delete_trade(self, trade_id: int) -> bool:
        """删除交易记录。"""
        return await self._financial_facts.delete_trade(trade_id)

    # ---------- Pending Fund Orders ----------

    def add_pending_fund_order_sync(
        self,
        *,
        submitted_at: str,
        symbol: str,
        display_name: str,
        amount: float,
        commission: float = 0.0,
        asset_class: str = "fund",
        target_trade_date: str,
        status: str = "pending",
        note: str = "",
    ) -> int:
        """同步写入待确认基金申购，等待确认净值发布后转交易。"""
        return self._financial_facts.add_pending_fund_order_sync(
            submitted_at=submitted_at,
            symbol=symbol,
            display_name=display_name,
            amount=amount,
            commission=commission,
            asset_class=asset_class,
            target_trade_date=target_trade_date,
            status=status,
            note=note,
        )

    def get_pending_fund_orders_sync(
        self, status: str = "pending"
    ) -> list[dict[str, Any]]:
        """同步读取待确认基金申购。"""
        return self._financial_facts.get_pending_fund_orders_sync(status)

    def mark_pending_fund_order_confirmed_sync(
        self,
        *,
        order_id: int,
        trade_id: int,
        confirmed_nav: float,
        confirmed_quantity: float,
        confirmed_trade_date: str,
    ) -> None:
        """标记待确认基金申购已转正式交易。"""
        return self._financial_facts.mark_pending_fund_order_confirmed_sync(
            order_id=order_id,
            trade_id=trade_id,
            confirmed_nav=confirmed_nav,
            confirmed_quantity=confirmed_quantity,
            confirmed_trade_date=confirmed_trade_date,
        )

    async def get_total_deposits(self) -> float:
        """所有入金总额（deposit - withdraw）。"""
        return await self._financial_facts.get_total_deposits()

    def get_total_deposits_sync(self) -> float:
        """同步版本，供后台线程调用。"""
        return self._financial_facts.get_total_deposits_sync()

    # ---------- Ledger Entries ----------

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
