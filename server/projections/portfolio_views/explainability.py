"""Canonical portfolio explainability projections."""

from __future__ import annotations

from collections import defaultdict

from server.models import (
    AccountOverview,
    ActivityItem,
    EquityPoint,
    EquitySeriesPoint,
    ExplainabilityBridgeItem,
    ExplainabilityDriver,
    ExplainabilityPositionDriver,
    ExplainabilityTimelineBreakdownItem,
    ExplainabilityTimelineEvent,
    ExplainabilityTimelinePoint,
    PortfolioSnapshot,
)
from server.projections.portfolio_application import (
    ledger_entry_trade_total_fee as _ledger_entry_trade_total_fee,
)
from server.projections.portfolio_application import (
    normalize_asset_class as _normalize_asset_class,
)
from server.projections.portfolio_application import (
    parse_fee_breakdown as _parse_fee_breakdown,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.services.asset_metadata import resolve_asset_metadata
from server.services.daily_performance import (
    calculate_account_daily_performance,
)

_ASSET_CLASS_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
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


def build_activity_items(
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


def ledger_entry_display_label(state, entry: dict) -> str | None:
    symbol = entry.get("symbol")
    if not symbol:
        return None
    symbol_text = str(symbol)
    display_name = resolve_asset_metadata(
        state,
        symbol_text,
        fallback_name=entry.get("display_name") or symbol_text,
    ).display_name
    if display_name and display_name != symbol_text:
        return f"{display_name} {symbol_text}"
    return symbol_text


def build_recent_drivers(state, entries: list[dict]) -> list[ExplainabilityDriver]:
    drivers: list[ExplainabilityDriver] = []
    for entry in entries:
        entry_type = entry.get("entry_type")
        symbol = entry.get("symbol")
        instrument_label = ledger_entry_display_label(state, entry) or symbol
        amount = entry.get("amount")
        title = entry_type or "ledger"
        detail = entry.get("note") or "账本活动。"
        structured_fields = ledger_entry_structured_explainability_fields(entry)

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
            amount = -(ledger_entry_notional(entry) + commission)
            detail = entry.get("note") or ""
        elif entry_type == "trade_sell":
            quantity = float(entry.get("quantity") or 0.0)
            price = float(entry.get("price") or 0.0)
            commission = float(entry.get("commission") or 0.0)
            title = f"卖出 {instrument_label}"
            amount = ledger_entry_notional(entry) - commission
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


def timeline_date_from_timestamp(timestamp: str) -> str:
    parsed = _parse_quote_timestamp(timestamp)
    if parsed is not None:
        return parsed.date().isoformat()
    return timestamp.split("T")[0]


def ledger_entry_notional(entry: dict) -> float:
    amount = entry.get("amount")
    if amount is not None:
        return abs(float(amount))
    quantity = entry.get("quantity")
    price = entry.get("price")
    if quantity is None or price is None:
        return 0.0
    return abs(float(quantity) * float(price))


def ledger_entry_structured_explainability_fields(entry: dict) -> dict:
    entry_type = entry.get("entry_type")
    if entry_type not in {"trade_buy", "trade_sell"}:
        return {}

    quantity = optional_float(entry.get("quantity"))
    price = optional_float(entry.get("price"))
    commission = optional_float(entry.get("commission"))
    gross_amount = optional_float(entry.get("gross_amount"))
    if gross_amount is None:
        gross_amount = ledger_entry_notional(entry)
    total_fee = _ledger_entry_trade_total_fee(entry)

    if entry_type == "trade_buy":
        net_cash_impact = optional_float(entry.get("net_cash_impact"))
        if net_cash_impact is None:
            net_cash_impact = -(gross_amount + total_fee)
    else:
        net_cash_impact = optional_float(entry.get("net_cash_impact"))
        if net_cash_impact is None:
            net_cash_impact = gross_amount - total_fee

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


def optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_timeline_breakdown_items(
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


def equity_series_components_by_date(
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


def build_timeline(
    equity_curve: list[EquityPoint | EquitySeriesPoint],
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
        event_date = timeline_date_from_timestamp(timestamp)
        entry_type = entry.get("entry_type") or "ledger"
        if event_kind and entry_type != event_kind:
            continue
        symbol = entry.get("symbol")
        instrument_label = ledger_entry_display_label(state, entry) or symbol
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
            trade_fields = ledger_entry_structured_explainability_fields(entry)
            net_cash_impact = trade_fields.get("net_cash_impact")
            positioning_flow_by_date[event_date][asset_class] += (
                -float(net_cash_impact)
                if net_cash_impact is not None
                else ledger_entry_notional(entry)
            )
        elif entry_type == "trade_sell":
            quantity = float(entry.get("quantity") or 0.0)
            price = float(entry.get("price") or 0.0)
            title = f"卖出 {instrument_label}"
            detail = entry.get("note") or ""
            amount = None
            category = "trade"
            impact_source = "positioning"
            trade_fields = ledger_entry_structured_explainability_fields(entry)
            net_cash_impact = trade_fields.get("net_cash_impact")
            positioning_flow_by_date[event_date][asset_class] += (
                -float(net_cash_impact)
                if net_cash_impact is not None
                else -ledger_entry_notional(entry)
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
                **ledger_entry_structured_explainability_fields(entry),
            )
        )

    timeline: list[ExplainabilityTimelinePoint] = []
    previous_equity: float | None = None
    previous_components: dict[str, float] | None = None
    previous_valuation_status = "complete"
    previous_missing_price_symbols: list[str] = []
    for point in equity_curve:
        point_date = point.timestamp.split("T")[0]
        point_equity = optional_float(
            getattr(point, "equity", getattr(point, "total", None))
        )
        point_components = (component_values_by_date or {}).get(point_date)
        if from_date and point_date < from_date:
            previous_equity = point_equity
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
        external_flow = external_flow_by_date.get(point_date, 0.0)
        if point_equity is None:
            delta = 0.0
            market_pnl = 0.0
        else:
            daily_performance = calculate_account_daily_performance(
                starting_equity=previous_equity,
                ending_equity=point_equity,
                external_flow=external_flow,
            )
            delta = daily_performance.equity_delta
            market_pnl = daily_performance.market_move
        point_valuation_status = (valuation_status_by_date or {}).get(
            point_date, "complete"
        )
        point_missing_price_symbols = (missing_price_symbols_by_date or {}).get(
            point_date, []
        )
        valuation_status = point_valuation_status
        missing_price_symbols = point_missing_price_symbols
        if previous_equity is not None and (
            is_missing_equity_quote_status(point_valuation_status)
            or is_missing_equity_quote_status(previous_valuation_status)
            or point_valuation_status == "partial"
            or previous_valuation_status == "partial"
        ):
            valuation_status = (
                "missing"
                if "partial" in {point_valuation_status, previous_valuation_status}
                else merge_equity_series_quote_status(
                    point_valuation_status,
                    previous_valuation_status,
                )
            )
            market_pnl = 0.0
            missing_price_symbols = sorted(
                set(missing_price_symbols) | set(previous_missing_price_symbols)
            )
        market_breakdown: list[ExplainabilityTimelineBreakdownItem] = []
        if (
            not is_missing_equity_quote_status(valuation_status)
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
            residual = market_pnl - sum(market_values.values())
            if abs(residual) > 1e-9:
                market_values["residual"] = residual
            market_breakdown = build_timeline_breakdown_items(
                market_values,
                _ASSET_CLASS_LABELS,
            )
        external_flow_breakdown = build_timeline_breakdown_items(
            dict(external_flow_breakdown_by_date.get(point_date, {})),
            _EXTERNAL_FLOW_LABELS,
        )
        timeline.append(
            ExplainabilityTimelinePoint(
                date=point_date,
                equity=point_equity,
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
        previous_equity = point_equity
        previous_components = point_components
        previous_valuation_status = point_valuation_status
        previous_missing_price_symbols = point_missing_price_symbols

    return timeline


def build_position_drivers(
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
                asset_class=(
                    asset_class_by_symbol.get(position.symbol)
                    or position.asset_class
                    or "other"
                ),
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


def build_equity_bridge(
    snapshot: PortfolioSnapshot, summary: AccountOverview
) -> list[ExplainabilityBridgeItem]:
    valuation_available = (
        snapshot.total_equity is not None and summary.unrealized_pnl is not None
    )
    market_value = (
        max(snapshot.total_equity - snapshot.cash, 0)
        if snapshot.total_equity is not None
        else None
    )
    total_pnl = (
        summary.realized_pnl + summary.unrealized_pnl
        if summary.unrealized_pnl is not None
        else None
    )
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
            detail=(
                "Mark-to-market move on current positions."
                if valuation_available
                else "Unavailable because current market evidence is incomplete."
            ),
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
            detail=(
                "Current marked value of open positions."
                if valuation_available
                else "Unavailable because current market evidence is incomplete."
            ),
        ),
        ExplainabilityBridgeItem(
            key="equity",
            label="Total Equity",
            value=snapshot.total_equity,
            detail=(
                f"Deposits plus total PnL ({total_pnl:.2f})."
                if total_pnl is not None
                else "Unavailable because current market evidence is incomplete."
            ),
        ),
    ]


def merge_equity_series_quote_status(current: str, candidate: str) -> str:
    priority = {
        "missing": 50,
        "error": 50,
        "confirmed_nav_missing": 40,
        "degraded": 35,
        "estimated": 30,
        "stale": 20,
        "cache": 10,
        "live": 0,
        "confirmed": 0,
    }
    return (
        candidate if priority.get(candidate, 0) > priority.get(current, 0) else current
    )


def is_missing_equity_quote_status(status: str | None) -> bool:
    return str(status or "").strip().lower() in {
        "missing",
        "error",
        "degraded",
        "estimated",
        "confirmed_nav_missing",
        "confirmed_fund_nav_missing_estimate_only",
    }


__all__ = (
    "build_activity_items",
    "build_equity_bridge",
    "build_position_drivers",
    "build_recent_drivers",
    "build_timeline",
    "build_timeline_breakdown_items",
    "equity_series_components_by_date",
    "is_missing_equity_quote_status",
    "ledger_entry_display_label",
    "ledger_entry_notional",
    "ledger_entry_structured_explainability_fields",
    "merge_equity_series_quote_status",
    "optional_float",
    "timeline_date_from_timestamp",
)
