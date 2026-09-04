from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from server.models import PortfolioSnapshot, RiskSummaryItem

_SH_TZ = ZoneInfo("Asia/Shanghai")


def _parse_quote_time(timestamp: str) -> datetime | None:
    try:
        quote_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if quote_time.tzinfo is None:
        return quote_time.replace(tzinfo=_SH_TZ)
    return quote_time.astimezone(_SH_TZ)


def build_risk_summary(
    snapshot: PortfolioSnapshot, latest_quote_timestamps: dict[str, str]
) -> list[RiskSummaryItem]:
    items: list[RiskSummaryItem] = []

    missing_symbols = sorted(
        set(snapshot.missing_price_symbols)
        | {
            position.symbol
            for position in snapshot.positions
            if not position.valuation_available
            or position.market_value is None
            or position.unrealized_pnl is None
        }
    )
    if (
        snapshot.valuation_status != "complete"
        or snapshot.valuation_blockers
        or snapshot.total_equity is None
        or missing_symbols
    ):
        named_blockers = sorted(set(snapshot.valuation_blockers))
        detail = "持仓估值证据不完整，权威收益、敞口、集中度和回撤计算已阻断"
        if named_blockers:
            detail += f"：{', '.join(named_blockers)}"
        elif missing_symbols:
            detail += f"：{', '.join(missing_symbols)}"
        return [
            RiskSummaryItem(
                kind="data",
                level="high",
                title="权威风险结果不可用",
                detail=detail,
            )
        ]

    if snapshot.total_equity > 0:
        non_cash = [item for item in snapshot.allocation if item.asset_class != "cash"]
        largest = max(non_cash, key=lambda item: item.weight, default=None)
        if largest and largest.weight >= 0.6:
            items.append(
                RiskSummaryItem(
                    kind="risk",
                    level="high",
                    title="仓位集中度偏高",
                    detail=f"{largest.name} 占总资产 {(largest.weight * 100):.1f}%",
                )
            )

        cash_ratio = snapshot.cash / snapshot.total_equity
        if cash_ratio <= 0.15:
            items.append(
                RiskSummaryItem(
                    kind="risk",
                    level="medium",
                    title="现金缓冲偏低",
                    detail=f"当前现金占比 {(cash_ratio * 100):.1f}%，可用调仓空间有限",
                )
            )

    threshold = datetime.now(_SH_TZ) - timedelta(days=1)
    for symbol, timestamp in latest_quote_timestamps.items():
        quote_time = _parse_quote_time(timestamp)
        if quote_time is None:
            continue
        if quote_time < threshold:
            items.append(
                RiskSummaryItem(
                    kind="data",
                    level="medium",
                    title="行情数据可能过旧",
                    detail=f"{symbol} 最新快照时间 {timestamp}",
                )
            )
            break

    if not items:
        items.append(
            RiskSummaryItem(
                kind="status",
                level="low",
                title="当前风险可控",
                detail="未发现明显的仓位集中、现金缓冲或数据时效问题",
            )
        )

    return items
