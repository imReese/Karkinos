from __future__ import annotations

from datetime import datetime, timedelta

from server.models import PortfolioSnapshot, RiskSummaryItem


def build_risk_summary(
    snapshot: PortfolioSnapshot, latest_quote_timestamps: dict[str, str]
) -> list[RiskSummaryItem]:
    items: list[RiskSummaryItem] = []

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

    threshold = datetime.now() - timedelta(days=1)
    for symbol, timestamp in latest_quote_timestamps.items():
        try:
            quote_time = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
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
