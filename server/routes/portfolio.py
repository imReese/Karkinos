"""Portfolio routes — /api/portfolio/*"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter

from core.types import ZERO, Symbol
from server.models import (
    AccountStateResponse,
    AccountOverview,
    ActivityItem,
    AllocationGroup,
    AllocationItem,
    CashFlowCreate,
    CashFlowResponse,
    EquityPoint,
    PortfolioSnapshot,
    PositionResponse,
    RiskSummaryItem,
    TradeCreate,
    TradeResponse,
)
from server.projections.service import (
    build_equity_curve_from_db,
    build_portfolio_projection_from_db,
)
from server.services.account_state import build_account_state_projection
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.risk_engine import build_risk_summary

logger = logging.getLogger(__name__)

_ASSET_CLASS_LABELS = {
    "stock": "A股",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
}


def _build_grouped_allocation(
    allocation: list[AllocationItem], total_equity: float
) -> list[AllocationGroup]:
    """按 asset_class 聚合 allocation 列表。"""
    groups: dict[str, list[AllocationItem]] = defaultdict(list)
    for item in allocation:
        groups[item.asset_class].append(item)

    result = []
    for ac, items in groups.items():
        group_value = sum(i.value for i in items)
        result.append(
            AllocationGroup(
                asset_class=ac,
                name=_ASSET_CLASS_LABELS.get(ac, ac),
                value=group_value,
                weight=group_value / total_equity if total_equity > 0 else 0,
                items=items,
            )
        )
    # 现金排第一，其余按市值降序
    result.sort(key=lambda g: (g.asset_class != "cash", -g.value))
    return result


def _build_activity_items(
    trades: list[dict], cash_flows: list[dict]
) -> list[ActivityItem]:
    items: list[ActivityItem] = []

    for trade in trades:
        action = "买入" if trade["direction"] == "buy" else "卖出"
        items.append(
            ActivityItem(
                kind="trade",
                title=f"{action} {trade['symbol']}",
                detail=f"{trade['quantity']:.0f} 股 @ ¥{trade['price']:.2f}",
                timestamp=trade["timestamp"],
                amount=float(trade["quantity"] * trade["price"]),
                symbol=trade["symbol"],
            )
        )

    for flow in cash_flows:
        flow_title = "入金" if flow["flow_type"] == "deposit" else "出金"
        items.append(
            ActivityItem(
                kind="cash_flow",
                title=flow_title,
                detail=flow.get("note") or "手工记录资金流水",
                timestamp=flow["timestamp"],
                amount=float(flow["amount"]),
            )
        )

    items.sort(key=lambda item: item.timestamp, reverse=True)
    return items


def _collect_latest_quote_timestamps(state) -> dict[str, str]:
    latest: dict[str, str] = {}
    scheduler = state.scheduler
    if scheduler and getattr(scheduler, "latest_quotes", None):
        for symbol, quote in scheduler.latest_quotes.items():
            timestamp = quote.get("timestamp")
            if timestamp:
                latest[str(symbol)] = timestamp

    if state.db is not None and hasattr(state.db, "get_latest_quotes_sync"):
        for row in state.db.get_latest_quotes_sync():
            timestamp = row.get("timestamp")
            symbol = row.get("symbol")
            if symbol and timestamp and str(symbol) not in latest:
                latest[str(symbol)] = timestamp

    return latest


def _collect_latest_quotes(state) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    scheduler = state.scheduler
    if scheduler and getattr(scheduler, "latest_quotes", None):
        for symbol, quote in scheduler.latest_quotes.items():
            latest[str(symbol)] = quote

    if state.db is not None and hasattr(state.db, "get_latest_quotes_sync"):
        for row in state.db.get_latest_quotes_sync():
            symbol = row.get("symbol")
            if symbol and str(symbol) not in latest:
                latest[str(symbol)] = row

    return latest


def _has_rows(rows: list[dict]) -> bool:
    return len(rows) > 0


def _resolve_projection_sources(state) -> tuple[object | None, dict]:
    scheduler = state.scheduler
    portfolio = scheduler.portfolio if scheduler else None
    instruments = scheduler.instruments if scheduler else {}

    if portfolio is not None or state.db is None:
        return portfolio, instruments

    latest_quotes = _collect_latest_quotes(state)
    legacy_cash_flows = (
        state.db.get_cash_flows_sync(limit=1, offset=0)
        if hasattr(state.db, "get_cash_flows_sync")
        else []
    )
    legacy_trades = (
        state.db.get_trades_sync(limit=1, offset=0)
        if hasattr(state.db, "get_trades_sync")
        else []
    )

    if _has_rows(legacy_cash_flows) or _has_rows(legacy_trades):
        rebuilt = rebuild_portfolio_from_ledger(
            state.config,
            state.db,
            latest_quotes=latest_quotes,
        )
        return rebuilt.portfolio, rebuilt.instruments

    ledger_entries = (
        state.db.get_ledger_entries_sync(limit=1, offset=0)
        if hasattr(state.db, "get_ledger_entries_sync")
        else []
    )
    if _has_rows(ledger_entries):
        return (
            build_portfolio_projection_from_db(
                state.db,
                initial_cash=state.config.initial_cash,
                latest_quotes=latest_quotes,
            ),
            {},
        )

    return None, {}


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    @r.get("", response_model=PortfolioSnapshot)
    async def get_portfolio() -> PortfolioSnapshot:
        """获取当前持仓 + 现金 + 总权益 + 资产配置。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler
        portfolio, instruments = _resolve_projection_sources(state)

        if portfolio is None:
            return PortfolioSnapshot(
                cash=float(state.config.initial_cash),
                total_equity=float(state.config.initial_cash),
                total_deposits=0.0,
                positions=[],
                allocation=[],
                allocation_grouped=[],
            )

        positions: list[PositionResponse] = []
        for sym, pos in portfolio.positions.items():
            positions.append(
                PositionResponse(
                    symbol=str(sym),
                    quantity=float(pos.quantity),
                    available_qty=float(pos.available_qty),
                    frozen_qty=float(pos.frozen_qty),
                    avg_cost=float(pos.avg_cost),
                    market_value=float(pos.market_value),
                    unrealized_pnl=float(pos.unrealized_pnl),
                    realized_pnl=float(pos.realized_pnl),
                    commission_paid=float(pos.commission_paid),
                )
            )

        # 计算总权益
        total_equity = float(portfolio.cash)
        for pos in positions:
            total_equity += pos.market_value

        # 计算配置
        allocation: list[AllocationItem] = []
        if total_equity > 0:
            # 现金配置
            allocation.append(
                AllocationItem(
                    symbol="CASH",
                    name="现金",
                    weight=float(portfolio.cash) / total_equity,
                    value=float(portfolio.cash),
                    asset_class="cash",
                )
            )
            # 持仓配置
            for pos in positions:
                ac = "stock"
                if scheduler:
                    for sym, asset_class in scheduler.watchlist:
                        if str(sym) == pos.symbol:
                            ac = asset_class.value
                            break
                if pos.symbol in {
                    str(symbol) for symbol, instrument in instruments.items()
                    if getattr(instrument, "asset_class", None) is not None
                }:
                    instrument = instruments.get(Symbol(pos.symbol))
                    if instrument is not None:
                        ac = instrument.asset_class.value
                name = pos.symbol
                if Symbol(pos.symbol) in instruments:
                    name = instruments[Symbol(pos.symbol)].name

                allocation.append(
                    AllocationItem(
                        symbol=pos.symbol,
                        name=name,
                        weight=pos.market_value / total_equity,
                        value=pos.market_value,
                        asset_class=ac,
                    )
                )

        allocation_grouped = _build_grouped_allocation(allocation, total_equity)

        if hasattr(portfolio, "total_deposits"):
            total_deposits = float(portfolio.total_deposits)
        elif state.db is not None:
            total_deposits = await state.db.get_total_deposits()
        else:
            total_deposits = 0.0

        return PortfolioSnapshot(
            cash=float(portfolio.cash),
            total_equity=total_equity,
            total_deposits=total_deposits,
            positions=positions,
            allocation=allocation,
            allocation_grouped=allocation_grouped,
        )

    @r.get("/positions", response_model=list[PositionResponse])
    async def get_positions() -> list[PositionResponse]:
        """获取投影后的持仓列表。"""
        snapshot = await get_portfolio()
        return snapshot.positions

    @r.get("/allocation", response_model=list[AllocationItem])
    async def get_allocation() -> list[AllocationItem]:
        """获取资产配置权重。"""
        snapshot = await get_portfolio()
        return snapshot.allocation

    @r.get("/overview", response_model=AccountOverview)
    async def get_overview() -> AccountOverview:
        """获取首页账户总览投影。"""
        from server.app import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        projection = build_account_state_projection(
            snapshot,
            build_risk_summary(snapshot, _collect_latest_quote_timestamps(state)),
        )
        return projection.summary

    @r.get("/state", response_model=AccountStateResponse)
    async def get_account_state() -> AccountStateResponse:
        """获取规范化账户状态投影。"""
        from server.app import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        risks = build_risk_summary(snapshot, _collect_latest_quote_timestamps(state))
        projection = build_account_state_projection(snapshot, risks)
        return AccountStateResponse(
            summary=projection.summary,
            snapshot=projection.snapshot,
            risks=projection.risks,
            next_step=projection.next_step,
        )

    @r.get("/risk-summary", response_model=list[RiskSummaryItem])
    async def get_risk_summary() -> list[RiskSummaryItem]:
        """获取首页风险摘要。"""
        from server.app import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        return build_risk_summary(snapshot, _collect_latest_quote_timestamps(state))

    @r.get("/equity-curve", response_model=list[EquityPoint])
    async def get_equity_curve() -> list[EquityPoint]:
        """获取权益曲线。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler
        portfolio = scheduler.portfolio if scheduler else None

        if portfolio is None:
            if state.db is None:
                return []

            legacy_cash_flows = (
                state.db.get_cash_flows_sync(limit=1, offset=0)
                if hasattr(state.db, "get_cash_flows_sync")
                else []
            )
            legacy_trades = (
                state.db.get_trades_sync(limit=1, offset=0)
                if hasattr(state.db, "get_trades_sync")
                else []
            )
            ledger_entries = (
                state.db.get_ledger_entries_sync(limit=1, offset=0)
                if hasattr(state.db, "get_ledger_entries_sync")
                else []
            )
            if (_has_rows(legacy_cash_flows) or _has_rows(legacy_trades)) or not _has_rows(ledger_entries):
                return []

            points = build_equity_curve_from_db(
                state.db,
                initial_cash=state.config.initial_cash,
                latest_quotes=_collect_latest_quotes(state),
            )
            return [
                EquityPoint(timestamp=ts.isoformat(), equity=float(eq))
                for ts, eq in points
            ]

        return [
            EquityPoint(timestamp=ts.isoformat(), equity=float(eq))
            for ts, eq in portfolio.equity_curve
        ]

    @r.get("/activity", response_model=list[ActivityItem])
    async def get_activity(limit: int = 10) -> list[ActivityItem]:
        """获取首页最近活动流。"""
        from server.app import get_app_state

        state = get_app_state()
        trades = await state.db.get_trades(limit=limit, offset=0)
        flows = await state.db.get_cash_flows(limit=limit, offset=0)
        return _build_activity_items(trades, flows)[:limit]

    # ---------- Cash Flows ----------

    @r.post("/cash-flow", response_model=CashFlowResponse)
    async def create_cash_flow(body: CashFlowCreate) -> CashFlowResponse:
        """记录入金/出金。"""
        from server.app import get_app_state

        state = get_app_state()
        db = state.db

        flow_id = await db.add_cash_flow(
            timestamp=body.timestamp,
            amount=body.amount,
            flow_type=body.flow_type,
            note=body.note,
        )

        # 更新 live portfolio 的 cash
        scheduler = state.scheduler
        if scheduler and scheduler.is_running:
            with scheduler._lock:
                portfolio = scheduler._portfolio
                if portfolio is not None:
                    if body.flow_type == "deposit":
                        portfolio.deposit(Decimal(str(body.amount)))
                    elif body.flow_type == "withdraw":
                        portfolio.withdraw(Decimal(str(body.amount)))

        flows = await db.get_cash_flows(limit=1)
        return CashFlowResponse(**flows[0])

    @r.get("/cash-flows", response_model=list[CashFlowResponse])
    async def list_cash_flows(
        limit: int = 50, offset: int = 0
    ) -> list[CashFlowResponse]:
        """列出资金流水。"""
        from server.app import get_app_state

        state = get_app_state()
        flows = await state.db.get_cash_flows(limit, offset)
        return [CashFlowResponse(**f) for f in flows]

    @r.delete("/cash-flow/{flow_id}")
    async def delete_cash_flow(flow_id: int) -> dict:
        """删除资金流水记录。"""
        from server.app import get_app_state

        state = get_app_state()
        deleted = await state.db.delete_cash_flow(flow_id)
        return {"deleted": deleted}

    # ---------- Trades ----------

    @r.post("/trade", response_model=TradeResponse)
    async def create_trade(body: TradeCreate) -> TradeResponse:
        """记录手动交易，同步更新 Portfolio 持仓。"""
        import uuid
        from datetime import datetime as dt

        from core.events import FillEvent
        from core.types import OrderSide, Symbol
        from server.app import get_app_state

        state = get_app_state()
        db = state.db

        trade_id = await db.add_trade(
            timestamp=body.timestamp,
            symbol=body.symbol,
            direction=body.direction,
            quantity=body.quantity,
            price=body.price,
            commission=body.commission,
            asset_class=body.asset_class,
            note=body.note,
        )

        # If live is running, synthesize FillEvent to update portfolio
        scheduler = state.scheduler
        if scheduler and scheduler.is_running:
            with scheduler._lock:
                portfolio = scheduler._portfolio
                if portfolio is not None:
                    side = OrderSide.BUY if body.direction == "buy" else OrderSide.SELL
                    fill = FillEvent(
                        timestamp=(
                            dt.fromisoformat(body.timestamp)
                            if isinstance(body.timestamp, str)
                            else body.timestamp
                        ),
                        fill_id=f"MANUAL-{uuid.uuid4().hex[:8]}",
                        order_id=f"MANUAL-ORD-{uuid.uuid4().hex[:8]}",
                        symbol=Symbol(body.symbol),
                        side=side,
                        fill_price=Decimal(str(body.price)),
                        fill_quantity=Decimal(str(body.quantity)),
                        commission=Decimal(str(body.commission)),
                        slippage=Decimal("0"),
                    )
                    portfolio.on_fill(fill)

        trades = await db.get_trades(limit=1)
        return TradeResponse(**trades[0])

    @r.get("/trades", response_model=list[TradeResponse])
    async def list_trades(limit: int = 50, offset: int = 0) -> list[TradeResponse]:
        """列出交易记录。"""
        from server.app import get_app_state

        state = get_app_state()
        trades = await state.db.get_trades(limit, offset)
        return [TradeResponse(**t) for t in trades]

    @r.delete("/trade/{trade_id}")
    async def delete_trade(trade_id: int) -> dict:
        """删除交易记录。"""
        from server.app import get_app_state

        state = get_app_state()
        deleted = await state.db.delete_trade(trade_id)
        return {"deleted": deleted}

    return r
