"""Portfolio routes — /api/portfolio/*"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from core.types import AssetClass, BarFrequency, ZERO, Symbol
from server.models import (
    AccountStateResponse,
    AccountOverview,
    ActivityItem,
    AllocationGroup,
    AllocationItem,
    CashFlowCreate,
    CashFlowResponse,
    EquityPoint,
    EquitySeriesPoint,
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
    PendingFundOrderResponse,
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
    build_equity_series_from_db,
    build_portfolio_projection_from_db,
)
from server.services.account_state import build_account_state_projection
from server.services.market_hours import get_shanghai_now, is_cn_trading_session
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.risk_engine import build_risk_summary
from server.services.risk_workspace import build_risk_workspace

logger = logging.getLogger(__name__)
_FUND_SUBSCRIPTION_CUTOFF = time(15, 0)
_CN_MORNING_OPEN = time(9, 30)
_CN_MORNING_CLOSE = time(11, 30)
_CN_AFTERNOON_OPEN = time(13, 0)
_CN_AFTERNOON_CLOSE = time(15, 0)
_INTRADAY_STEP_MINUTES = 5
_SH_TZ = ZoneInfo("Asia/Shanghai")

_INTRADAY_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "fund": AssetClass.FUND,
    "etf": AssetClass.FUND,
}

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


def _persist_runtime_config(config) -> None:
    from server.bootstrap import resolve_config_path

    payload = {
        "host": getattr(config, "host", "0.0.0.0"),
        "port": getattr(config, "port", 8000),
        "live_auto_start": getattr(config, "live_auto_start", True),
        "initial_cash": str(getattr(config, "initial_cash", 0)),
        "start_date": getattr(config, "start_date", ""),
        "end_date": getattr(config, "end_date", ""),
        "assets": getattr(config, "assets", []),
        "strategy": getattr(config, "strategy", "dual_ma"),
        "short_period": getattr(config, "short_period", 5),
        "long_period": getattr(config, "long_period", 20),
        "data_source": getattr(config, "data_source", "akshare"),
        "tushare_token": getattr(config, "tushare_token", ""),
        "notification": getattr(config, "notification", {"type": "console"}),
        "live_poll_interval": getattr(config, "live_poll_interval", 60),
    }
    resolve_config_path().write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _ensure_asset_config(
    state,
    *,
    symbol: str,
    asset_class: str,
    display_name: str | None = None,
) -> None:
    assets = getattr(state.config, "assets", [])
    for asset in assets:
        if asset.get("symbol") == symbol:
            updated = False
            if display_name:
                updated = asset.get("display_name") != display_name
                asset["display_name"] = display_name
            if updated:
                _persist_runtime_config(state.config)
            return

    assets.append(
        {
            "symbol": symbol,
            "asset_class": asset_class,
            "display_name": display_name or symbol,
        }
    )
    _persist_runtime_config(state.config)


def _resolve_fund_buy_fill(
    state,
    *,
    symbol: str,
    timestamp: str,
    gross_amount: float,
    commission: float,
) -> dict:
    from data.manager import build_sources
    from core.types import AssetClass, BarFrequency, Symbol

    submitted_at = datetime.fromisoformat(timestamp)
    target_date = submitted_at.date()
    if submitted_at.time() >= _FUND_SUBSCRIPTION_CUTOFF:
        target_date += timedelta(days=1)

    sources = build_sources(
        data_source=getattr(state.config, "data_source", "akshare"),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    akshare = sources["akshare"]
    symbol_obj = Symbol(symbol.strip())
    display_name = (
        akshare._resolve_open_end_fund_name(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_name")
        else str(symbol_obj)
    ) or str(symbol_obj)
    canonical_symbol = (
        akshare._resolve_open_end_fund_code(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_code")
        else str(symbol_obj)
    ) or str(symbol_obj)

    start = datetime.combine(submitted_at.date() - timedelta(days=1), time.min)
    end = datetime.combine(submitted_at.date() + timedelta(days=10), time.max)
    bars = akshare.fetch_bars(
        Symbol(canonical_symbol),
        start=start,
        end=end,
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.FUND,
    )
    if bars.empty:
        raise ValueError("No fund NAV history available from AKShare")

    eligible = bars[bars["timestamp"].dt.date >= target_date].sort_values("timestamp")
    latest_available = bars["timestamp"].max().date()
    if eligible.empty:
        raise LookupError(
            f"Fund NAV for target trade date {target_date.isoformat()} is not published yet "
            f"(latest available {latest_available.isoformat()})."
        )

    confirmed = eligible.iloc[0]
    confirmed_trade_date = confirmed["timestamp"].date().isoformat()
    confirmed_nav = float(confirmed["close"])
    net_amount = gross_amount - commission
    if net_amount <= 0:
        raise ValueError("Net subscription amount must be positive")
    quantity = net_amount / confirmed_nav
    return {
        "symbol": canonical_symbol,
        "display_name": display_name,
        "price": confirmed_nav,
        "quantity": quantity,
        "confirmed_trade_date": confirmed_trade_date,
        "gross_amount": gross_amount,
        "target_trade_date": target_date.isoformat(),
    }


def _resolve_fund_identity(state, symbol: str) -> dict[str, str]:
    from data.manager import build_sources
    from core.types import Symbol

    sources = build_sources(
        data_source=getattr(state.config, "data_source", "akshare"),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    akshare = sources["akshare"]
    symbol_obj = Symbol(symbol.strip())
    display_name = (
        akshare._resolve_open_end_fund_name(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_name")
        else str(symbol_obj)
    ) or str(symbol_obj)
    canonical_symbol = (
        akshare._resolve_open_end_fund_code(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_code")
        else str(symbol_obj)
    ) or str(symbol_obj)
    return {"symbol": canonical_symbol, "display_name": display_name}


def _fund_target_trade_date(timestamp: str) -> str:
    submitted_at = datetime.fromisoformat(timestamp)
    target_date = submitted_at.date()
    if submitted_at.time() >= _FUND_SUBSCRIPTION_CUTOFF:
        target_date += timedelta(days=1)
    return target_date.isoformat()


def confirm_pending_fund_orders(state) -> int:
    """Try to convert published pending fund subscriptions into normal trades."""
    if state.db is None or not hasattr(state.db, "get_pending_fund_orders_sync"):
        return 0

    confirmed_count = 0
    for order in state.db.get_pending_fund_orders_sync(status="pending"):
        try:
            resolved = _resolve_fund_buy_fill(
                state,
                symbol=order["symbol"],
                timestamp=order["submitted_at"],
                gross_amount=float(order["amount"]),
                commission=float(order.get("commission") or 0.0),
            )
        except (LookupError, ValueError):
            continue

        note_parts = [
            order.get("note") or "",
            f"Auto-confirmed pending fund subscription: gross_amount={resolved['gross_amount']:.2f}",
            f"confirmed_trade_date={resolved['confirmed_trade_date']}",
            f"confirmed_nav={resolved['price']:.6f}",
        ]
        trade_id = state.db.add_trade_sync(
            timestamp=order["submitted_at"],
            symbol=resolved["symbol"],
            direction="buy",
            quantity=resolved["quantity"],
            price=resolved["price"],
            commission=float(order.get("commission") or 0.0),
            asset_class="fund",
            note=" | ".join(part for part in note_parts if part),
        )
        state.db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp=order["submitted_at"],
            amount=resolved["quantity"] * resolved["price"],
            symbol=resolved["symbol"],
            direction="buy",
            quantity=resolved["quantity"],
            price=resolved["price"],
            commission=float(order.get("commission") or 0.0),
            asset_class="fund",
            note=" | ".join(part for part in note_parts if part),
            source="portfolio_trade",
            source_ref=f"trade:{trade_id}",
        )
        state.db.mark_pending_fund_order_confirmed_sync(
            order_id=int(order["id"]),
            trade_id=trade_id,
            confirmed_nav=resolved["price"],
            confirmed_quantity=resolved["quantity"],
            confirmed_trade_date=resolved["confirmed_trade_date"],
        )
        _ensure_asset_config(
            state,
            symbol=resolved["symbol"],
            asset_class="fund",
            display_name=resolved["display_name"],
        )
        confirmed_count += 1
    return confirmed_count


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
        item.symbol: item.asset_class
        for item in snapshot.allocation
        if item.asset_class != "cash"
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


def _parse_quote_timestamp(timestamp: object) -> datetime | None:
    if isinstance(timestamp, datetime):
        parsed = timestamp
    elif isinstance(timestamp, str) and timestamp.strip():
        value = timestamp.strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(f"{value}T00:00:00")
            except ValueError:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SH_TZ)
    return parsed.astimezone(_SH_TZ)


def _previous_weekday(day):
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _expected_quote_date(now: datetime | None = None):
    current = get_shanghai_now(now)
    if current.weekday() >= 5:
        return _previous_weekday(current.date())
    if current.time() < _CN_MORNING_OPEN:
        return _previous_weekday(current.date())
    return current.date()


def _quote_is_stale(
    quote: dict | None,
    *,
    now: datetime | None = None,
    live_poll_interval: int | None = None,
) -> bool:
    if not quote or quote.get("price") in {None, ""}:
        return True

    timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if timestamp is None:
        return True

    current = get_shanghai_now(now)
    if timestamp.date() < _expected_quote_date(current):
        return True

    if is_cn_trading_session(current):
        ttl_seconds = max(int(live_poll_interval or 60), 15) * 3
        return (current - timestamp).total_seconds() > ttl_seconds

    return False


def _quote_status(
    state,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str:
    return (
        "stale"
        if _quote_is_stale(
            quote,
            now=now,
            live_poll_interval=getattr(state.config, "live_poll_interval", 60),
        )
        else "live"
    )


def _can_refresh_quotes(state, now: datetime | None = None) -> bool:
    return bool(hasattr(state.config, "data_source") and is_cn_trading_session(now))


def _asset_class_for_position(
    symbol: str, quote: dict | None, instruments: dict
) -> AssetClass | None:
    raw_asset_class = (quote or {}).get("asset_class")
    if not raw_asset_class and instruments:
        instrument = instruments.get(Symbol(symbol)) or instruments.get(symbol)
        raw_asset_class = getattr(
            getattr(instrument, "asset_class", None), "value", None
        )

    normalized = _normalize_asset_class_value(raw_asset_class)
    if normalized == "etf":
        normalized = AssetClass.FUND.value

    try:
        return AssetClass(normalized)
    except ValueError:
        return None


def _store_runtime_quote(state, symbol: str, quote: dict) -> None:
    scheduler = state.scheduler
    if scheduler is None:
        return

    if hasattr(scheduler, "_latest_quotes"):
        scheduler._latest_quotes[symbol] = quote
        return

    latest_quotes = getattr(scheduler, "latest_quotes", None)
    if isinstance(latest_quotes, dict):
        latest_quotes[symbol] = quote


def _hydrate_missing_position_quotes(
    state,
    portfolio,
    instruments: dict,
) -> tuple[object, dict, bool]:
    if portfolio is None:
        return portfolio, instruments, False

    latest_quotes = _collect_latest_quotes(state)
    refresh_needed: list[tuple[str, AssetClass]] = []
    now = get_shanghai_now()
    can_refresh = _can_refresh_quotes(state, now)
    for sym in portfolio.positions:
        symbol = str(sym)
        quote = latest_quotes.get(symbol)
        if quote:
            is_stale = _quote_is_stale(
                quote,
                now=now,
                live_poll_interval=getattr(state.config, "live_poll_interval", 60),
            )
            if not is_stale or not can_refresh:
                continue
        asset_class = _asset_class_for_position(symbol, quote, instruments)
        if asset_class is None:
            continue
        refresh_needed.append((symbol, asset_class))

    if not refresh_needed:
        return portfolio, instruments, False

    from server.routes.market import _fetch_latest_snapshot

    hydrated = False
    for symbol, asset_class in refresh_needed:
        try:
            snapshot = _fetch_latest_snapshot(state, symbol, asset_class)
        except Exception:
            logger.warning(
                "Failed to refresh stale quote for %s", symbol, exc_info=True
            )
            continue
        if snapshot:
            latest_quotes[symbol] = snapshot
            _store_runtime_quote(state, symbol, snapshot)
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
    if state.db is None or not hasattr(state.db, "get_recent_quote_snapshots_sync"):
        return []
    rows = state.db.get_recent_quote_snapshots_sync(symbol, limit=limit)
    return rows if isinstance(rows, list) else []


def _resolve_live_holding_baseline(
    state, symbol: str, latest_quote: dict | None
) -> tuple[float | None, str | None, str]:
    if latest_quote:
        previous_close = latest_quote.get("previous_close")
        previous_close_date = latest_quote.get("previous_close_date")
        if previous_close not in {None, 0, ""} and previous_close_date not in {
            None,
            "",
        }:
            return (
                float(previous_close),
                str(previous_close_date),
                "previous_close",
            )

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
        latest_price_value = (
            float(latest_price) if latest_price not in {None, ""} else None
        )
        baseline_price, baseline_timestamp, baseline_source = (
            _resolve_live_holding_baseline(
                state,
                symbol,
                latest_quote if latest_quote else None,
            )
        )
        avg_cost = float(pos.avg_cost)
        market_value = float(pos.market_value)
        cost_basis = quantity * avg_cost
        since_buy_pnl = market_value - cost_basis
        since_buy_pnl_pct = None if cost_basis == 0 else since_buy_pnl / cost_basis
        today_change = None
        today_change_pct = None
        if baseline_price not in {None, 0}:
            reference_price = (
                latest_price_value if latest_price_value is not None else avg_cost
            )
            today_change = quantity * (reference_price - baseline_price)
            today_change_pct = (reference_price / baseline_price) - 1

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
                quote_status=_quote_status(state, latest_quote),
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


def _normalize_asset_class_value(value) -> str:
    if hasattr(value, "value"):
        return _normalize_asset_class(getattr(value, "value", None))
    return _normalize_asset_class(str(value) if value is not None else None)


def _combine_session_time(trade_day, session_time: time, tzinfo) -> datetime:
    return datetime.combine(trade_day, session_time, tzinfo=tzinfo)


def _floor_session_timestamp(timestamp: datetime, step_minutes: int) -> datetime:
    return timestamp.replace(
        minute=timestamp.minute - (timestamp.minute % step_minutes),
        second=0,
        microsecond=0,
    )


def _build_cn_session_ticks(
    trade_day,
    tzinfo,
    *,
    full_session: bool = False,
    now: datetime | None = None,
) -> list[datetime]:
    morning_open = _combine_session_time(trade_day, _CN_MORNING_OPEN, tzinfo)
    morning_close = _combine_session_time(trade_day, _CN_MORNING_CLOSE, tzinfo)
    afternoon_open = _combine_session_time(trade_day, _CN_AFTERNOON_OPEN, tzinfo)
    afternoon_close = _combine_session_time(trade_day, _CN_AFTERNOON_CLOSE, tzinfo)
    if full_session:
        effective_end = afternoon_close
    else:
        current = get_shanghai_now(now)
        effective_end = min(
            _floor_session_timestamp(current, _INTRADAY_STEP_MINUTES),
            afternoon_close,
        )
    if effective_end <= morning_open:
        return [morning_open]

    ticks: list[datetime] = []
    for start, end in (
        (morning_open, morning_close),
        (afternoon_open, afternoon_close),
    ):
        if effective_end < start:
            continue
        segment_end = end if full_session else min(end, effective_end)
        current = start
        while current <= segment_end:
            ticks.append(current)
            current += timedelta(minutes=_INTRADAY_STEP_MINUTES)

    return ticks or [morning_open]


def _normalize_intraday_timestamp(timestamp, tzinfo) -> datetime | None:
    if timestamp is None:
        return None
    if hasattr(timestamp, "to_pydatetime"):
        timestamp = timestamp.to_pydatetime()
    elif isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
    if not isinstance(timestamp, datetime):
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=tzinfo)
    return timestamp.astimezone(tzinfo)


def _load_intraday_price_points(
    source,
    *,
    symbol: str,
    asset_class: str,
    start: datetime,
    end: datetime,
    latest_quote: dict | None,
) -> list[tuple[datetime, float]]:
    mapped_asset_class = _INTRADAY_ASSET_CLASS_MAP.get(asset_class)
    if source is None or mapped_asset_class is None:
        return []

    try:
        bars = source.fetch_bars(
            Symbol(symbol),
            start,
            end,
            frequency=BarFrequency.MIN_5,
            asset_class=mapped_asset_class,
        )
    except Exception:
        logger.warning(
            "Failed to load intraday bars for %s (%s)",
            symbol,
            asset_class,
            exc_info=True,
        )
        bars = None

    points: list[tuple[datetime, float]] = []
    if (
        bars is not None
        and len(bars) > 0
        and {"timestamp", "close"}.issubset(bars.columns)
    ):
        for row in bars.itertuples(index=False):
            timestamp = _normalize_intraday_timestamp(
                getattr(row, "timestamp", None),
                start.tzinfo,
            )
            close = getattr(row, "close", None)
            if timestamp is None or close in {None, ""}:
                continue
            points.append((timestamp, float(close)))

    latest_price = latest_quote.get("price") if latest_quote else None
    latest_timestamp = _normalize_intraday_timestamp(
        latest_quote.get("timestamp") if latest_quote else None,
        start.tzinfo,
    )
    if (
        latest_price not in {None, ""}
        and latest_timestamp is not None
        and latest_timestamp.date() == start.date()
        and start <= latest_timestamp <= end
    ):
        points.append((latest_timestamp, float(latest_price)))

    points.sort(key=lambda item: item[0])
    deduped: list[tuple[datetime, float]] = []
    for timestamp, close in points:
        if deduped and deduped[-1][0] == timestamp:
            deduped[-1] = (timestamp, close)
            continue
        deduped.append((timestamp, close))
    return deduped


def _build_intraday_equity_curve_series(
    state,
    portfolio,
    instruments: dict,
) -> list[dict]:
    session_now = get_shanghai_now()
    tzinfo = session_now.tzinfo
    trade_day = session_now.date()
    session_start = _combine_session_time(trade_day, _CN_MORNING_OPEN, tzinfo)
    session_close = _combine_session_time(trade_day, _CN_AFTERNOON_CLOSE, tzinfo)
    live_ticks = _build_cn_session_ticks(trade_day, tzinfo, now=session_now)
    full_session_ticks = _build_cn_session_ticks(trade_day, tzinfo, full_session=True)
    latest_quotes = _collect_latest_quotes(state)

    from data.manager import build_sources

    sources = build_sources(
        data_source=getattr(state.config, "data_source", "akshare"),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    intraday_source = sources.get("akshare")

    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    holdings: list[dict] = []
    has_intraday_prices = False

    for sym, position in positions.items():
        quantity = float(getattr(position, "quantity", 0.0) or 0.0)
        if quantity == 0:
            continue

        symbol = str(sym)
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        latest_quote = latest_quotes.get(symbol, {})
        asset_class = _normalize_asset_class_value(
            latest_quote.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", None)
        )
        baseline_price, _, _ = _resolve_live_holding_baseline(
            state,
            symbol,
            latest_quote if latest_quote else None,
        )
        if baseline_price is None:
            latest_price = latest_quote.get("price")
            if latest_price not in {None, ""}:
                baseline_price = float(latest_price)
            else:
                baseline_price = float(getattr(position, "avg_cost", 0.0) or 0.0)

        price_points = _load_intraday_price_points(
            intraday_source,
            symbol=symbol,
            asset_class=asset_class,
            start=session_start,
            end=session_close,
            latest_quote=latest_quote if latest_quote else None,
        )
        has_intraday_prices = has_intraday_prices or len(price_points) > 0
        holdings.append(
            {
                "asset_class": asset_class,
                "quantity": quantity,
                "avg_cost": float(getattr(position, "avg_cost", 0.0) or 0.0),
                "baseline_price": float(baseline_price),
                "price_points": price_points,
            }
        )

    ticks = live_ticks if has_intraday_prices else full_session_ticks
    cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
    series: list[dict] = []

    for tick in ticks:
        stocks_value = 0.0
        funds_value = 0.0
        others_value = 0.0
        unrealized_pnl = 0.0

        for holding in holdings:
            price = holding["baseline_price"]
            for point_timestamp, point_price in holding["price_points"]:
                if point_timestamp <= tick:
                    price = point_price
                    continue
                break

            position_value = holding["quantity"] * price
            cost_basis = holding["quantity"] * holding["avg_cost"]
            unrealized_pnl += position_value - cost_basis

            if holding["asset_class"] == "stock":
                stocks_value += position_value
            elif holding["asset_class"] in {"fund", "etf"}:
                funds_value += position_value
            else:
                others_value += position_value

        total = cash + stocks_value + funds_value + others_value
        series.append(
            {
                "timestamp": tick,
                "total": total,
                "stocks": stocks_value,
                "funds": funds_value,
                "others": others_value,
                "cash": cash,
                "unrealized_pnl": unrealized_pnl,
            }
        )

    if series:
        return series

    return [
        {
            "timestamp": tick,
            "total": cash,
            "stocks": 0.0,
            "funds": 0.0,
            "others": 0.0,
            "cash": cash,
            "unrealized_pnl": 0.0,
        }
        for tick in full_session_ticks
    ]


def _current_equity_series_point(
    state, portfolio, instruments: dict
) -> EquitySeriesPoint | None:
    if portfolio is None:
        return None

    latest_quotes = _collect_latest_quotes(state)
    cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
    buckets = {"stocks": 0.0, "funds": 0.0, "others": 0.0}
    unrealized_pnl = 0.0
    quote_status = "live"

    for sym, position in getattr(portfolio, "positions", {}).items():
        symbol = str(sym)
        quote = latest_quotes.get(symbol)
        asset_class = _normalize_asset_class_value(
            (quote or {}).get("asset_class")
            or getattr(
                getattr(
                    (instruments or {}).get(Symbol(symbol))
                    or (instruments or {}).get(symbol),
                    "asset_class",
                    None,
                ),
                "value",
                None,
            )
        )
        bucket = "others"
        if asset_class == "stock":
            bucket = "stocks"
        elif asset_class in {"fund", "etf"}:
            bucket = "funds"

        market_value = float(getattr(position, "market_value", 0.0) or 0.0)
        buckets[bucket] += market_value
        unrealized_pnl += float(getattr(position, "unrealized_pnl", 0.0) or 0.0)
        if _quote_status(state, quote) == "stale":
            quote_status = "stale"

    return EquitySeriesPoint(
        timestamp=get_shanghai_now().isoformat(),
        total=cash + buckets["stocks"] + buckets["funds"] + buckets["others"],
        stocks=buckets["stocks"],
        funds=buckets["funds"],
        others=buckets["others"],
        cash=cash,
        unrealized_pnl=unrealized_pnl,
        quote_status=quote_status,
    )


def _append_current_equity_series_point(
    points: list[EquitySeriesPoint],
    current: EquitySeriesPoint | None,
) -> list[EquitySeriesPoint]:
    if current is None:
        return points
    if not points:
        return [current]

    last_timestamp = _parse_quote_timestamp(points[-1].timestamp)
    current_timestamp = _parse_quote_timestamp(current.timestamp)
    if last_timestamp is None or current_timestamp is None:
        return points + [current]
    if current_timestamp < last_timestamp:
        return points
    if current_timestamp == last_timestamp:
        return [*points[:-1], current]
    return [*points, current]


def _series_point_from_intraday(
    point: dict, quote_status: str = "live"
) -> EquitySeriesPoint:
    return EquitySeriesPoint(
        timestamp=str(point["timestamp"].isoformat()),
        total=float(point["total"]),
        stocks=float(point["stocks"]),
        funds=float(point["funds"]),
        others=float(point["others"]),
        cash=float(point["cash"]),
        unrealized_pnl=float(point["unrealized_pnl"]),
        quote_status=quote_status,
    )


def _snapshot_quote_status(snapshot: PortfolioSnapshot) -> str:
    return (
        "stale"
        if any(position.quote_status == "stale" for position in snapshot.positions)
        else "live"
    )


def _with_overview_quote_metadata(
    overview: AccountOverview,
    snapshot: PortfolioSnapshot,
) -> AccountOverview:
    return overview.model_copy(
        update={
            "valuation_timestamp": get_shanghai_now().isoformat(),
            "quote_status": _snapshot_quote_status(snapshot),
        }
    )


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

        latest_quotes = _collect_latest_quotes(state)
        positions: list[PositionResponse] = []
        for sym, pos in portfolio.positions.items():
            symbol = str(sym)
            quote = latest_quotes.get(symbol)
            positions.append(
                PositionResponse(
                    symbol=symbol,
                    quantity=float(pos.quantity),
                    available_qty=float(pos.available_qty),
                    frozen_qty=float(pos.frozen_qty),
                    avg_cost=float(pos.avg_cost),
                    market_value=float(pos.market_value),
                    unrealized_pnl=float(pos.unrealized_pnl),
                    realized_pnl=float(pos.realized_pnl),
                    commission_paid=float(pos.commission_paid),
                    quote_timestamp=None if quote is None else quote.get("timestamp"),
                    quote_status=_quote_status(state, quote),
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
                    str(symbol)
                    for symbol, instrument in instruments.items()
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
        return _with_overview_quote_metadata(projection.summary, snapshot)

    @r.get("/state", response_model=AccountStateResponse)
    async def get_account_state() -> AccountStateResponse:
        """获取规范化账户状态投影。"""
        from server.app import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        risks = build_risk_summary(snapshot, _collect_latest_quote_timestamps(state))
        projection = build_account_state_projection(snapshot, risks)
        return AccountStateResponse(
            summary=_with_overview_quote_metadata(projection.summary, snapshot),
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
            if (
                _has_rows(legacy_cash_flows) or _has_rows(legacy_trades)
            ) or not _has_rows(ledger_entries):
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

    @r.get("/equity-curve/series", response_model=list[EquitySeriesPoint])
    async def get_equity_curve_series(range: str = "1m") -> list[EquitySeriesPoint]:
        """获取按资产类别拆分的权益曲线。"""
        from server.app import get_app_state

        state = get_app_state()
        selected_range = str(range).lower()
        if selected_range == "1d":
            portfolio, instruments = _resolve_projection_sources(state)
            portfolio, instruments, _ = _hydrate_missing_position_quotes(
                state,
                portfolio,
                instruments,
            )
            if portfolio is None:
                return []

            current_point = _current_equity_series_point(state, portfolio, instruments)
            quote_status = (
                "live" if current_point is None else current_point.quote_status
            )
            timeout_seconds = float(
                getattr(state.config, "intraday_curve_timeout_seconds", 4.0) or 4.0
            )
            try:
                intraday_points = await asyncio.wait_for(
                    asyncio.to_thread(
                        _build_intraday_equity_curve_series,
                        state,
                        portfolio,
                        instruments,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                logger.warning(
                    "Timed out building intraday equity curve after %.2fs",
                    timeout_seconds,
                )
                return [] if current_point is None else [current_point]
            except Exception:
                logger.warning("Failed to build intraday equity curve", exc_info=True)
                return [] if current_point is None else [current_point]

            return [
                _series_point_from_intraday(point, quote_status=quote_status)
                for point in intraday_points
            ]

        if state.db is None or not hasattr(state.db, "get_ledger_entries_sync"):
            return []

        sample_entries = state.db.get_ledger_entries_sync(limit=1, offset=0)
        if not _has_rows(sample_entries):
            return []

        portfolio, instruments = _resolve_projection_sources(state)
        portfolio, instruments, _ = _hydrate_missing_position_quotes(
            state,
            portfolio,
            instruments,
        )
        points = build_equity_series_from_db(
            state.db,
            initial_cash=state.config.initial_cash,
            latest_quotes=_collect_latest_quotes(state),
        )
        series_points = [
            EquitySeriesPoint(
                timestamp=str(point["timestamp"].isoformat()),
                total=float(point["total"]),
                stocks=float(point["stocks"]),
                funds=float(point["funds"]),
                others=float(point["others"]),
                cash=float(point["cash"]),
                unrealized_pnl=None,
                quote_status="live",
            )
            for point in points
        ]
        return _append_current_equity_series_point(
            series_points,
            _current_equity_series_point(state, portfolio, instruments),
        )

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

        symbol = body.symbol.strip()
        quantity = body.quantity
        price = body.price
        note = body.note

        if (
            body.asset_class == "fund"
            and body.direction == "buy"
            and body.amount is not None
        ):
            try:
                resolved = _resolve_fund_buy_fill(
                    state,
                    symbol=symbol,
                    timestamp=body.timestamp,
                    gross_amount=body.amount,
                    commission=body.commission,
                )
            except LookupError as exc:
                from fastapi.responses import JSONResponse

                identity = _resolve_fund_identity(state, symbol)
                _ensure_asset_config(
                    state,
                    symbol=identity["symbol"],
                    asset_class=body.asset_class,
                    display_name=identity["display_name"],
                )
                pending_id = db.add_pending_fund_order_sync(
                    submitted_at=body.timestamp,
                    symbol=identity["symbol"],
                    display_name=identity["display_name"],
                    amount=body.amount,
                    commission=body.commission,
                    asset_class=body.asset_class,
                    target_trade_date=_fund_target_trade_date(body.timestamp),
                    note=body.note,
                )
                return JSONResponse(
                    status_code=202,
                    content={
                        "status": "pending",
                        "id": pending_id,
                        "symbol": identity["symbol"],
                        "display_name": identity["display_name"],
                        "amount": body.amount,
                        "commission": body.commission,
                        "asset_class": body.asset_class,
                        "target_trade_date": _fund_target_trade_date(body.timestamp),
                        "detail": str(exc),
                    },
                )
            except ValueError as exc:
                from fastapi import HTTPException

                raise HTTPException(status_code=400, detail=str(exc)) from exc

            symbol = resolved["symbol"]
            quantity = resolved["quantity"]
            price = resolved["price"]
            fund_note_parts = [
                body.note.strip() if body.note.strip() else "",
                f"Auto-confirmed fund subscription: gross_amount={resolved['gross_amount']:.2f}",
                f"confirmed_trade_date={resolved['confirmed_trade_date']}",
                f"confirmed_nav={resolved['price']:.6f}",
            ]
            note = " | ".join(part for part in fund_note_parts if part)
            _ensure_asset_config(
                state,
                symbol=symbol,
                asset_class=body.asset_class,
                display_name=resolved["display_name"],
            )
        elif quantity is None or price is None:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="quantity and price are required unless this is a fund buy with amount",
            )

        trade_id = await db.add_trade(
            timestamp=body.timestamp,
            symbol=symbol,
            direction=body.direction,
            quantity=quantity,
            price=price,
            commission=body.commission,
            asset_class=body.asset_class,
            note=note,
        )
        db.insert_ledger_entry_sync(
            entry_type=f"trade_{body.direction}",
            timestamp=body.timestamp,
            amount=float(quantity) * float(price),
            symbol=symbol,
            direction=body.direction,
            quantity=float(quantity),
            price=float(price),
            commission=body.commission,
            asset_class=body.asset_class,
            note=note,
            source="portfolio_trade",
            source_ref=f"trade:{trade_id}",
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
                        symbol=Symbol(symbol),
                        side=side,
                        fill_price=Decimal(str(price)),
                        fill_quantity=Decimal(str(quantity)),
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

    @r.get("/pending-fund-orders", response_model=list[PendingFundOrderResponse])
    async def list_pending_fund_orders() -> list[PendingFundOrderResponse]:
        """列出等待确认净值的基金申购。"""
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "get_pending_fund_orders_sync"):
            return []
        rows = state.db.get_pending_fund_orders_sync(status="pending")
        return [PendingFundOrderResponse(**row) for row in rows]

    @r.delete("/trade/{trade_id}")
    async def delete_trade(trade_id: int) -> dict:
        """删除交易记录。"""
        from server.app import get_app_state

        state = get_app_state()
        deleted = await state.db.delete_trade(trade_id)
        return {"deleted": deleted}

    return r
