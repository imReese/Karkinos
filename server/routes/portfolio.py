"""Portfolio routes — /api/portfolio/*"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from core.types import ZERO, AssetClass, BarFrequency, Symbol
from server.ledger.models import LedgerEntry
from server.models import (
    AccountOverview,
    AccountStateResponse,
    ActionCard,
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
    ExplainabilityTimelineBreakdownItem,
    ExplainabilityTimelineEvent,
    ExplainabilityTimelinePoint,
    LiveHoldingGroupResponse,
    LiveHoldingItemResponse,
    LiveHoldingsResponse,
    PendingFundOrderResponse,
    PortfolioCockpitPosition,
    PortfolioCockpitResponse,
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
    TradePreviewResponse,
    TradeResponse,
)
from server.projections.service import (
    build_equity_curve_from_db,
    build_equity_series_from_db,
    build_portfolio_projection,
    build_portfolio_projection_from_db,
)
from server.services.account_state import build_account_state_projection
from server.services.asset_metadata import resolve_asset_metadata
from server.services.manual_trade_fees import (
    MANUAL_FEE_INPUT_RULE_ID,
    MANUAL_FEE_INPUT_RULE_VERSION,
    manual_fee_input_payload,
    resolve_manual_trade_fee_breakdown,
)
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
_EQUITY_SERIES_RANGE_DAYS = {
    "5d": 5,
    "1m": 31,
    "6m": 183,
    "1y": 366,
}

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


def _manual_trade_fee_breakdown(commission: float) -> dict[str, str]:
    return manual_fee_input_payload(commission)


def _manual_trade_net_cash_impact(
    *, direction: str, gross_amount: float, total_fee: float
) -> float:
    if direction == "buy":
        return -(gross_amount + total_fee)
    return gross_amount - total_fee


def _manual_trade_preview_payload(config, body: TradeCreate) -> dict:
    quantity = body.quantity
    price = body.price
    if quantity is None or price is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="quantity and price are required for trade preview",
        )

    commission = body.commission
    configured_fee = None
    note = body.note
    if commission is None:
        configured_fee = resolve_manual_trade_fee_breakdown(
            config,
            asset_class=body.asset_class,
            direction=body.direction,
            quantity=quantity,
            price=price,
        )
        if configured_fee is None:
            commission = 0.0
        else:
            commission = configured_fee.commission
            if not note.strip():
                note = configured_fee.note

    gross_amount = float(quantity) * float(price)
    total_fee = configured_fee.total_fee if configured_fee is not None else float(commission)
    fee_breakdown_json = (
        configured_fee.fee_breakdown_json
        if configured_fee is not None
        else _manual_trade_fee_breakdown(commission)
    )
    fee_rule_id = (
        configured_fee.fee_rule_id if configured_fee is not None else MANUAL_FEE_INPUT_RULE_ID
    )
    fee_rule_version = (
        configured_fee.fee_rule_version
        if configured_fee is not None
        else MANUAL_FEE_INPUT_RULE_VERSION
    )

    return {
        "symbol": body.symbol.strip(),
        "direction": body.direction,
        "quantity": float(quantity),
        "price": float(price),
        "gross_amount": gross_amount,
        "commission": float(commission),
        "total_fee": total_fee,
        "net_cash_impact": _manual_trade_net_cash_impact(
            direction=body.direction,
            gross_amount=gross_amount,
            total_fee=total_fee,
        ),
        "fee_breakdown": fee_breakdown_json,
        "fee_rule_id": fee_rule_id,
        "fee_rule_version": fee_rule_version,
        "cost_basis_method": "moving_average_buy_cost",
        "note": note,
    }


_TIMELINE_MARKET_COMPONENTS = (
    ("stock", "stocks"),
    ("fund", "funds"),
    ("other", "others"),
)

_EXTERNAL_FLOW_LABELS = {
    "cash_deposit": "入金",
    "cash_withdrawal": "出金",
    "cash_interest": "现金利息",
    "dividend": "分红",
    "manual_adjustment": "手工调整",
}

_CASH_INCOME_LEDGER_TYPES = {"cash_interest", "dividend"}

_FUND_ESTIMATE_QUOTE_SOURCES = {
    "eastmoney_fund_estimate",
    "eastmoney_fund_page",
}


def _normalize_asset_class(value: str | None) -> str:
    if not value:
        return "other"
    normalized = str(value).strip().lower()
    if normalized in {"stock", "fund", "etf", "gold", "bond", "cash"}:
        return normalized
    return "other"


def _resolve_display_name(state, symbol: str, fallback: str | None = None) -> str:
    return resolve_asset_metadata(
        state,
        symbol,
        fallback_name=fallback,
    ).display_name


def _ensure_asset_config(
    state,
    *,
    symbol: str,
    asset_class: str,
    display_name: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    upsert_watchlist = getattr(db, "upsert_watchlist_asset_sync", None)
    if callable(upsert_watchlist):
        upsert_watchlist(
            symbol=symbol,
            asset_class=asset_class,
            display_name=display_name or symbol,
            source="trade",
        )
    upsert_metadata = getattr(db, "upsert_instrument_metadata_sync", None)
    if callable(upsert_metadata):
        upsert_metadata(
            symbol=symbol,
            asset_type=asset_class,
            display_name=display_name or symbol,
            provider_symbol=symbol,
            source="trade",
        )


def _resolve_fund_buy_fill(
    state,
    *,
    symbol: str,
    timestamp: str,
    gross_amount: float,
    commission: float,
) -> dict:
    from core.types import AssetClass, BarFrequency, Symbol
    from data.manager import build_sources

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
    from core.types import Symbol
    from data.manager import build_sources

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


def _ledger_entry_display_label(state, entry: dict) -> str | None:
    symbol = entry.get("symbol")
    if not symbol:
        return None
    symbol_text = str(symbol)
    display_name = _resolve_display_name(
        state,
        symbol_text,
        fallback=entry.get("display_name") or symbol_text,
    )
    if display_name and display_name != symbol_text:
        return f"{display_name} {symbol_text}"
    return symbol_text


def _build_recent_drivers(state, entries: list[dict]) -> list[ExplainabilityDriver]:
    drivers: list[ExplainabilityDriver] = []
    for entry in entries:
        entry_type = entry.get("entry_type")
        symbol = entry.get("symbol")
        instrument_label = _ledger_entry_display_label(state, entry) or symbol
        amount = entry.get("amount")
        title = entry_type or "ledger"
        detail = entry.get("note") or "账本活动。"
        structured_fields = _ledger_entry_structured_explainability_fields(entry)

        if entry_type == "cash_deposit":
            title = "资金转入"
            detail = entry.get("note") or "现金流入组合。"
        elif entry_type == "cash_withdrawal":
            title = "资金转出"
            detail = entry.get("note") or "现金流出组合。"
        elif entry_type == "trade_buy":
            quantity = float(entry.get("quantity") or 0.0)
            price = float(entry.get("price") or 0.0)
            commission = float(entry.get("commission") or 0.0)
            title = f"买入 {instrument_label}"
            amount = -(_ledger_entry_notional(entry) + commission)
            detail = entry.get("note") or ""
        elif entry_type == "trade_sell":
            quantity = float(entry.get("quantity") or 0.0)
            price = float(entry.get("price") or 0.0)
            commission = float(entry.get("commission") or 0.0)
            title = f"卖出 {instrument_label}"
            amount = _ledger_entry_notional(entry) - commission
            detail = entry.get("note") or ""
        elif entry_type in _CASH_INCOME_LEDGER_TYPES:
            if entry_type == "cash_interest":
                title = "现金利息"
                detail = entry.get("note") or "现金利息入账。"
            else:
                title = f"分红 {instrument_label}"
                detail = entry.get("note") or "持仓现金收入。"
        elif entry_type == "manual_adjustment":
            title = "手工调整"
            detail = entry.get("note") or "手工估值或持仓调整。"

        drivers.append(
            ExplainabilityDriver(
                kind=entry_type or "ledger",
                title=title,
                detail=detail,
                timestamp=entry["timestamp"],
                symbol=symbol,
                amount=float(amount) if amount is not None else None,
                **structured_fields,
            )
        )
    return drivers


def _timeline_date_from_timestamp(timestamp: str) -> str:
    parsed = _parse_quote_timestamp(timestamp)
    if parsed is not None:
        return parsed.date().isoformat()
    return timestamp.split("T")[0]


def _ledger_entry_notional(entry: dict) -> float:
    amount = entry.get("amount")
    if amount is not None:
        return abs(float(amount))
    quantity = entry.get("quantity")
    price = entry.get("price")
    if quantity is None or price is None:
        return 0.0
    return abs(float(quantity) * float(price))


def _ledger_entry_structured_explainability_fields(entry: dict) -> dict:
    entry_type = entry.get("entry_type")
    if entry_type not in {"trade_buy", "trade_sell"}:
        return {}

    quantity = _optional_float(entry.get("quantity"))
    price = _optional_float(entry.get("price"))
    commission = _optional_float(entry.get("commission"))
    gross_amount = _optional_float(entry.get("gross_amount"))
    if gross_amount is None:
        gross_amount = _ledger_entry_notional(entry)

    if entry_type == "trade_buy":
        net_cash_impact = _optional_float(entry.get("net_cash_impact"))
        if net_cash_impact is None:
            net_cash_impact = -(gross_amount + (commission or 0.0))
    else:
        net_cash_impact = _optional_float(entry.get("net_cash_impact"))
        if net_cash_impact is None:
            net_cash_impact = gross_amount - (commission or 0.0)

    return {
        "quantity": quantity,
        "price": price,
        "commission": commission,
        "gross_amount": gross_amount,
        "net_cash_impact": net_cash_impact,
        "fee_breakdown": _parse_fee_breakdown(entry.get("fee_breakdown_json")),
        "fee_rule_id": entry.get("fee_rule_id"),
        "fee_rule_version": entry.get("fee_rule_version"),
        "asset_class": _normalize_asset_class(entry.get("asset_class")),
    }


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_fee_breakdown(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _build_timeline_breakdown_items(
    values: dict[str, float],
    labels: dict[str, str],
) -> list[ExplainabilityTimelineBreakdownItem]:
    return [
        ExplainabilityTimelineBreakdownItem(
            key=key,
            label=labels.get(key, key.replace("_", " ").title()),
            value=value,
        )
        for key, value in values.items()
        if abs(value) > 1e-9
    ]


def _equity_series_components_by_date(
    points: list[EquitySeriesPoint],
) -> dict[str, dict[str, float]]:
    components_by_date: dict[str, dict[str, float]] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if not point_date:
            continue
        if point.stocks is None or point.funds is None or point.others is None:
            continue
        components_by_date[point_date] = {
            "stocks": float(point.stocks),
            "funds": float(point.funds),
            "others": float(point.others),
            "cash": float(point.cash),
        }
    return components_by_date


def _build_timeline(
    equity_curve: list[EquityPoint],
    entries: list[dict],
    *,
    state=None,
    event_kind: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    valuation_status_by_date: dict[str, str] | None = None,
    missing_price_symbols_by_date: dict[str, list[str]] | None = None,
    component_values_by_date: dict[str, dict[str, float]] | None = None,
) -> list[ExplainabilityTimelinePoint]:
    if not equity_curve:
        return []

    events_by_date: dict[str, list[ExplainabilityTimelineEvent]] = defaultdict(list)
    external_flow_by_date: dict[str, float] = defaultdict(float)
    external_flow_breakdown_by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    positioning_flow_by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    for entry in entries:
        timestamp = str(entry.get("timestamp") or "")
        if not timestamp:
            continue
        event_date = _timeline_date_from_timestamp(timestamp)
        entry_type = entry.get("entry_type") or "ledger"
        if event_kind and entry_type != event_kind:
            continue
        symbol = entry.get("symbol")
        instrument_label = _ledger_entry_display_label(state, entry) or symbol
        amount = float(entry.get("amount") or 0.0)
        asset_class = _normalize_asset_class(entry.get("asset_class"))
        category = "portfolio"
        impact_source = "market"

        title = entry_type.replace("_", " ").title()
        detail = entry.get("note") or "账本活动。"
        if entry_type == "cash_deposit":
            title = "资金转入"
            detail = entry.get("note") or "现金流入组合。"
            external_flow_by_date[event_date] += amount
            external_flow_breakdown_by_date[event_date][entry_type] += amount
            category = "capital"
            impact_source = "external"
        elif entry_type == "cash_withdrawal":
            title = "资金转出"
            detail = entry.get("note") or "现金流出组合。"
            external_flow_by_date[event_date] -= abs(amount)
            external_flow_breakdown_by_date[event_date][entry_type] -= abs(amount)
            amount = -abs(amount)
            category = "capital"
            impact_source = "external"
        elif entry_type in _CASH_INCOME_LEDGER_TYPES:
            if entry_type == "cash_interest":
                title = "现金利息"
                detail = entry.get("note") or "现金利息入账。"
            else:
                title = f"分红 {instrument_label}"
                detail = entry.get("note") or "持仓现金收入。"
            external_flow_by_date[event_date] += amount
            external_flow_breakdown_by_date[event_date][entry_type] += amount
            category = "income"
            impact_source = "cash"
        elif entry_type == "manual_adjustment":
            title = "手工调整"
            detail = entry.get("note") or "手工账本覆盖。"
            external_flow_by_date[event_date] += amount
            external_flow_breakdown_by_date[event_date][entry_type] += amount
            category = "override"
            impact_source = "manual"
        elif entry_type == "trade_buy":
            quantity = float(entry.get("quantity") or 0.0)
            price = float(entry.get("price") or 0.0)
            title = f"买入 {instrument_label}"
            detail = entry.get("note") or ""
            amount = None
            category = "trade"
            impact_source = "positioning"
            positioning_flow_by_date[event_date][asset_class] += _ledger_entry_notional(
                entry
            )
        elif entry_type == "trade_sell":
            quantity = float(entry.get("quantity") or 0.0)
            price = float(entry.get("price") or 0.0)
            title = f"卖出 {instrument_label}"
            detail = entry.get("note") or ""
            amount = None
            category = "trade"
            impact_source = "positioning"
            positioning_flow_by_date[event_date][asset_class] -= _ledger_entry_notional(
                entry
            )

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
                **_ledger_entry_structured_explainability_fields(entry),
            )
        )

    timeline: list[ExplainabilityTimelinePoint] = []
    previous_equity: float | None = None
    previous_components: dict[str, float] | None = None
    previous_valuation_status = "complete"
    previous_missing_price_symbols: list[str] = []
    for point in equity_curve:
        point_date = point.timestamp.split("T")[0]
        point_components = (component_values_by_date or {}).get(point_date)
        if from_date and point_date < from_date:
            previous_equity = point.equity
            previous_components = point_components
            previous_valuation_status = (valuation_status_by_date or {}).get(
                point_date, "complete"
            )
            previous_missing_price_symbols = (missing_price_symbols_by_date or {}).get(
                point_date, []
            )
            continue
        if to_date and point_date > to_date:
            continue
        delta = 0.0 if previous_equity is None else point.equity - previous_equity
        external_flow = external_flow_by_date.get(point_date, 0.0)
        market_pnl = 0.0 if previous_equity is None else delta - external_flow
        point_valuation_status = (valuation_status_by_date or {}).get(
            point_date, "complete"
        )
        point_missing_price_symbols = (missing_price_symbols_by_date or {}).get(
            point_date, []
        )
        valuation_status = point_valuation_status
        missing_price_symbols = point_missing_price_symbols
        if previous_equity is not None and (
            point_valuation_status in {"missing", "partial"}
            or previous_valuation_status in {"missing", "partial"}
        ):
            valuation_status = "missing"
            market_pnl = 0.0
            missing_price_symbols = sorted(
                set(missing_price_symbols) | set(previous_missing_price_symbols)
            )
        market_breakdown: list[ExplainabilityTimelineBreakdownItem] = []
        if (
            valuation_status != "missing"
            and previous_components is not None
            and point_components is not None
        ):
            market_values: dict[str, float] = {}
            positioning_values = positioning_flow_by_date.get(point_date, {})
            for asset_key, component_key in _TIMELINE_MARKET_COMPONENTS:
                current_value = float(point_components.get(component_key, 0.0))
                previous_value = float(previous_components.get(component_key, 0.0))
                component_delta = current_value - previous_value
                market_values[asset_key] = component_delta - float(
                    positioning_values.get(asset_key, 0.0)
                )
            market_breakdown = _build_timeline_breakdown_items(
                market_values,
                _ASSET_CLASS_LABELS,
            )
        external_flow_breakdown = _build_timeline_breakdown_items(
            dict(external_flow_breakdown_by_date.get(point_date, {})),
            _EXTERNAL_FLOW_LABELS,
        )
        timeline.append(
            ExplainabilityTimelinePoint(
                date=point_date,
                equity=point.equity,
                delta=delta,
                external_flow=external_flow,
                market_pnl=market_pnl,
                events=events_by_date.get(point_date, []),
                valuation_status=valuation_status,
                missing_price_symbols=missing_price_symbols,
                market_breakdown=market_breakdown,
                external_flow_breakdown=external_flow_breakdown,
            )
        )
        previous_equity = point.equity
        previous_components = point_components
        previous_valuation_status = point_valuation_status
        previous_missing_price_symbols = point_missing_price_symbols

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

    if state.db is not None:
        if hasattr(state.db, "list_latest_quotes_sync"):
            for row in state.db.list_latest_quotes_sync():
                quote = _adapt_persistent_quote_for_portfolio(row)
                timestamp = quote.get("timestamp")
                symbol = quote.get("symbol")
                if symbol and timestamp and str(symbol) not in latest:
                    latest[str(symbol)] = timestamp
        if hasattr(state.db, "get_latest_quotes_sync"):
            for row in state.db.get_latest_quotes_sync():
                quote = _adapt_persistent_quote_for_portfolio(row)
                timestamp = quote.get("timestamp")
                symbol = quote.get("symbol")
                if symbol and timestamp and str(symbol) not in latest:
                    latest[str(symbol)] = timestamp

    return latest


def _adapt_persistent_quote_for_portfolio(row: dict) -> dict:
    quote = dict(row)
    if quote.get("asset_class") in {None, ""} and quote.get("asset_type") not in {
        None,
        "",
    }:
        quote["asset_class"] = quote.get("asset_type")
    if quote.get("timestamp") in {None, ""} and quote.get("quote_timestamp") not in {
        None,
        "",
    }:
        quote["timestamp"] = quote.get("quote_timestamp")
    if (
        quote.get("previous_close") not in {None, ""}
        and quote.get("previous_close_date") in {None, ""}
        and quote.get("timestamp") not in {None, ""}
    ):
        quote["previous_close_date"] = quote.get("timestamp")
    if quote.get("source") in {None, ""} and quote.get("quote_source") not in {
        None,
        "",
    }:
        quote["source"] = quote.get("quote_source")
    if quote.get("provider") in {None, ""} and quote.get("provider_name") not in {
        None,
        "",
    }:
        quote["provider"] = quote.get("provider_name")

    metadata_json = quote.get("metadata_json")
    if metadata_json:
        try:
            metadata = json.loads(str(metadata_json))
        except (TypeError, ValueError):
            metadata = None
        if isinstance(metadata, dict):
            for key in (
                "display_name",
                "name",
                "asset_name",
                "market",
                "provider_symbol",
            ):
                value = metadata.get(key)
                if quote.get(key) in {None, ""} and value not in {None, ""}:
                    quote[key] = value
            if quote.get("source") in {None, ""} and metadata.get("source") not in {
                None,
                "",
            }:
                quote["source"] = metadata.get("source")
    return quote


def _quote_market_timestamp(quote: dict) -> datetime | None:
    timestamps = [
        _parse_quote_timestamp(quote.get(key))
        for key in ("timestamp", "quote_timestamp")
    ]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(timestamps) if timestamps else None


def _quote_merge_timestamp(quote: dict) -> datetime | None:
    timestamps = [
        _parse_quote_timestamp(quote.get(key)) for key in ("captured_at", "updated_at")
    ]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(timestamps) if timestamps else _quote_market_timestamp(quote)


def _merge_quote_identity(base: dict, candidate: dict) -> dict:
    base_timestamp = _quote_market_timestamp(base)
    candidate_timestamp = _quote_market_timestamp(candidate)
    if base_timestamp is not None and candidate_timestamp is not None:
        if candidate_timestamp > base_timestamp:
            primary = candidate
            secondary = base
        else:
            primary = base
            secondary = candidate
    else:
        base_timestamp = _quote_merge_timestamp(base)
        candidate_timestamp = _quote_merge_timestamp(candidate)
        if candidate_timestamp is not None and (
            base_timestamp is None or candidate_timestamp > base_timestamp
        ):
            primary = candidate
            secondary = base
        else:
            primary = base
            secondary = candidate

    merged = dict(primary)
    for key in (
        "asset_class",
        "display_name",
        "name",
        "asset_name",
        "market",
        "provider_symbol",
        "nav_date",
        "previous_close",
        "previous_close_date",
        "change",
        "change_percent",
        "day_change_value",
        "day_change_pct",
        "quote_status",
        "provider_status",
        "stale_reason",
    ):
        if merged.get(key) in {None, ""} and secondary.get(key) not in {None, ""}:
            merged[key] = secondary[key]
    return merged


def _collect_latest_quotes(state) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    scheduler = state.scheduler
    if scheduler and getattr(scheduler, "latest_quotes", None):
        for symbol, quote in scheduler.latest_quotes.items():
            latest[str(symbol)] = quote

    if state.db is not None:
        if hasattr(state.db, "list_latest_quotes_sync"):
            for row in state.db.list_latest_quotes_sync():
                quote = _adapt_persistent_quote_for_portfolio(row)
                symbol = quote.get("symbol")
                if not symbol:
                    continue
                key = str(symbol)
                latest[key] = (
                    _merge_quote_identity(latest[key], quote)
                    if key in latest
                    else quote
                )
        if hasattr(state.db, "get_latest_quotes_sync"):
            for row in state.db.get_latest_quotes_sync():
                quote = _adapt_persistent_quote_for_portfolio(row)
                symbol = quote.get("symbol")
                if not symbol:
                    continue
                key = str(symbol)
                latest[key] = (
                    _merge_quote_identity(latest[key], quote)
                    if key in latest
                    else quote
                )

    return latest


def _parse_quote_timestamp(timestamp: object) -> datetime | None:
    if isinstance(timestamp, datetime):
        parsed = timestamp
    elif isinstance(timestamp, str) and timestamp.strip():
        value = timestamp.strip().replace("T ", "T")
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


def _quote_asset_class(quote: dict | None) -> str:
    if not quote:
        return ""
    value = quote.get("asset_class") or quote.get("asset_type")
    if hasattr(value, "value"):
        value = value.value
    return str(value or "").strip().lower()


def _quote_source_name(quote: dict | None) -> str:
    if not quote:
        return ""
    value = (
        quote.get("quote_source")
        or quote.get("source")
        or quote.get("provider_name")
        or quote.get("provider")
    )
    return str(value or "").strip().lower()


def _quote_live_ttl_seconds(
    quote: dict | None,
    *,
    live_poll_interval: int | None = None,
) -> int:
    base_seconds = max(int(live_poll_interval or 60), 15)
    asset_class = _quote_asset_class(quote)
    source = _quote_source_name(quote)
    if asset_class in {"fund", "etf"} and source in _FUND_ESTIMATE_QUOTE_SOURCES:
        return max(base_seconds * 10, 600)
    return max(base_seconds * 5, 300)


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
        ttl_seconds = _quote_live_ttl_seconds(
            quote,
            live_poll_interval=live_poll_interval,
        )
        return (current - timestamp).total_seconds() > ttl_seconds

    return False


def _quote_status(
    state,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str:
    raw_status = str(quote.get("quote_status") or "").strip().lower() if quote else ""
    if raw_status in {"missing", "error", "stale", "estimated"}:
        return raw_status
    if raw_status in {
        "cache",
        "cached",
        "cache_only",
        "cache_only_after_market_data_permission_fallback",
    }:
        return "cache"
    if raw_status in {
        "confirmed_nav_missing",
        "confirmed_fund_nav_missing_estimate_only",
    }:
        return "confirmed_nav_missing"
    return (
        "stale"
        if _quote_is_stale(
            quote,
            now=now,
            live_poll_interval=getattr(state.config, "live_poll_interval", 60),
        )
        else "live"
    )


def _merge_equity_series_quote_status(current: str, candidate: str) -> str:
    priority = {
        "missing": 50,
        "error": 50,
        "confirmed_nav_missing": 40,
        "estimated": 30,
        "stale": 20,
        "cache": 10,
        "live": 0,
        "confirmed": 0,
    }
    return (
        candidate if priority.get(candidate, 0) > priority.get(current, 0) else current
    )


def _is_missing_equity_quote_status(status: str | None) -> bool:
    return str(status or "").strip().lower() in {"missing", "error"}


def _quote_age_seconds(quote: dict | None, now: datetime | None = None) -> int | None:
    timestamp = _parse_quote_timestamp(
        None if quote is None else quote.get("timestamp")
    )
    if timestamp is None:
        return None
    current = get_shanghai_now(now)
    return max(int((current - timestamp).total_seconds()), 0)


def _quote_latest_price(quote: dict | None) -> float | None:
    if not quote or quote.get("price") in {None, ""}:
        return None
    return float(quote["price"])


def _session_closed_market_bar_price(
    state,
    *,
    symbol: str,
    latest_quote: dict | None,
) -> tuple[float | None, str | None]:
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    trade_day = (
        latest_timestamp.date()
        if latest_timestamp is not None
        else get_shanghai_now().date()
    )
    now = get_shanghai_now()
    if trade_day != now.date() or is_cn_trading_session(now):
        return None, None
    if state.db is None or not hasattr(state.db, "get_market_bar_on_date_sync"):
        return None, None
    market_bar = state.db.get_market_bar_on_date_sync(symbol, trade_day.isoformat())
    if not market_bar:
        return None, None
    close = market_bar.get("close", market_bar.get("price"))
    if close in {None, ""}:
        return None, None
    return (
        float(close),
        market_bar.get("trade_date")
        or str(market_bar.get("timestamp", "")).split("T")[0],
    )


def _is_unconfirmed_fund_estimate(
    state,
    *,
    symbol: str,
    asset_class: str | None,
    quote: dict | None,
) -> bool:
    """Return whether a fund quote is an estimate without confirmed same-day NAV."""
    if _normalize_asset_class(asset_class) != "fund":
        return False
    if not quote or quote.get("price") in {None, ""}:
        return False

    source = str(quote.get("quote_source") or quote.get("source") or "").strip().lower()
    if source != "eastmoney_fund_estimate":
        return False

    quote_timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if quote_timestamp is None:
        return True
    trade_date = quote_timestamp.date().isoformat()

    if state.db is None or not hasattr(state.db, "get_market_bar_on_date_sync"):
        return True
    market_bar = state.db.get_market_bar_on_date_sync(symbol, trade_date)
    if not market_bar:
        return True
    close = market_bar.get("close", market_bar.get("price"))
    return close in {None, ""}


def _position_quote_presentation(
    state,
    *,
    symbol: str,
    asset_class: str | None,
    quote: dict | None,
) -> tuple[str, str | None]:
    quote_status = _response_quote_status(state, quote)
    stale_reason = _quote_stale_reason(state, quote)
    if _is_unconfirmed_fund_estimate(
        state,
        symbol=symbol,
        asset_class=asset_class,
        quote=quote,
    ):
        return "stale", "confirmed_fund_nav_missing_estimate_only"
    return quote_status, stale_reason


def _optional_float_attr(obj, name: str) -> float | None:
    return _optional_float_value(getattr(obj, name, None))


def _optional_float_value(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _broker_cost_basis_evidence_by_symbol(
    state,
    symbols: set[str],
) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        return {}

    try:
        from account_truth.broker_evidence import BrokerEvidenceRepository

        repository = BrokerEvidenceRepository(db_path)
        evidence_by_symbol: dict[str, dict[str, object]] = {}
        for import_run in repository.list_import_runs(limit=50):
            for event in reversed(repository.list_events(import_run.import_run_id)):
                symbol = str(event.symbol)
                if (
                    symbol not in symbols
                    or symbol in evidence_by_symbol
                    or event.event_type != "position_snapshot"
                    or event.is_row_duplicate
                ):
                    continue
                unit_cost = _optional_float_value(event.cost_basis)
                if unit_cost is None:
                    continue
                evidence_by_symbol[symbol] = {
                    "unit_cost": unit_cost,
                    "method": event.cost_basis_method or "broker_remaining_cost",
                    "import_run_id": import_run.import_run_id,
                }
            if symbols.issubset(evidence_by_symbol):
                break
        return evidence_by_symbol
    except Exception:
        logger.debug("Unable to hydrate broker cost-basis evidence", exc_info=True)
        return {}


def _broker_cost_basis_fields(
    pos,
    evidence: dict[str, object] | None,
    *,
    quantity: float,
    avg_cost: float,
) -> dict[str, object]:
    unit_cost = _optional_float_attr(pos, "broker_displayed_unit_cost")
    if unit_cost is None and evidence is not None:
        unit_cost = _optional_float_value(evidence.get("unit_cost"))

    displayed_cost_basis = _optional_float_attr(pos, "broker_displayed_cost_basis")
    if displayed_cost_basis is None and unit_cost is not None:
        displayed_cost_basis = unit_cost * quantity

    difference = _optional_float_attr(pos, "broker_cost_basis_difference")
    if difference is None and displayed_cost_basis is not None:
        difference = displayed_cost_basis - quantity * avg_cost

    method = getattr(pos, "broker_cost_basis_method", None)
    if method is None and evidence is not None:
        method = evidence.get("method")

    status = getattr(pos, "broker_cost_basis_status", None)
    if status is None and unit_cost is not None:
        status = "available"

    return {
        "broker_displayed_unit_cost": unit_cost,
        "broker_displayed_cost_basis": displayed_cost_basis,
        "broker_cost_basis_difference": difference,
        "broker_cost_basis_method": method,
        "broker_cost_basis_status": status,
    }


def _resolve_live_holding_latest_price(
    state,
    *,
    symbol: str,
    latest_quote: dict | None,
    latest_price_value: float | None,
) -> float | None:
    session_close_price, _ = _session_closed_market_bar_price(
        state,
        symbol=symbol,
        latest_quote=latest_quote,
    )
    if session_close_price is not None:
        return session_close_price
    return latest_price_value


def _quote_source(state, quote: dict | None) -> str | None:
    if not quote:
        return None
    source = (
        quote.get("quote_source")
        or quote.get("source")
        or quote.get("provider_name")
        or quote.get("provider")
    )
    if source:
        return str(source)
    configured = getattr(state.config, "data_source", None)
    if configured:
        return str(configured)
    return None


def _refresh_policy(now: datetime | None = None) -> str:
    current = get_shanghai_now(now)
    return "live" if is_cn_trading_session(current) else "cache_only"


def _quote_stale_reason(
    state,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str | None:
    if not quote or quote.get("price") in {None, ""}:
        return (
            str(quote.get("stale_reason"))
            if quote and quote.get("stale_reason")
            else "no_real_data_available"
        )
    if quote.get("stale_reason"):
        return str(quote["stale_reason"])

    timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if timestamp is None:
        return "quote_timestamp_missing"

    if _quote_status(state, quote, now=now) != "stale":
        return None

    policy = _refresh_policy(now)
    if policy == "cache_only":
        return "market_closed_cache_only"

    return "quote_older_than_expected_session"


def _response_quote_status(state, quote: dict | None) -> str:
    if not quote or quote.get("price") in {None, ""}:
        return "missing"
    return _quote_status(state, quote)


def _using_persistent_cache(quote: dict | None) -> bool:
    return bool(
        quote
        and (
            quote.get("using_persistent_cache")
            or quote.get("captured_reason") == "persistent_cache"
            or quote.get("quote_status") == "stale"
        )
    )


def _can_refresh_quotes(state, now: datetime | None = None) -> bool:
    return bool(hasattr(state.config, "data_source") and is_cn_trading_session(now))


def _asset_class_from_config(state, symbol: str) -> str | None:
    """Legacy fallback for old config.json assets; DB sources are authoritative."""
    for asset in getattr(state.config, "assets", []) or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("symbol") or "").strip() != symbol:
            continue
        asset_class = asset.get("asset_class") or asset.get("asset_type")
        if asset_class not in {None, ""}:
            return str(asset_class)
    return None


def _asset_class_from_watchlist(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if not callable(list_watchlist):
        return None
    try:
        rows = list_watchlist()
    except Exception:
        logger.warning("Failed to read watchlist assets for %s", symbol, exc_info=True)
        return None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip() != symbol:
            continue
        asset_class = row.get("asset_class") or row.get("asset_type")
        if asset_class not in {None, ""}:
            return str(asset_class)
    return None


def _asset_class_from_metadata(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "get_instrument_metadata_sync"):
        return None
    try:
        metadata = db.get_instrument_metadata_sync(symbol)
    except Exception:
        logger.warning(
            "Failed to read instrument metadata for %s", symbol, exc_info=True
        )
        return None
    if not metadata:
        return None
    asset_class = metadata.get("asset_type") or metadata.get("asset_class")
    return None if asset_class in {None, ""} else str(asset_class)


def _asset_class_from_ledger(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return None

    offset = 0
    batch_size = 500
    latest_asset_class: str | None = None
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol") or "").strip() != symbol:
                continue
            asset_class = row.get("asset_class")
            if asset_class not in {None, ""}:
                latest_asset_class = str(asset_class)
        if len(rows) < batch_size:
            break
        offset += batch_size
    return latest_asset_class


def _asset_class_for_position(
    symbol: str, quote: dict | None, instruments: dict, state=None
) -> AssetClass | None:
    raw_asset_class = (quote or {}).get("asset_class")
    if not raw_asset_class and instruments:
        instrument = instruments.get(Symbol(symbol)) or instruments.get(symbol)
        raw_asset_class = getattr(
            getattr(instrument, "asset_class", None), "value", None
        )
    if not raw_asset_class and state is not None:
        raw_asset_class = (
            _asset_class_from_metadata(state, symbol)
            or _asset_class_from_watchlist(state, symbol)
            or _asset_class_from_ledger(state, symbol)
            or _asset_class_from_config(state, symbol)
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
    *,
    allow_remote_refresh: bool = False,
) -> tuple[object, dict, bool]:
    if portfolio is None:
        return portfolio, instruments, False
    if not allow_remote_refresh:
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
        asset_class = _asset_class_for_position(symbol, quote, instruments, state)
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

    ledger_entries = (
        state.db.get_ledger_entries_sync(limit=1, offset=0)
        if hasattr(state.db, "get_ledger_entries_sync")
        else []
    )
    if _has_position_ledger_entries(ledger_entries):
        rebuilt_projection = build_portfolio_projection_from_db(
            state.db,
            initial_cash=state.config.initial_cash,
            latest_quotes=latest_quotes,
        )
        return rebuilt_projection, instruments, True

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
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    trade_date = (
        latest_timestamp.date().isoformat()
        if latest_timestamp is not None
        else datetime.now().date().isoformat()
    )

    if state.db is not None and hasattr(
        state.db, "get_latest_market_bar_before_date_sync"
    ):
        market_bar = state.db.get_latest_market_bar_before_date_sync(symbol, trade_date)
        if market_bar:
            return (
                float(market_bar.get("close", market_bar.get("price"))),
                market_bar.get("trade_date")
                or str(market_bar.get("timestamp", "")).split("T")[0],
                "market_bar_close",
            )

    if state.db is not None and hasattr(state.db, "get_latest_daily_close_before_sync"):
        daily_close = state.db.get_latest_daily_close_before_sync(symbol, trade_date)
        if daily_close:
            return (
                float(daily_close["close_price"]),
                daily_close.get("trade_date"),
                "daily_close",
            )

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


def _ledger_entry_shanghai_date(entry: dict) -> date | None:
    timestamp = entry.get("timestamp")
    if timestamp in {None, ""}:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SH_TZ)
    return parsed.astimezone(_SH_TZ).date()


def _same_day_buy_cost_basis(
    state,
    *,
    symbol: str,
    trade_day: date,
    current_quantity: float,
) -> tuple[float | None, float | None]:
    db = state.db
    if (
        current_quantity <= 0
        or db is None
        or not hasattr(db, "get_ledger_entries_sync")
    ):
        return None, None

    total_quantity = 0.0
    total_cost = 0.0
    batch_size = 500
    offset = 0
    while True:
        entries = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not entries:
            break
        for entry in entries:
            if (
                str(entry.get("symbol") or "") != symbol
                or str(entry.get("entry_type") or "").lower() != "trade_buy"
                or _ledger_entry_shanghai_date(entry) != trade_day
            ):
                continue
            quantity = entry.get("quantity")
            price = entry.get("price")
            if quantity in {None, ""} or price in {None, ""}:
                continue
            quantity_value = float(quantity)
            if quantity_value <= 0:
                continue
            amount = entry.get("amount")
            cost = (
                float(amount)
                if amount not in {None, ""}
                else quantity_value * float(price)
            )
            cost += float(entry.get("commission") or 0.0)
            total_quantity += quantity_value
            total_cost += cost
        if len(entries) < batch_size:
            break
        offset += batch_size

    if total_quantity <= 0:
        return None, None
    matched_quantity = min(current_quantity, total_quantity)
    if matched_quantity < current_quantity:
        return None, None
    return total_cost / total_quantity, total_cost


def _same_day_buy_lots(
    state,
    *,
    symbol: str,
    trade_day: date,
) -> list[dict[str, float | datetime]]:
    db = state.db
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return []

    lots: list[dict[str, float | datetime]] = []
    batch_size = 500
    offset = 0
    while True:
        entries = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not entries:
            break
        for entry in entries:
            if (
                str(entry.get("symbol") or "") != symbol
                or str(entry.get("entry_type") or "").lower() != "trade_buy"
                or _ledger_entry_shanghai_date(entry) != trade_day
            ):
                continue
            quantity = entry.get("quantity")
            price = entry.get("price")
            if quantity in {None, ""} or price in {None, ""}:
                continue
            quantity_value = float(quantity)
            if quantity_value <= 0:
                continue
            timestamp = _parse_quote_timestamp(entry.get("timestamp"))
            if timestamp is None:
                continue
            amount = entry.get("amount")
            trade_cost = (
                float(amount)
                if amount not in {None, ""}
                else quantity_value * float(price)
            )
            trade_cost += float(entry.get("commission") or 0.0)
            lots.append(
                {
                    "timestamp": timestamp.astimezone(_SH_TZ),
                    "quantity": quantity_value,
                    "total_cost": trade_cost,
                    "avg_cost": trade_cost / quantity_value,
                }
            )
        if len(entries) < batch_size:
            break
        offset += batch_size

    return sorted(lots, key=lambda lot: lot["timestamp"])


def _resolve_position_today_change(
    state,
    *,
    symbol: str,
    quantity: float,
    avg_cost: float,
    latest_quote: dict | None,
    latest_price_value: float | None,
) -> tuple[float | None, float | None, float | None, str | None, str]:
    baseline_price, baseline_timestamp, baseline_source = (
        _resolve_live_holding_baseline(state, symbol, latest_quote)
    )
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    trade_day = (
        latest_timestamp.date()
        if latest_timestamp is not None
        else get_shanghai_now().date()
    )
    intraday_cost_price, intraday_total_cost = _same_day_buy_cost_basis(
        state,
        symbol=symbol,
        trade_day=trade_day,
        current_quantity=quantity,
    )
    if intraday_cost_price is not None:
        baseline_price = intraday_cost_price
        baseline_timestamp = trade_day.isoformat()
        baseline_source = "intraday_trade_cost"

    today_change = None
    today_change_pct = None
    if baseline_price not in {None, 0}:
        reference_price = (
            latest_price_value if latest_price_value is not None else avg_cost
        )
        if intraday_total_cost is not None:
            current_value = quantity * reference_price
            today_change = current_value - intraday_total_cost
            today_change_pct = (
                current_value / intraday_total_cost - 1 if intraday_total_cost else None
            )
        else:
            today_change = quantity * (reference_price - baseline_price)
            today_change_pct = (reference_price / baseline_price) - 1

    return (
        today_change,
        today_change_pct,
        baseline_price,
        baseline_timestamp,
        baseline_source,
    )


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
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=asset_class,
            quote=latest_quote,
            fallback_name=getattr(instrument, "name", symbol),
        )
        latest_price = latest_quote.get("price")
        latest_price_value = (
            float(latest_price) if latest_price not in {None, ""} else None
        )
        latest_price_value = _resolve_live_holding_latest_price(
            state,
            symbol=symbol,
            latest_quote=latest_quote if latest_quote else None,
            latest_price_value=latest_price_value,
        )
        (
            today_change,
            today_change_pct,
            baseline_price,
            baseline_timestamp,
            baseline_source,
        ) = _resolve_position_today_change(
            state,
            symbol=symbol,
            quantity=quantity,
            avg_cost=float(pos.avg_cost),
            latest_quote=latest_quote if latest_quote else None,
            latest_price_value=latest_price_value,
        )
        avg_cost = float(pos.avg_cost)
        market_value = (
            quantity * latest_price_value
            if latest_price_value is not None
            else float(pos.market_value)
        )
        cost_basis = quantity * avg_cost
        since_buy_pnl = market_value - cost_basis
        since_buy_pnl_pct = None if cost_basis == 0 else since_buy_pnl / cost_basis
        quote_status, stale_reason = _position_quote_presentation(
            state,
            symbol=symbol,
            asset_class=metadata.asset_class,
            quote=latest_quote,
        )

        groups[metadata.asset_class].append(
            LiveHoldingItemResponse(
                symbol=symbol,
                name=metadata.display_name,
                display_name=metadata.display_name,
                asset_class=metadata.asset_class,
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
                quote_status=quote_status,
                quote_source=_quote_source(state, latest_quote),
                quote_age_seconds=_quote_age_seconds(latest_quote),
                stale_reason=stale_reason,
                refresh_policy=_refresh_policy(),
                using_persistent_cache=_using_persistent_cache(latest_quote),
                nav_date=latest_quote.get("nav_date"),
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

    if state.db is None:
        return portfolio, instruments

    latest_quotes = _collect_latest_quotes(state)
    ledger_entries = (
        state.db.get_ledger_entries_sync(limit=50, offset=0)
        if hasattr(state.db, "get_ledger_entries_sync")
        else []
    )
    if _has_rows(ledger_entries) and (
        portfolio is None or _has_position_ledger_entries(ledger_entries)
    ):
        return (
            build_portfolio_projection_from_db(
                state.db,
                initial_cash=state.config.initial_cash,
                latest_quotes=latest_quotes,
            ),
            {},
        )

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

    if portfolio is not None:
        return portfolio, instruments

    return None, {}


def _has_position_ledger_entries(entries: object) -> bool:
    if not isinstance(entries, list):
        return False
    trade_types = {"trade_buy", "buy", "trade", "trade_sell", "sell"}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_type = str(entry.get("entry_type") or "").strip().lower()
        symbol = str(entry.get("symbol") or "").strip()
        if symbol and entry_type in trade_types:
            return True
    return False


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


def _load_local_intraday_quote_points(
    db,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, float]]:
    get_snapshots = getattr(db, "get_recent_quote_snapshots_sync", None)
    if not callable(get_snapshots):
        return []

    try:
        snapshots = get_snapshots(symbol, limit=1000)
    except Exception:
        logger.warning(
            "Failed to load local intraday quote snapshots for %s",
            symbol,
            exc_info=True,
        )
        return []

    points: list[tuple[datetime, float]] = []
    for snapshot in snapshots:
        quote_status = str(snapshot.get("quote_status") or "").strip().lower()
        if quote_status in {"missing", "error"}:
            continue
        timestamp = _normalize_intraday_timestamp(
            snapshot.get("timestamp"),
            start.tzinfo,
        )
        price = snapshot.get("price")
        if timestamp is None or price in {None, ""}:
            continue
        if timestamp.date() != start.date() or timestamp < start or timestamp > end:
            continue
        points.append((timestamp, float(price)))

    points.sort(key=lambda item: item[0])
    return points


def _load_intraday_price_points(
    source,
    *,
    db,
    symbol: str,
    asset_class: str,
    start: datetime,
    end: datetime,
    latest_quote: dict | None,
) -> tuple[list[tuple[datetime, float]], bool]:
    mapped_asset_class = _INTRADAY_ASSET_CLASS_MAP.get(asset_class)
    points: list[tuple[datetime, float]] = []
    local_points = _load_local_intraday_quote_points(
        db,
        symbol=symbol,
        start=start,
        end=end,
    )
    points.extend(local_points)

    if len(local_points) < 2 and source is not None and mapped_asset_class is not None:
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
    else:
        bars = None

    source_points: list[tuple[datetime, float]] = []
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
            source_points.append((timestamp, float(close)))
    points.extend(source_points)

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
    return deduped, bool(source_points or local_points)


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
        latest_timestamp = _parse_quote_timestamp(latest_quote.get("timestamp"))
        trade_day = (
            latest_timestamp.date()
            if latest_timestamp is not None
            else get_shanghai_now().date()
        )
        same_day_buy_lots = _same_day_buy_lots(
            state,
            symbol=symbol,
            trade_day=trade_day,
        )
        same_day_buy_quantity = min(
            quantity,
            sum(float(lot["quantity"]) for lot in same_day_buy_lots),
        )
        overnight_quantity = max(quantity - same_day_buy_quantity, 0.0)
        intraday_total_cost = sum(float(lot["total_cost"]) for lot in same_day_buy_lots)
        intraday_cost_price = (
            intraday_total_cost / same_day_buy_quantity
            if same_day_buy_quantity > 0
            else None
        )
        if intraday_cost_price is not None:
            baseline_price = intraday_cost_price
        overnight_baseline_value = overnight_quantity * float(baseline_price)

        price_points, has_source_intraday_prices = _load_intraday_price_points(
            intraday_source,
            db=state.db,
            symbol=symbol,
            asset_class=asset_class,
            start=session_start,
            end=session_close,
            latest_quote=latest_quote if latest_quote else None,
        )
        has_intraday_prices = has_intraday_prices or has_source_intraday_prices
        holdings.append(
            {
                "asset_class": asset_class,
                "quantity": quantity,
                "overnight_quantity": overnight_quantity,
                "avg_cost": float(getattr(position, "avg_cost", 0.0) or 0.0),
                "baseline_price": float(baseline_price),
                "overnight_baseline_value": overnight_baseline_value,
                "same_day_buy_lots": same_day_buy_lots,
                "price_points": price_points,
            }
        )

    sparse_quote_ticks = {session_start}
    trade_ticks = set()
    for holding in holdings:
        for lot in holding["same_day_buy_lots"]:
            lot_timestamp = lot["timestamp"]
            if isinstance(lot_timestamp, datetime):
                if session_start <= lot_timestamp <= session_close:
                    trade_ticks.add(lot_timestamp)
                    sparse_quote_ticks.add(lot_timestamp)
        if not has_intraday_prices:
            for point_timestamp, _ in holding["price_points"]:
                if session_start <= point_timestamp <= session_close:
                    sparse_quote_ticks.add(point_timestamp)
    if has_intraday_prices:
        ticks = sorted(set(live_ticks) | trade_ticks)
    elif len(sparse_quote_ticks) > 1:
        ticks = sorted(sparse_quote_ticks)
    else:
        ticks = full_session_ticks
    current_cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
    series: list[dict] = []

    for tick in ticks:
        pending_trade_cost = sum(
            float(lot["total_cost"])
            for holding in holdings
            for lot in holding["same_day_buy_lots"]
            if isinstance(lot["timestamp"], datetime) and lot["timestamp"] > tick
        )
        cash = current_cash + pending_trade_cost
        stocks_value = 0.0
        funds_value = 0.0
        others_value = 0.0
        unrealized_pnl = 0.0
        stocks_daily_change = 0.0
        funds_daily_change = 0.0
        others_daily_change = 0.0

        for holding in holdings:
            price = holding["baseline_price"]
            for point_timestamp, point_price in holding["price_points"]:
                if point_timestamp <= tick:
                    price = point_price
                    continue
                break

            active_same_day_quantity = sum(
                float(lot["quantity"])
                for lot in holding["same_day_buy_lots"]
                if isinstance(lot["timestamp"], datetime) and lot["timestamp"] <= tick
            )
            active_quantity = min(
                holding["quantity"],
                holding["overnight_quantity"] + active_same_day_quantity,
            )
            position_value = active_quantity * price
            cost_basis = active_quantity * holding["avg_cost"]
            unrealized_pnl += position_value - cost_basis
            active_same_day_baseline_value = sum(
                float(lot["total_cost"])
                for lot in holding["same_day_buy_lots"]
                if isinstance(lot["timestamp"], datetime) and lot["timestamp"] <= tick
            )
            baseline_value = (
                holding["overnight_baseline_value"] + active_same_day_baseline_value
            )
            daily_change = position_value - baseline_value

            if holding["asset_class"] == "stock":
                stocks_value += position_value
                stocks_daily_change += daily_change
            elif holding["asset_class"] in {"fund", "etf"}:
                funds_value += position_value
                funds_daily_change += daily_change
            else:
                others_value += position_value
                others_daily_change += daily_change

        total = cash + stocks_value + funds_value + others_value
        total_daily_change = (
            stocks_daily_change + funds_daily_change + others_daily_change
        )
        series.append(
            {
                "timestamp": tick,
                "total": total,
                "stocks": stocks_value,
                "funds": funds_value,
                "others": others_value,
                "cash": cash,
                "unrealized_pnl": unrealized_pnl,
                "total_daily_change": total_daily_change,
                "stocks_daily_change": stocks_daily_change,
                "funds_daily_change": funds_daily_change,
                "others_daily_change": others_daily_change,
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
            "total_daily_change": 0.0,
            "stocks_daily_change": 0.0,
            "funds_daily_change": 0.0,
            "others_daily_change": 0.0,
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
    missing_price_symbols: set[str] = set()

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
        position_quote_status, position_stale_reason = _position_quote_presentation(
            state,
            symbol=symbol,
            asset_class=asset_class,
            quote=quote,
        )
        if position_stale_reason == "confirmed_fund_nav_missing_estimate_only":
            position_quote_status = "confirmed_nav_missing"
        if _is_missing_equity_quote_status(position_quote_status):
            missing_price_symbols.add(symbol)
        quote_status = _merge_equity_series_quote_status(
            quote_status,
            position_quote_status,
        )

    quote_dependent_values_available = not _is_missing_equity_quote_status(quote_status)
    return EquitySeriesPoint(
        timestamp=get_shanghai_now().isoformat(),
        total=(
            cash + buckets["stocks"] + buckets["funds"] + buckets["others"]
            if quote_dependent_values_available
            else None
        ),
        stocks=buckets["stocks"] if quote_dependent_values_available else None,
        funds=buckets["funds"] if quote_dependent_values_available else None,
        others=buckets["others"] if quote_dependent_values_available else None,
        cash=cash,
        unrealized_pnl=unrealized_pnl if quote_dependent_values_available else None,
        quote_status=quote_status,
        missing_price_symbols=sorted(missing_price_symbols),
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


def _daily_equity_series_for_range(
    points: list[EquitySeriesPoint],
    selected_range: str,
) -> list[EquitySeriesPoint]:
    """Materialize sparse ledger valuation points into day-level chart points."""

    if selected_range == "1d" or len(points) < 2:
        return points

    parsed_points = [
        (timestamp, point)
        for point in points
        if (timestamp := _parse_quote_timestamp(point.timestamp)) is not None
    ]
    if len(parsed_points) < 2:
        return points

    parsed_points.sort(key=lambda item: item[0])
    end_timestamp = parsed_points[-1][0]
    range_days = _EQUITY_SERIES_RANGE_DAYS.get(selected_range)
    if range_days is None:
        start_timestamp = parsed_points[0][0]
    else:
        start_timestamp = end_timestamp - timedelta(days=range_days)

    start_date = start_timestamp.date()
    end_date = end_timestamp.date()
    event_index = 0
    active_point: EquitySeriesPoint | None = None

    while (
        event_index < len(parsed_points)
        and parsed_points[event_index][0] <= start_timestamp
    ):
        active_point = parsed_points[event_index][1]
        event_index += 1

    daily_points: list[EquitySeriesPoint] = []
    current_date = start_date
    while current_date <= end_date:
        day_end = datetime.combine(
            current_date,
            time(23, 59, 59),
            tzinfo=end_timestamp.tzinfo or _SH_TZ,
        )
        while (
            event_index < len(parsed_points)
            and parsed_points[event_index][0] <= day_end
        ):
            active_point = parsed_points[event_index][1]
            event_index += 1

        is_range_start = current_date == start_date
        is_range_end = current_date == end_date
        is_trading_day = current_date.weekday() < 5
        should_emit_day = is_range_start or is_trading_day
        if active_point is not None and should_emit_day:
            point_timestamp = (
                end_timestamp
                if is_range_end
                else datetime.combine(
                    current_date,
                    _CN_AFTERNOON_CLOSE,
                    tzinfo=end_timestamp.tzinfo or _SH_TZ,
                )
            )
            daily_points.append(
                active_point.model_copy(
                    update={"timestamp": point_timestamp.isoformat()}
                )
            )

        current_date += timedelta(days=1)

    return daily_points or points


def _equity_points_from_series(
    points: list[EquitySeriesPoint],
) -> list[EquityPoint]:
    by_date: dict[str, EquityPoint] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if not point_date:
            continue
        if point.total is None:
            continue
        by_date[point_date] = EquityPoint(
            timestamp=point.timestamp,
            equity=float(point.total),
        )
    return list(by_date.values())


def _trim_non_trading_terminal_series_point(
    points: list[EquitySeriesPoint],
) -> list[EquitySeriesPoint]:
    if len(points) < 2:
        return points
    timestamp = _parse_quote_timestamp(points[-1].timestamp)
    if timestamp is not None and timestamp.weekday() >= 5:
        return points[:-1]
    previous_timestamp = _parse_quote_timestamp(points[-2].timestamp)
    if (
        points[-1].quote_status == "stale"
        and timestamp is not None
        and previous_timestamp is not None
        and timestamp.date() > previous_timestamp.date()
    ):
        return points[:-1]
    return points


def _trim_intraday_terminal_series_point(
    points: list[EquitySeriesPoint],
    *,
    now: datetime | None = None,
) -> list[EquitySeriesPoint]:
    if len(points) < 2:
        return points
    timestamp = _parse_quote_timestamp(points[-1].timestamp)
    if timestamp is None:
        return points
    current = (now or get_shanghai_now()).astimezone(_SH_TZ)
    point_time = timestamp.astimezone(_SH_TZ).time().replace(tzinfo=None)
    if timestamp.astimezone(_SH_TZ).date() == current.date() and (
        point_time != _CN_AFTERNOON_CLOSE
    ):
        return points[:-1]
    return points


def _equity_series_status_rank(status: str | None) -> int:
    if status in {"missing", "error"}:
        return 0
    if status == "stale":
        return 1
    return 2


def _dedupe_equity_series_points_by_date(
    points: list[EquitySeriesPoint],
) -> list[EquitySeriesPoint]:
    by_date: dict[str, EquitySeriesPoint] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if not point_date:
            continue
        existing = by_date.get(point_date)
        if existing is None:
            by_date[point_date] = point
            continue
        existing_timestamp = _parse_quote_timestamp(existing.timestamp)
        point_timestamp = _parse_quote_timestamp(point.timestamp)
        existing_score = (
            _equity_series_status_rank(existing.quote_status),
            existing_timestamp or datetime.min.replace(tzinfo=_SH_TZ),
        )
        point_score = (
            _equity_series_status_rank(point.quote_status),
            point_timestamp or datetime.min.replace(tzinfo=_SH_TZ),
        )
        if point_score >= existing_score:
            by_date[point_date] = point
    return [by_date[day] for day in sorted(by_date)]


def _equity_series_metadata_by_date(
    points: list[EquitySeriesPoint],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    valuation_status_by_date: dict[str, str] = {}
    missing_symbols_by_date: dict[str, list[str]] = {}
    for point in points:
        point_date = str(point.timestamp).split("T")[0]
        if not point_date:
            continue
        valuation_status_by_date[point_date] = point.quote_status
        missing_symbols = getattr(point, "missing_price_symbols", None)
        if missing_symbols:
            missing_symbols_by_date[point_date] = list(missing_symbols)
    return valuation_status_by_date, missing_symbols_by_date


def _load_ledger_entries_for_equity_series(
    db, batch_size: int = 500
) -> list[LedgerEntry]:
    entries: list[LedgerEntry] = []
    offset = 0
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        entries.extend(LedgerEntry.from_row(row) for row in rows)
        if len(rows) < batch_size:
            break
        offset += batch_size
    return sorted(entries, key=lambda entry: (entry.timestamp, entry.id or 0))


def _ledger_entry_timestamp(entry: LedgerEntry) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(entry.timestamp)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=_SH_TZ)
    return timestamp.astimezone(_SH_TZ)


def _equity_series_bucket(asset_class: str | None) -> str | None:
    normalized = _normalize_asset_class_value(asset_class)
    if normalized == "stock":
        return "stocks"
    if normalized in {"fund", "etf"}:
        return "funds"
    if normalized in {"bond", "gold"}:
        return "others"
    return None


def _historical_quote_for_equity_day(
    state,
    *,
    symbol: str,
    asset_class: str,
    trade_date: date,
    latest_quotes: dict[str, dict],
    is_current_day: bool,
) -> dict | None:
    _ = is_current_day

    next_date = (trade_date + timedelta(days=1)).isoformat()
    db = state.db
    if db is not None and hasattr(db, "get_latest_market_bar_before_date_sync"):
        market_bar = db.get_latest_market_bar_before_date_sync(symbol, next_date)
        if market_bar:
            return {
                "symbol": symbol,
                "asset_class": market_bar.get("asset_class") or asset_class,
                "price": market_bar.get("price", market_bar.get("close")),
                "timestamp": market_bar.get("timestamp")
                or market_bar.get("trade_date")
                or trade_date.isoformat(),
                "quote_status": "confirmed",
                "source": market_bar.get("source") or "market_bars",
                "open": market_bar.get("open"),
                "high": market_bar.get("high"),
                "low": market_bar.get("low"),
                "close": market_bar.get("close"),
            }

    if db is not None and hasattr(db, "get_latest_daily_close_before_sync"):
        daily_close = db.get_latest_daily_close_before_sync(symbol, next_date)
        if daily_close:
            return {
                "symbol": symbol,
                "asset_class": daily_close.get("asset_class") or asset_class,
                "price": daily_close["close_price"],
                "timestamp": daily_close.get("trade_date"),
                "quote_status": "confirmed",
                "source": daily_close.get("source"),
            }

    if db is not None and hasattr(db, "get_latest_quote_before_date_sync"):
        quote = db.get_latest_quote_before_date_sync(symbol, next_date)
        if quote:
            return quote

    if not (
        db is not None
        and (
            hasattr(db, "get_latest_daily_close_before_sync")
            or hasattr(db, "get_latest_quote_before_date_sync")
        )
    ):
        return latest_quotes.get(symbol)
    return None


def _quote_valuation_date(quote: dict | None) -> date | None:
    if not quote:
        return None
    for key in ("trade_date", "timestamp", "quote_timestamp"):
        value = quote.get(key)
        parsed = _parse_quote_timestamp(value)
        if parsed is not None:
            return parsed.date()
        if isinstance(value, str) and value.strip():
            try:
                return date.fromisoformat(value.strip().split("T")[0].split(" ")[0])
            except ValueError:
                continue
    return None


def _daily_equity_series_from_ledger_history(
    state,
    *,
    selected_range: str,
    current_point: EquitySeriesPoint | None,
) -> list[EquitySeriesPoint]:
    if (
        selected_range == "1d"
        or state.db is None
        or not hasattr(state.db, "get_ledger_entries_sync")
    ):
        return []

    entries = _load_ledger_entries_for_equity_series(state.db)
    dated_entries = [
        (timestamp, entry)
        for entry in entries
        if (timestamp := _ledger_entry_timestamp(entry)) is not None
    ]
    if not dated_entries:
        return []

    latest_timestamp = (
        _parse_quote_timestamp(current_point.timestamp)
        if current_point is not None
        else None
    ) or get_shanghai_now()
    latest_timestamp = latest_timestamp.astimezone(_SH_TZ)
    range_days = _EQUITY_SERIES_RANGE_DAYS.get(selected_range)
    first_entry_date = dated_entries[0][0].date()
    if range_days is None:
        start_date = first_entry_date
    else:
        start_date = (latest_timestamp - timedelta(days=range_days)).date()
    end_date = latest_timestamp.date()
    if start_date > end_date:
        return []

    latest_quotes = _collect_latest_quotes(state)
    active_entries: list[LedgerEntry] = []
    entry_index = 0
    asset_classes: dict[str, str] = {}
    points: list[EquitySeriesPoint] = []
    current_date = start_date

    while current_date <= end_date:
        day_end = datetime.combine(
            current_date,
            time(23, 59, 59),
            tzinfo=_SH_TZ,
        )
        while (
            entry_index < len(dated_entries)
            and dated_entries[entry_index][0] <= day_end
        ):
            _, entry = dated_entries[entry_index]
            active_entries.append(entry)
            if entry.symbol:
                asset_classes[str(entry.symbol)] = _normalize_asset_class_value(
                    entry.asset_class
                )
            entry_index += 1

        should_emit_day = current_date == start_date or current_date.weekday() < 5
        if active_entries and should_emit_day:
            historical_quotes: dict[str, dict] = {}
            missing_price_symbols: list[str] = []
            stale_terminal_symbols: list[str] = []
            for symbol, asset_class in asset_classes.items():
                quote = _historical_quote_for_equity_day(
                    state,
                    symbol=symbol,
                    asset_class=asset_class,
                    trade_date=current_date,
                    latest_quotes=latest_quotes,
                    is_current_day=current_date == end_date,
                )
                if quote is not None:
                    quote_date = _quote_valuation_date(quote)
                    if current_date == end_date and quote_date != current_date:
                        stale_terminal_symbols.append(symbol)
                        continue
                    historical_quotes[symbol] = quote
                elif any(entry.symbol == symbol for entry in active_entries):
                    missing_price_symbols.append(symbol)

            if current_date == end_date and stale_terminal_symbols:
                current_date += timedelta(days=1)
                continue

            projection = build_portfolio_projection(
                active_entries,
                initial_cash=state.config.initial_cash,
                latest_quotes=historical_quotes,
            )
            buckets = {"stocks": 0.0, "funds": 0.0, "others": 0.0}
            unrealized_pnl = 0.0
            for symbol, position in projection.positions.items():
                bucket = _equity_series_bucket(asset_classes.get(symbol))
                if bucket is None:
                    continue
                market_value = float(position.market_value)
                buckets[bucket] += market_value
                unrealized_pnl += float(position.unrealized_pnl)

            timestamp = datetime.combine(
                current_date,
                _CN_AFTERNOON_CLOSE,
                tzinfo=_SH_TZ,
            )
            points.append(
                EquitySeriesPoint(
                    timestamp=timestamp.isoformat(),
                    total=float(projection.cash)
                    + buckets["stocks"]
                    + buckets["funds"]
                    + buckets["others"],
                    stocks=buckets["stocks"],
                    funds=buckets["funds"],
                    others=buckets["others"],
                    cash=float(projection.cash),
                    unrealized_pnl=unrealized_pnl,
                    quote_status="missing" if missing_price_symbols else "live",
                    missing_price_symbols=sorted(set(missing_price_symbols)),
                )
            )

        current_date += timedelta(days=1)

    return points


def _flat_intraday_equity_series_from_current(
    current: EquitySeriesPoint | None,
) -> list[EquitySeriesPoint]:
    if current is None:
        return []

    current_timestamp = _parse_quote_timestamp(current.timestamp) or get_shanghai_now()
    ticks = _build_cn_session_ticks(
        current_timestamp.date(),
        current_timestamp.tzinfo or _SH_TZ,
        full_session=True,
    )
    if not ticks:
        return [current]

    return [
        current.model_copy(update={"timestamp": tick.isoformat()}) for tick in ticks
    ]


def _synthetic_intraday_equity_series_from_current_quotes(
    state,
    portfolio,
    instruments: dict,
    current: EquitySeriesPoint | None,
) -> list[EquitySeriesPoint]:
    if portfolio is None:
        return []

    now = get_shanghai_now()
    trade_day = now.date()
    session_ticks = _build_cn_session_ticks(
        trade_day, now.tzinfo or _SH_TZ, full_session=True
    )
    if not session_ticks:
        return [] if current is None else [current]
    session_start = session_ticks[0]
    session_close = session_ticks[-1]

    latest_quotes = _collect_latest_quotes(state)
    cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
    holdings: list[dict] = []
    sparse_quote_ticks = {session_start}

    for sym, position in getattr(portfolio, "positions", {}).items():
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
        latest_price = latest_quote.get("price")
        latest_price_value = (
            float(latest_price) if latest_price not in {None, ""} else None
        )
        baseline_price, _, _ = _resolve_live_holding_baseline(
            state,
            symbol,
            latest_quote if latest_quote else None,
        )
        quote_timestamp = _parse_quote_timestamp(latest_quote.get("timestamp"))
        quote_trade_day = (
            quote_timestamp.date() if quote_timestamp is not None else trade_day
        )
        intraday_cost_price, intraday_total_cost = _same_day_buy_cost_basis(
            state,
            symbol=symbol,
            trade_day=quote_trade_day,
            current_quantity=quantity,
        )
        if intraday_cost_price is not None:
            baseline_price = intraday_cost_price
        if baseline_price is None:
            baseline_price = (
                latest_price_value
                if latest_price_value is not None
                else float(getattr(position, "avg_cost", 0.0) or 0.0)
            )
        if (
            latest_price_value is not None
            and quote_timestamp is not None
            and session_start <= quote_timestamp <= session_close
        ):
            sparse_quote_ticks.add(quote_timestamp)

        holdings.append(
            {
                "asset_class": asset_class,
                "quantity": quantity,
                "avg_cost": float(getattr(position, "avg_cost", 0.0) or 0.0),
                "baseline_price": float(baseline_price),
                "baseline_value": (
                    float(intraday_total_cost)
                    if intraday_total_cost is not None
                    else quantity * float(baseline_price)
                ),
                "latest_price": latest_price_value,
                "quote_timestamp": quote_timestamp,
            }
        )

    quote_status = "live" if current is None else current.quote_status
    ticks = sorted(sparse_quote_ticks) if len(sparse_quote_ticks) > 1 else session_ticks
    points: list[EquitySeriesPoint] = []
    for tick in ticks:
        stocks_value = 0.0
        funds_value = 0.0
        others_value = 0.0
        unrealized_pnl = 0.0
        stocks_daily_change = 0.0
        funds_daily_change = 0.0
        others_daily_change = 0.0
        for holding in holdings:
            price = holding["baseline_price"]
            quote_timestamp = holding["quote_timestamp"]
            if (
                holding["latest_price"] is not None
                and quote_timestamp is not None
                and quote_timestamp <= tick
            ):
                price = holding["latest_price"]

            position_value = holding["quantity"] * price
            cost_basis = holding["quantity"] * holding["avg_cost"]
            unrealized_pnl += position_value - cost_basis
            daily_change = position_value - holding["baseline_value"]

            if holding["asset_class"] == "stock":
                stocks_value += position_value
                stocks_daily_change += daily_change
            elif holding["asset_class"] in {"fund", "etf"}:
                funds_value += position_value
                funds_daily_change += daily_change
            else:
                others_value += position_value
                others_daily_change += daily_change

        total_daily_change = (
            stocks_daily_change + funds_daily_change + others_daily_change
        )
        points.append(
            EquitySeriesPoint(
                timestamp=tick.isoformat(),
                total=cash + stocks_value + funds_value + others_value,
                stocks=stocks_value,
                funds=funds_value,
                others=others_value,
                cash=cash,
                unrealized_pnl=unrealized_pnl,
                total_daily_change=total_daily_change,
                stocks_daily_change=stocks_daily_change,
                funds_daily_change=funds_daily_change,
                others_daily_change=others_daily_change,
                quote_status=quote_status,
            )
        )

    return points


def _should_fetch_intraday_equity_curve(now: datetime) -> bool:
    return now.astimezone(_SH_TZ).weekday() < 5


def _series_point_from_intraday(
    point: dict,
    quote_status: str = "live",
    missing_price_symbols: list[str] | None = None,
) -> EquitySeriesPoint:
    if _is_missing_equity_quote_status(quote_status):
        return EquitySeriesPoint(
            timestamp=str(point["timestamp"].isoformat()),
            total=None,
            stocks=None,
            funds=None,
            others=None,
            cash=float(point["cash"]),
            unrealized_pnl=None,
            total_daily_change=None,
            stocks_daily_change=None,
            funds_daily_change=None,
            others_daily_change=None,
            quote_status=quote_status,
            missing_price_symbols=sorted(set(missing_price_symbols or [])),
        )

    return EquitySeriesPoint(
        timestamp=str(point["timestamp"].isoformat()),
        total=float(point["total"]),
        stocks=float(point["stocks"]),
        funds=float(point["funds"]),
        others=float(point["others"]),
        cash=float(point["cash"]),
        unrealized_pnl=float(point["unrealized_pnl"]),
        total_daily_change=(
            None
            if point.get("total_daily_change") is None
            else float(point["total_daily_change"])
        ),
        stocks_daily_change=(
            None
            if point.get("stocks_daily_change") is None
            else float(point["stocks_daily_change"])
        ),
        funds_daily_change=(
            None
            if point.get("funds_daily_change") is None
            else float(point["funds_daily_change"])
        ),
        others_daily_change=(
            None
            if point.get("others_daily_change") is None
            else float(point["others_daily_change"])
        ),
        quote_status=quote_status,
        missing_price_symbols=sorted(set(missing_price_symbols or [])),
    )


def _snapshot_quote_status(snapshot: PortfolioSnapshot) -> str:
    if any(position.quote_status == "missing" for position in snapshot.positions):
        return "missing"
    if any(position.quote_status == "stale" for position in snapshot.positions):
        return "stale"
    return "live"


def _snapshot_quote_age_seconds(snapshot: PortfolioSnapshot) -> int | None:
    ages = [
        position.quote_age_seconds
        for position in snapshot.positions
        if position.quote_age_seconds is not None
    ]
    return max(ages) if ages else None


def _snapshot_stale_reason(snapshot: PortfolioSnapshot) -> str | None:
    for position in snapshot.positions:
        if position.quote_status == "stale" and position.stale_reason:
            return position.stale_reason
        if position.quote_status == "missing" and position.stale_reason:
            return position.stale_reason
    return None


def _snapshot_quote_source(snapshot: PortfolioSnapshot) -> str | None:
    for position in snapshot.positions:
        if position.quote_source:
            return position.quote_source
    return None


def _snapshot_uses_persistent_cache(snapshot: PortfolioSnapshot) -> bool:
    return any(position.using_persistent_cache for position in snapshot.positions)


def _with_overview_quote_metadata(
    overview: AccountOverview,
    snapshot: PortfolioSnapshot,
) -> AccountOverview:
    return overview.model_copy(
        update={
            "valuation_timestamp": get_shanghai_now().isoformat(),
            "quote_status": _snapshot_quote_status(snapshot),
            "quote_age_seconds": _snapshot_quote_age_seconds(snapshot),
            "quote_source": _snapshot_quote_source(snapshot),
            "stale_reason": _snapshot_stale_reason(snapshot),
            "refresh_policy": _refresh_policy(),
            "using_persistent_cache": _snapshot_uses_persistent_cache(snapshot),
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
                cash=0.0,
                total_equity=0.0,
                total_deposits=0.0,
                positions=[],
                allocation=[],
                allocation_grouped=[],
            )

        latest_quotes = _collect_latest_quotes(state)
        broker_cost_basis_evidence = _broker_cost_basis_evidence_by_symbol(
            state,
            {str(symbol) for symbol in portfolio.positions},
        )
        positions: list[PositionResponse] = []
        for sym, pos in portfolio.positions.items():
            symbol = str(sym)
            quote = latest_quotes.get(symbol)
            instrument = instruments.get(Symbol(symbol)) if instruments else None
            asset_class = _normalize_asset_class(
                (quote or {}).get("asset_class")
                or getattr(getattr(instrument, "asset_class", None), "value", None)
            )
            metadata = resolve_asset_metadata(
                state,
                symbol,
                asset_class=asset_class,
                quote=quote,
                fallback_name=getattr(instrument, "name", None) or symbol,
            )
            quantity = float(pos.quantity)
            avg_cost = float(pos.avg_cost)
            latest_price_value = _quote_latest_price(quote)
            (
                today_change,
                today_change_pct,
                baseline_price,
                baseline_timestamp,
                baseline_source,
            ) = _resolve_position_today_change(
                state,
                symbol=symbol,
                quantity=quantity,
                avg_cost=avg_cost,
                latest_quote=quote,
                latest_price_value=latest_price_value,
            )
            quote_status, stale_reason = _position_quote_presentation(
                state,
                symbol=symbol,
                asset_class=metadata.asset_class,
                quote=quote,
            )
            broker_cost_basis_fields = _broker_cost_basis_fields(
                pos,
                broker_cost_basis_evidence.get(symbol),
                quantity=quantity,
                avg_cost=avg_cost,
            )
            positions.append(
                PositionResponse(
                    symbol=symbol,
                    name=metadata.display_name,
                    display_name=metadata.display_name,
                    asset_class=metadata.asset_class,
                    quantity=quantity,
                    available_qty=float(pos.available_qty),
                    frozen_qty=float(pos.frozen_qty),
                    avg_cost=avg_cost,
                    **broker_cost_basis_fields,
                    latest_price=latest_price_value,
                    market_value=float(pos.market_value),
                    unrealized_pnl=float(pos.unrealized_pnl),
                    realized_pnl=float(pos.realized_pnl),
                    commission_paid=float(pos.commission_paid),
                    today_change=today_change,
                    today_change_pct=today_change_pct,
                    baseline_price=baseline_price,
                    baseline_timestamp=baseline_timestamp,
                    baseline_source=baseline_source,
                    quote_timestamp=None if quote is None else quote.get("timestamp"),
                    quote_status=quote_status,
                    quote_source=_quote_source(state, quote),
                    quote_age_seconds=_quote_age_seconds(quote),
                    stale_reason=stale_reason,
                    refresh_policy=_refresh_policy(),
                    using_persistent_cache=_using_persistent_cache(quote),
                    nav_date=None if quote is None else quote.get("nav_date"),
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
                name = pos.display_name or pos.name or pos.symbol

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

    @r.get("/cockpit", response_model=PortfolioCockpitResponse)
    async def get_portfolio_cockpit() -> PortfolioCockpitResponse:
        """Return portfolio weights, drift, action queue, and risk alerts."""
        from server.app import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        risks = build_risk_summary(snapshot, _collect_latest_quote_timestamps(state))
        projection = build_account_state_projection(snapshot, risks)
        action_rows = []
        if state.db is not None and hasattr(state.db, "get_action_tasks"):
            action_rows = await state.db.get_action_tasks(
                statuses=["pending", "deferred"],
                limit=10,
            )
        action_queue = [ActionCard(**row) for row in action_rows]
        actions_by_symbol = {action.symbol: action for action in action_queue}

        positions: list[PortfolioCockpitPosition] = []
        for position in snapshot.positions:
            actual_weight = (
                position.market_value / snapshot.total_equity
                if snapshot.total_equity > 0
                else 0.0
            )
            action = actions_by_symbol.get(position.symbol)
            target_weight = (
                action.target_weight if action is not None else actual_weight
            )
            positions.append(
                PortfolioCockpitPosition(
                    symbol=position.symbol,
                    name=position.display_name or position.name,
                    asset_class=position.asset_class,
                    market_value=position.market_value,
                    actual_weight=actual_weight,
                    target_weight=target_weight,
                    drift=target_weight - actual_weight,
                    action_task=action,
                )
            )

        return PortfolioCockpitResponse(
            summary=_with_overview_quote_metadata(projection.summary, snapshot),
            positions=positions,
            action_queue=action_queue,
            risk_alerts=projection.risks,
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
            if not _should_fetch_intraday_equity_curve(get_shanghai_now()):
                return _flat_intraday_equity_series_from_current(current_point)

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
                return _synthetic_intraday_equity_series_from_current_quotes(
                    state,
                    portfolio,
                    instruments,
                    current_point,
                )
            except Exception:
                logger.warning("Failed to build intraday equity curve", exc_info=True)
                return _synthetic_intraday_equity_series_from_current_quotes(
                    state,
                    portfolio,
                    instruments,
                    current_point,
                )

            return [
                _series_point_from_intraday(
                    point,
                    quote_status=quote_status,
                    missing_price_symbols=(
                        []
                        if current_point is None
                        else current_point.missing_price_symbols
                    ),
                )
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
        current_point = _current_equity_series_point(state, portfolio, instruments)
        daily_points = _daily_equity_series_from_ledger_history(
            state,
            selected_range=selected_range,
            current_point=current_point,
        )
        if daily_points:
            return _append_current_equity_series_point(daily_points, current_point)

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
        return _daily_equity_series_for_range(
            _append_current_equity_series_point(
                series_points,
                current_point,
            ),
            selected_range,
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
        equity_curve: list[EquityPoint] = []
        valuation_status_by_date: dict[str, str] = {}
        missing_price_symbols_by_date: dict[str, list[str]] = {}
        component_values_by_date: dict[str, dict[str, float]] = {}
        if state.db is not None and (
            hasattr(state.db, "get_latest_daily_close_before_sync")
            or hasattr(state.db, "get_latest_quote_before_date_sync")
        ):
            equity_series = await get_equity_curve_series("all")
            equity_series = _trim_non_trading_terminal_series_point(equity_series)
            equity_series = _trim_intraday_terminal_series_point(equity_series)
            equity_series = _dedupe_equity_series_points_by_date(equity_series)
            equity_curve = _equity_points_from_series(equity_series)
            component_values_by_date = _equity_series_components_by_date(equity_series)
            (
                valuation_status_by_date,
                missing_price_symbols_by_date,
            ) = _equity_series_metadata_by_date(equity_series)
        if not equity_curve:
            equity_curve = await get_equity_curve()

        entries = []
        if state.db is not None and hasattr(state.db, "get_ledger_entries_sync"):
            entries = state.db.get_ledger_entries_sync(limit=limit, offset=0)

        return ExplainabilityResponse(
            equity_bridge=_build_equity_bridge(snapshot, summary),
            recent_drivers=_build_recent_drivers(state, entries),
            positions=_build_position_drivers(snapshot, entries),
            timeline=_build_timeline(
                equity_curve,
                entries,
                state=state,
                event_kind=event_kind,
                from_date=from_date,
                to_date=to_date,
                valuation_status_by_date=valuation_status_by_date,
                missing_price_symbols_by_date=missing_price_symbols_by_date,
                component_values_by_date=component_values_by_date,
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

    @r.post("/trade/preview", response_model=TradePreviewResponse)
    async def preview_trade(body: TradeCreate) -> TradePreviewResponse:
        """Preview manual trade fees and cash impact without writing ledger facts."""
        from server.app import get_app_state

        state = get_app_state()
        return TradePreviewResponse(
            **_manual_trade_preview_payload(state.config, body)
        )

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
        commission = body.commission
        configured_fee = None

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
                    commission=commission or 0.0,
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
                    commission=commission or 0.0,
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
                        "commission": commission or 0.0,
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

        if commission is None:
            configured_fee = resolve_manual_trade_fee_breakdown(
                state.config,
                asset_class=body.asset_class,
                direction=body.direction,
                quantity=quantity,
                price=price,
            )
            if configured_fee is None:
                commission = 0.0
            else:
                commission = configured_fee.commission
                if not note.strip():
                    note = configured_fee.note

        gross_amount = float(quantity) * float(price)
        total_fee = (
            configured_fee.total_fee
            if configured_fee is not None
            else float(commission)
        )
        fee_breakdown_json = (
            configured_fee.fee_breakdown_json
            if configured_fee is not None
            else _manual_trade_fee_breakdown(commission)
        )
        fee_rule_id = (
            configured_fee.fee_rule_id
            if configured_fee is not None
            else MANUAL_FEE_INPUT_RULE_ID
        )
        fee_rule_version = (
            configured_fee.fee_rule_version
            if configured_fee is not None
            else MANUAL_FEE_INPUT_RULE_VERSION
        )

        trade_id = await db.add_trade(
            timestamp=body.timestamp,
            symbol=symbol,
            direction=body.direction,
            quantity=quantity,
            price=price,
            commission=commission,
            asset_class=body.asset_class,
            note=note,
        )
        db.insert_ledger_entry_sync(
            entry_type=f"trade_{body.direction}",
            timestamp=body.timestamp,
            amount=gross_amount,
            symbol=symbol,
            direction=body.direction,
            quantity=float(quantity),
            price=float(price),
            commission=commission,
            gross_amount=gross_amount,
            net_cash_impact=_manual_trade_net_cash_impact(
                direction=body.direction,
                gross_amount=gross_amount,
                total_fee=total_fee,
            ),
            fee_breakdown_json=json.dumps(
                fee_breakdown_json,
                ensure_ascii=False,
                sort_keys=True,
            ),
            fee_rule_id=fee_rule_id,
            fee_rule_version=fee_rule_version,
            cost_basis_method="moving_average_buy_cost",
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
                        commission=Decimal(str(commission)),
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
