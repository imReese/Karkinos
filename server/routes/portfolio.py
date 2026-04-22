"""Portfolio routes — /api/portfolio/*"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
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
    ExplainabilityBridgeItem,
    ExplainabilityDriver,
    ExplainabilityPositionDriver,
    ExplainabilityResponse,
    ExplainabilityTimelineEvent,
    ExplainabilityTimelinePoint,
    LiveHoldingGroupResponse,
    LiveHoldingItemResponse,
    LiveHoldingsResponse,
    PortfolioSnapshot,
    PositionResponse,
    RiskConcentrationItem,
    RiskDrawdownPoint,
    RiskDrawdownSummary,
    RiskExposureBucket,
    RiskMetricItem,
    RiskSummaryItem,
    RiskWorkspaceResponse,
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
from server.services.risk_workspace import build_risk_workspace

logger = logging.getLogger(__name__)

_ASSET_CLASS_LABELS = {
    "stock": "A股",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
}


def _normalize_asset_class(value: str | None) -> str:
    if not value:
        return "other"
    normalized = str(value).strip().lower()
    if normalized in {"stock", "fund", "etf", "gold", "bond", "cash"}:
        return normalized
    return "other"


def _resolve_display_name(state, symbol: str, fallback: str | None = None) -> str:
    for asset_cfg in getattr(state.config, "assets", []):
        if asset_cfg.get("symbol") == symbol:
            return str(asset_cfg.get("display_name") or asset_cfg["symbol"])
    return fallback or symbol


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


def _build_recent_drivers(entries: list[dict]) -> list[ExplainabilityDriver]:
    drivers: list[ExplainabilityDriver] = []
    for entry in entries:
        entry_type = entry.get("entry_type")
        symbol = entry.get("symbol")
        amount = entry.get("amount")
        title = entry_type or "ledger"
        detail = entry.get("note") or "Ledger activity"

        if entry_type == "cash_deposit":
            title = "Cash deposited"
            detail = entry.get("note") or "Capital added to the portfolio."
        elif entry_type == "cash_withdrawal":
            title = "Cash withdrawn"
            detail = entry.get("note") or "Capital removed from the portfolio."
        elif entry_type == "trade_buy":
            title = f"Bought {symbol}"
            detail = f"{entry.get('quantity') or 0:g} @ {entry.get('price') or 0:g}"
        elif entry_type == "trade_sell":
            title = f"Sold {symbol}"
            detail = f"{entry.get('quantity') or 0:g} @ {entry.get('price') or 0:g}"
        elif entry_type == "dividend":
            title = f"Dividend from {symbol}"
            detail = entry.get("note") or "Cash income recorded from holdings."
        elif entry_type == "manual_adjustment":
            title = "Manual adjustment"
            detail = entry.get("note") or "Manual valuation or position adjustment."

        drivers.append(
            ExplainabilityDriver(
                kind=entry_type or "ledger",
                title=title,
                detail=detail,
                timestamp=entry["timestamp"],
                symbol=symbol,
                amount=float(amount) if amount is not None else None,
            )
        )
    return drivers


def _build_timeline(
    equity_curve: list[EquityPoint],
    entries: list[dict],
    *,
    event_kind: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[ExplainabilityTimelinePoint]:
    if not equity_curve:
        return []

    events_by_date: dict[str, list[ExplainabilityTimelineEvent]] = defaultdict(list)
    external_flow_by_date: dict[str, float] = defaultdict(float)

    for entry in entries:
        timestamp = str(entry.get("timestamp") or "")
        if not timestamp:
            continue
        event_date = timestamp.split("T")[0]
        entry_type = entry.get("entry_type") or "ledger"
        if event_kind and entry_type != event_kind:
            continue
        symbol = entry.get("symbol")
        amount = float(entry.get("amount") or 0.0)
        category = "portfolio"
        impact_source = "market"

        title = entry_type.replace("_", " ").title()
        detail = entry.get("note") or "Ledger activity"
        if entry_type == "cash_deposit":
            title = "Cash deposited"
            detail = entry.get("note") or "Capital added to the portfolio."
            external_flow_by_date[event_date] += amount
            category = "capital"
            impact_source = "external"
        elif entry_type == "cash_withdrawal":
            title = "Cash withdrawn"
            detail = entry.get("note") or "Capital removed from the portfolio."
            external_flow_by_date[event_date] -= abs(amount)
            amount = -abs(amount)
            category = "capital"
            impact_source = "external"
        elif entry_type == "dividend":
            title = f"Dividend from {symbol}"
            detail = entry.get("note") or "Cash income recorded from holdings."
            external_flow_by_date[event_date] += amount
            category = "income"
            impact_source = "cash"
        elif entry_type == "manual_adjustment":
            title = "Manual adjustment"
            detail = entry.get("note") or "Manual ledger override applied."
            external_flow_by_date[event_date] += amount
            category = "override"
            impact_source = "manual"
        elif entry_type == "trade_buy":
            title = f"Bought {symbol}"
            detail = f"{entry.get('quantity') or 0:g} @ {entry.get('price') or 0:g}"
            amount = None
            category = "trade"
            impact_source = "positioning"
        elif entry_type == "trade_sell":
            title = f"Sold {symbol}"
            detail = f"{entry.get('quantity') or 0:g} @ {entry.get('price') or 0:g}"
            amount = None
            category = "trade"
            impact_source = "positioning"

        events_by_date[event_date].append(
            ExplainabilityTimelineEvent(
                category=category,
                impact_source=impact_source,
                kind=entry_type,
                title=title,
                detail=detail,
                timestamp=timestamp,
                symbol=symbol,
                amount=amount,
            )
        )

    timeline: list[ExplainabilityTimelinePoint] = []
    previous_equity: float | None = None
    for point in equity_curve:
        point_date = point.timestamp.split("T")[0]
        if from_date and point_date < from_date:
            previous_equity = point.equity
            continue
        if to_date and point_date > to_date:
            continue
        delta = 0.0 if previous_equity is None else point.equity - previous_equity
        external_flow = external_flow_by_date.get(point_date, 0.0)
        market_pnl = 0.0 if previous_equity is None else delta - external_flow
        timeline.append(
            ExplainabilityTimelinePoint(
                date=point_date,
                equity=point.equity,
                delta=delta,
                external_flow=external_flow,
                market_pnl=market_pnl,
                events=events_by_date.get(point_date, []),
            )
        )
        previous_equity = point.equity

    return timeline


def _build_position_drivers(
    snapshot: PortfolioSnapshot, entries: list[dict]
) -> list[ExplainabilityPositionDriver]:
    by_symbol: dict[str, dict] = {}
    for entry in entries:
        symbol = entry.get("symbol")
        if not symbol:
            continue
        previous = by_symbol.get(symbol)
        if previous is None or entry["timestamp"] > previous["timestamp"]:
            by_symbol[symbol] = entry

    asset_class_by_symbol = {
        item.symbol: item.asset_class for item in snapshot.allocation if item.asset_class != "cash"
    }
    drivers: list[ExplainabilityPositionDriver] = []
    for position in snapshot.positions:
        last_entry = by_symbol.get(position.symbol, {})
        drivers.append(
            ExplainabilityPositionDriver(
                symbol=position.symbol,
                asset_class=asset_class_by_symbol.get(position.symbol, "stock"),
                quantity=position.quantity,
                avg_cost=position.avg_cost,
                market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl,
                realized_pnl=position.realized_pnl,
                last_activity_at=last_entry.get("timestamp"),
                last_activity_note=last_entry.get("note"),
            )
        )
    return drivers


def _build_equity_bridge(
    snapshot: PortfolioSnapshot, summary: AccountOverview
) -> list[ExplainabilityBridgeItem]:
    market_value = max(snapshot.total_equity - snapshot.cash, 0)
    total_pnl = summary.realized_pnl + summary.unrealized_pnl
    return [
        ExplainabilityBridgeItem(
            key="deposits",
            label="Net Deposits",
            value=snapshot.total_deposits,
            detail="External capital recorded through deposits and withdrawals.",
        ),
        ExplainabilityBridgeItem(
            key="realized",
            label="Realized PnL",
            value=summary.realized_pnl,
            detail="Closed trade outcome already locked in.",
        ),
        ExplainabilityBridgeItem(
            key="unrealized",
            label="Unrealized PnL",
            value=summary.unrealized_pnl,
            detail="Mark-to-market move on current positions.",
        ),
        ExplainabilityBridgeItem(
            key="cash",
            label="Cash",
            value=snapshot.cash,
            detail="Immediate buffer available for redeployment.",
        ),
        ExplainabilityBridgeItem(
            key="market_value",
            label="Market Value",
            value=market_value,
            detail="Current marked value of open positions.",
        ),
        ExplainabilityBridgeItem(
            key="equity",
            label="Total Equity",
            value=snapshot.total_equity,
            detail=f"Deposits plus total PnL ({total_pnl:.2f}).",
        ),
    ]


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


def _hydrate_missing_position_quotes(
    state,
    portfolio,
    instruments: dict,
) -> tuple[object, dict, bool]:
    if portfolio is None:
        return portfolio, instruments, False

    latest_quotes = _collect_latest_quotes(state)
    missing: list[tuple[str, object]] = []
    for sym in portfolio.positions:
        symbol = str(sym)
        if symbol in latest_quotes:
            continue
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        asset_class = getattr(instrument, "asset_class", None)
        if asset_class is None:
            continue
        missing.append((symbol, asset_class))

    if not missing:
        return portfolio, instruments, False

    from server.routes.market import _fetch_latest_snapshot

    hydrated = False
    for symbol, asset_class in missing:
        snapshot = _fetch_latest_snapshot(state, symbol, asset_class)
        if snapshot:
            latest_quotes[symbol] = snapshot
            hydrated = True

    if not hydrated or state.db is None:
        return portfolio, instruments, hydrated

    rebuilt = rebuild_portfolio_from_ledger(
        state.config,
        state.db,
        latest_quotes=latest_quotes,
    )
    return rebuilt.portfolio, rebuilt.instruments, True


def _get_recent_quote_snapshots(state, symbol: str, limit: int = 2) -> list[dict]:
    if (
        state.db is None
        or not hasattr(state.db, "get_recent_quote_snapshots_sync")
    ):
        return []
    rows = state.db.get_recent_quote_snapshots_sync(symbol, limit=limit)
    return rows if isinstance(rows, list) else []


def _resolve_live_holding_baseline(
    state, symbol: str, latest_quote: dict | None
) -> tuple[float | None, str | None, str]:
    latest_timestamp = latest_quote.get("timestamp") if latest_quote else None
    trade_date = (
        str(latest_timestamp).split("T")[0]
        if latest_timestamp
        else datetime.now().date().isoformat()
    )

    if state.db is not None and hasattr(state.db, "get_latest_daily_close_before_sync"):
        daily_close = state.db.get_latest_daily_close_before_sync(symbol, trade_date)
        if daily_close:
            return (
                float(daily_close["close_price"]),
                daily_close.get("trade_date"),
                "previous_close",
            )

    if state.db is not None and hasattr(state.db, "get_latest_quote_before_date_sync"):
        fallback_quote = state.db.get_latest_quote_before_date_sync(symbol, trade_date)
        if fallback_quote:
            if hasattr(state.db, "save_daily_close_snapshot_sync"):
                state.db.save_daily_close_snapshot_sync(
                    symbol=symbol,
                    asset_class=str(fallback_quote.get("asset_class") or "stock"),
                    trade_date=str(fallback_quote["timestamp"]).split("T")[0],
                    close_price=float(fallback_quote["price"]),
                    source="quote_fallback",
                )
            return (
                float(fallback_quote["price"]),
                fallback_quote.get("timestamp"),
                "fallback_close",
            )

    return None, None, "unavailable"


def _build_live_holdings_response(state) -> LiveHoldingsResponse:
    portfolio, instruments = _resolve_projection_sources(state)
    portfolio, instruments, _ = _hydrate_missing_position_quotes(
        state,
        portfolio,
        instruments,
    )
    if portfolio is None:
        return LiveHoldingsResponse(groups=[])

    latest_quotes = _collect_latest_quotes(state)
    groups: dict[str, list[LiveHoldingItemResponse]] = defaultdict(list)

    for sym, pos in portfolio.positions.items():
        quantity = float(pos.quantity)
        if quantity == 0:
            continue

        symbol = str(sym)
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        latest_quote = latest_quotes.get(symbol, {})
        asset_class = _normalize_asset_class(
            latest_quote.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", None)
        )
        latest_price = latest_quote.get("price")
        latest_price_value = float(latest_price) if latest_price not in {None, ""} else None
        baseline_price, baseline_timestamp, baseline_source = _resolve_live_holding_baseline(
            state,
            symbol,
            latest_quote if latest_quote else None,
        )
        avg_cost = float(pos.avg_cost)
        market_value = float(pos.market_value)
        cost_basis = quantity * avg_cost
        since_buy_pnl = market_value - cost_basis
        since_buy_pnl_pct = None if cost_basis == 0 else since_buy_pnl / cost_basis
        today_change = None
        today_change_pct = None
        if baseline_price not in {None, 0}:
            today_change = quantity * ((latest_price_value or avg_cost) - baseline_price)
            today_change_pct = ((latest_price_value or avg_cost) / baseline_price) - 1

        groups[asset_class].append(
            LiveHoldingItemResponse(
                symbol=symbol,
                name=_resolve_display_name(
                    state,
                    symbol,
                    getattr(instrument, "name", symbol),
                ),
                asset_class=asset_class,
                quantity=quantity,
                avg_cost=avg_cost,
                market_value=market_value,
                latest_price=latest_price_value,
                quote_timestamp=latest_quote.get("timestamp"),
                since_buy_pnl=since_buy_pnl,
                since_buy_pnl_pct=since_buy_pnl_pct,
                today_change=today_change,
                today_change_pct=today_change_pct,
                baseline_price=baseline_price,
                baseline_timestamp=baseline_timestamp,
                baseline_source=baseline_source,
                quote_status="live" if latest_price_value is not None else "stale",
            )
        )

    response_groups: list[LiveHoldingGroupResponse] = []
    for asset_class, items in groups.items():
        items.sort(key=lambda item: item.market_value, reverse=True)
        response_groups.append(
            LiveHoldingGroupResponse(
                asset_class=asset_class,
                label=_ASSET_CLASS_LABELS.get(asset_class, asset_class.upper()),
                total_market_value=sum(item.market_value for item in items),
                total_today_change=sum(item.today_change or 0.0 for item in items),
                total_since_buy_pnl=sum(item.since_buy_pnl for item in items),
                items=items,
            )
        )

    response_groups.sort(key=lambda group: -group.total_market_value)
    return LiveHoldingsResponse(groups=response_groups)


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
        portfolio, instruments, _ = _hydrate_missing_position_quotes(
            state,
            portfolio,
            instruments,
        )

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
                name = _resolve_display_name(state, pos.symbol, name)

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

    @r.get("/live-holdings", response_model=LiveHoldingsResponse)
    async def get_live_holdings() -> LiveHoldingsResponse:
        """按资产类别返回当前持仓的实时价格、累计收益和日内变化。"""
        from server.app import get_app_state

        state = get_app_state()
        return _build_live_holdings_response(state)

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

    @r.get("/explainability", response_model=ExplainabilityResponse)
    async def get_explainability(
        limit: int = 50,
        from_date: str | None = None,
        to_date: str | None = None,
        event_kind: str | None = None,
    ) -> ExplainabilityResponse:
        """Return traceable drivers for equity, PnL, and current positions."""
        from server.app import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        summary = await get_overview()
        equity_curve = await get_equity_curve()

        entries = []
        if state.db is not None and hasattr(state.db, "get_ledger_entries_sync"):
            entries = state.db.get_ledger_entries_sync(limit=limit, offset=0)

        return ExplainabilityResponse(
            equity_bridge=_build_equity_bridge(snapshot, summary),
            recent_drivers=_build_recent_drivers(entries),
            positions=_build_position_drivers(snapshot, entries),
            timeline=_build_timeline(
                equity_curve,
                entries,
                event_kind=event_kind,
                from_date=from_date,
                to_date=to_date,
            ),
        )

    @r.get("/risk-workspace", response_model=RiskWorkspaceResponse)
    async def get_risk_workspace() -> RiskWorkspaceResponse:
        """Return richer drawdown, exposure, and concentration diagnostics."""
        snapshot = await get_portfolio()
        equity_curve = await get_equity_curve()
        return build_risk_workspace(snapshot, equity_curve)

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
