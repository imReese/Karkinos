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
    valuation_complete = (
        snapshot.valuation_status == "complete"
        and not snapshot.valuation_blockers
        and snapshot.total_equity is not None
    )
    total_equity = snapshot.total_equity if valuation_complete else None
    cash_ratio = (
        snapshot.cash / total_equity
        if total_equity is not None and total_equity > 0
        else (0.0 if total_equity == 0 else None)
    )
    realized_pnl = snapshot.realized_pnl_total
    if realized_pnl is None:
        all_position_facts = [
            *snapshot.positions,
            *snapshot.closed_positions,
            *(item.position for item in snapshot.position_review_items),
        ]
        realized_pnl = sum(position.realized_pnl for position in all_position_facts)
    summary = AccountOverview(
        total_equity=total_equity,
        available_cash=snapshot.cash,
        total_deposits=snapshot.total_deposits,
        positions_count=len(snapshot.positions),
        unrealized_pnl=(
            sum(float(position.unrealized_pnl) for position in snapshot.positions)
            if valuation_complete
            and all(
                position.unrealized_pnl is not None and position.valuation_available
                for position in snapshot.positions
            )
            else None
        ),
        realized_pnl=realized_pnl,
        cash_ratio=cash_ratio,
        valuation_snapshot_id=snapshot.valuation_snapshot_id,
        valuation_as_of=snapshot.valuation_as_of,
        valuation_trade_date=snapshot.valuation_trade_date,
        valuation_policy=snapshot.valuation_policy,
        valuation_status=snapshot.valuation_status,
        ledger_cutoff_id=snapshot.ledger_cutoff_id,
        ledger_fingerprint=snapshot.ledger_fingerprint,
        quote_set_fingerprint=snapshot.quote_set_fingerprint,
        missing_price_symbols=snapshot.missing_price_symbols,
        valuation_blockers=snapshot.valuation_blockers,
    )
    if not valuation_complete:
        next_step = "补齐并复核市场数据证据"
    elif any(item.level in {"medium", "high"} for item in risks):
        next_step = "复核风险后再确认任何建议"
    else:
        next_step = "继续观察市场"
    return AccountStateProjection(
        summary=summary,
        snapshot=snapshot,
        risks=risks,
        next_step=next_step,
    )
