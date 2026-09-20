"""Canonical account state projection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.contracts.http.portfolio_models import (
    OverviewMarketSession,
    OverviewRefreshHealth,
    OverviewState,
)
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
    if summary.total_equity is not None and summary.unrealized_pnl is not None:
        summary.realized_pnl = (
            summary.total_equity - summary.total_deposits - summary.unrealized_pnl
        )
        summary.cumulative_pnl = summary.realized_pnl + summary.unrealized_pnl
    else:
        summary.cumulative_pnl = None
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


def build_overview_state(
    snapshot: PortfolioSnapshot,
    *,
    market_session: dict[str, Any],
    refresh_health: OverviewRefreshHealth,
    operations: dict[str, Any] | None,
    user_attention: list[dict[str, Any]],
) -> OverviewState:
    """Describe independent uses of one account valuation without granting authority."""
    usable = (
        snapshot.valuation_status == "complete"
        and not snapshot.valuation_blockers
        and snapshot.total_equity is not None
    )
    dates = [
        position.pricing_as_of
        for position in snapshot.positions
        if position.pricing_as_of
    ]
    plan = (operations or {}).get("daily_plan") or {}
    required_gates = {"market_data", "account_truth", "risk", "paper_shadow"}
    gate_states = {
        item.get("id"): item.get("status")
        for item in (operations or {}).get("subsystems", [])
        if item.get("id") in required_gates
    }
    decision_readiness = "unknown"
    if (
        not usable
        or int(plan.get("blocked_count") or 0) > 0
        or any(status == "blocked" for status in gate_states.values())
    ):
        decision_readiness = "blocked"
    elif (
        int(plan.get("manual_ready_count") or 0) > 0
        and market_session.get("calendar_verified")
        and set(gate_states) == required_gates
        and all(status == "pass" for status in gate_states.values())
    ):
        decision_readiness = "ready"
    return OverviewState(
        market_session=OverviewMarketSession.model_validate(market_session),
        valuation_usability=(
            "usable" if usable else "degraded" if snapshot.positions else "unavailable"
        ),
        pricing_as_of=min(dates) if dates else snapshot.valuation_trade_date,
        refresh_health=refresh_health,
        decision_readiness=decision_readiness,
        user_attention=user_attention,
        attention_status="available" if operations is not None else "unavailable",
    )


def read_overview_refresh_health(db: Any) -> OverviewRefreshHealth:
    """A later attempt is operational evidence, never a valuation override."""
    reader = getattr(db, "list_quote_fetch_runs", None)
    if not callable(reader):
        return OverviewRefreshHealth(status="unknown")
    runs = reader(limit=1)
    attempt = runs[0] if runs else None
    if not isinstance(attempt, dict):
        return OverviewRefreshHealth(status="unknown")
    status = str(attempt.get("status") or "")
    return OverviewRefreshHealth(
        status=(
            "degraded"
            if status in {"failed", "error", "blocked", "partial"}
            else (
                "running"
                if status in {"running", "pending"}
                else (
                    "healthy"
                    if status in {"success", "ready", "complete", "succeeded"}
                    else "unknown"
                )
            )
        ),
        latest_attempt=attempt,
        blockers=list(attempt.get("blockers") or []),
    )
