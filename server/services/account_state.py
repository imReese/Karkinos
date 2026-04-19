"""Canonical account state projection helpers."""

from __future__ import annotations

from dataclasses import dataclass

from server.models import AccountOverview, PortfolioSnapshot, RiskSummaryItem


@dataclass(slots=True)
class AccountStateProjection:
    """Projected account state for homepage and API consumers."""

    summary: AccountOverview
    snapshot: PortfolioSnapshot
    risks: list[RiskSummaryItem]
    next_step: str


def build_account_state_projection(
    snapshot: PortfolioSnapshot,
    risks: list[RiskSummaryItem],
) -> AccountStateProjection:
    """Build the canonical account state projection from portfolio inputs."""
    total_equity = snapshot.total_equity
    cash_ratio = snapshot.cash / total_equity if total_equity > 0 else 0.0
    summary = AccountOverview(
        total_equity=total_equity,
        available_cash=snapshot.cash,
        total_deposits=snapshot.total_deposits,
        positions_count=len(snapshot.positions),
        unrealized_pnl=sum(position.unrealized_pnl for position in snapshot.positions),
        realized_pnl=sum(position.realized_pnl for position in snapshot.positions),
        cash_ratio=cash_ratio,
    )
    next_step = (
        "确认待执行建议"
        if any(item.level in {"medium", "high"} for item in risks)
        else "继续观察市场"
    )
    return AccountStateProjection(
        summary=summary,
        snapshot=snapshot,
        risks=risks,
        next_step=next_step,
    )
