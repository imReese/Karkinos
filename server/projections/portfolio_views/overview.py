"""Canonical portfolio overview projections."""

from __future__ import annotations

import json

from server.models import (
    DailyOperationsSummary,
    LiveHoldingsResponse,
    PortfolioCockpitPosition,
    PortfolioConstructionRecommendation,
    PortfolioSnapshot,
    TodayPnlBreakdown,
    TodayPnlContributor,
)
from server.projections.portfolio_application import (
    normalize_asset_class as _normalize_asset_class,
)
from server.services.daily_operations import build_daily_operations_summary


def overview_today_pnl_update(
    live_holdings: LiveHoldingsResponse,
    snapshot: PortfolioSnapshot | None = None,
) -> dict[str, object]:
    daily_positions = [item for group in live_holdings.groups for item in group.items]
    if snapshot is not None:
        daily_positions.extend(snapshot.closed_positions)
    if any(position.today_change is None for position in daily_positions):
        return {
            "today_pnl": None,
            "today_pnl_breakdown": None,
            "today_contributors": [],
            "quote_status": "missing",
            "stale_reason": "daily_baseline_unavailable",
        }

    stocks = 0.0
    funds = 0.0
    others = 0.0
    contributors: list[TodayPnlContributor] = []

    for position in daily_positions:
        asset_class = _normalize_asset_class(position.asset_class)
        value = float(position.today_change or 0.0)
        if asset_class == "stock":
            stocks += value
        elif asset_class in {"fund", "etf"}:
            funds += value
        else:
            others += value

        contributors.append(
            TodayPnlContributor(
                symbol=position.symbol,
                name=position.name,
                display_name=position.display_name,
                asset_class=position.asset_class or "other",
                today_change=value,
                today_change_pct=position.today_change_pct,
                quote_status=position.quote_status,
            )
        )

    contributors.sort(key=lambda item: abs(item.today_change), reverse=True)
    total = stocks + funds + others
    return {
        "today_pnl": total,
        "today_pnl_breakdown": TodayPnlBreakdown(
            stocks=stocks,
            funds=funds,
            others=others,
            total=total,
        ),
        "today_contributors": contributors[:3],
    }


def overview_daily_operations_summary(state: object) -> DailyOperationsSummary:
    db = getattr(state, "db", None)
    if db is None:
        return build_daily_operations_summary(
            decision_summary={
                "candidate_count": 0,
                "market_data": {"source_health": "unknown"},
                "account_truth": {"gate_status": "blocked"},
            },
            candidates=[],
            pending_manual_orders=[],
            order_facts=[],
            fill_facts=[],
            ledger_review_count=0,
        )

    action_reader = getattr(db, "get_action_tasks_sync", None)
    actions = (
        list(action_reader(statuses=["pending", "deferred"], limit=50, offset=0))
        if callable(action_reader)
        else []
    )
    manual_reader = getattr(db, "list_manual_orders_sync", None)
    pending_manual_orders = (
        list(manual_reader(status="pending_confirm", limit=50, offset=0))
        if callable(manual_reader)
        else []
    )
    order_reader = getattr(db, "list_orders_sync", None)
    order_facts = (
        list(order_reader(limit=50, offset=0)) if callable(order_reader) else []
    )
    fill_reader = getattr(db, "list_fills_sync", None)
    fill_facts = list(fill_reader(limit=50, offset=0)) if callable(fill_reader) else []
    account_truth = {"gate_status": portfolio_account_truth_gate_status(state)}
    market_data = {"source_health": "live" if actions else "unknown"}

    return build_daily_operations_summary(
        decision_summary={
            "candidate_count": len(actions),
            "risk_blocked_count": sum(
                1
                for action in actions
                if str(action.get("risk_gate_status") or "").strip().lower()
                == "blocked"
            ),
            "ready_for_manual_confirmation_count": sum(
                1
                for action in actions
                if str(action.get("manual_confirmation_status") or "").strip().lower()
                == "ready_for_manual_confirmation"
            ),
            "market_data": market_data,
            "account_truth": account_truth,
        },
        candidates=actions,
        pending_manual_orders=pending_manual_orders,
        order_facts=order_facts,
        fill_facts=fill_facts,
        ledger_review_count=0,
    )


def portfolio_account_truth_gate_status(state: object) -> str:
    db = getattr(state, "db", None)
    if db is None:
        return "blocked"

    from server.account_truth_gate import build_latest_account_truth_score_payload

    payload = dict_payload(build_latest_account_truth_score_payload(state))
    if not payload:
        reader = getattr(db, "get_account_truth_score_sync", None)
        if callable(reader):
            payload = dict_payload(reader())
    if not payload:
        list_reader = getattr(db, "list_account_truth_scores_sync", None)
        if callable(list_reader):
            rows = list_reader(limit=1, offset=0)
            payload = dict_payload(rows[0]) if rows else None

    if not payload:
        return "blocked"

    gate_status = str(payload.get("gate_status") or "").strip().lower()
    if gate_status in {"pass", "degraded", "blocked"}:
        return gate_status

    score = payload.get("score")
    if isinstance(score, int | float):
        if score >= 80:
            return "pass"
        if score >= 60:
            return "degraded"
    return "blocked"


def dict_payload(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def portfolio_construction_recommendations(
    positions: list[PortfolioCockpitPosition],
    *,
    account_truth_gate_status: str,
) -> list[PortfolioConstructionRecommendation]:
    recommendations: list[PortfolioConstructionRecommendation] = []
    for position in positions:
        action = position.action_task
        if action is None:
            continue

        risk_gate_status = str(action.risk_gate_status or "not_checked")
        valuation_available = (
            position.actual_weight is not None
            and position.target_weight is not None
            and position.drift is not None
        )
        actionable = (
            valuation_available
            and account_truth_gate_status == "pass"
            and risk_gate_status == "passed"
        )
        required_actions = portfolio_construction_required_actions(
            account_truth_gate_status=account_truth_gate_status,
            risk_gate_status=risk_gate_status,
        )
        if not valuation_available:
            required_actions.insert(0, "refresh_market_evidence_before_rebalance")
        recommendations.append(
            PortfolioConstructionRecommendation(
                symbol=position.symbol,
                name=position.name,
                asset_class=position.asset_class,
                direction=action.direction,
                status=(
                    portfolio_construction_status(
                        account_truth_gate_status=account_truth_gate_status,
                        risk_gate_status=risk_gate_status,
                    )
                    if valuation_available
                    else "blocked"
                ),
                actionable=actionable,
                actual_weight=position.actual_weight,
                target_weight=position.target_weight,
                drift=position.drift,
                account_truth_gate_status=account_truth_gate_status,
                risk_gate_status=risk_gate_status,
                required_actions=required_actions,
                rationale=(
                    portfolio_construction_rationale(
                        account_truth_gate_status=account_truth_gate_status,
                        risk_gate_status=risk_gate_status,
                        actionable=actionable,
                    )
                    if valuation_available
                    else "持仓行情证据不完整，组合权重与偏离不可用，不能进入执行候选。"
                ),
                source_action_task_id=action.id,
            )
        )
    return recommendations


def portfolio_construction_status(
    *,
    account_truth_gate_status: str,
    risk_gate_status: str,
) -> str:
    if account_truth_gate_status == "pass" and risk_gate_status == "passed":
        return "actionable"
    if account_truth_gate_status == "degraded":
        return "degraded"
    return "blocked"


def portfolio_construction_required_actions(
    *,
    account_truth_gate_status: str,
    risk_gate_status: str,
) -> list[str]:
    actions: list[str] = []
    if account_truth_gate_status != "pass":
        actions.extend(
            [
                "import_and_reconcile_broker_evidence",
                "resolve_account_truth_before_rebalance",
            ]
        )
    if risk_gate_status == "blocked":
        actions.append("review_blocked_risk_gate")
    elif risk_gate_status != "passed":
        actions.append("run_pre_trade_risk_gate")
    return actions


def portfolio_construction_rationale(
    *,
    account_truth_gate_status: str,
    risk_gate_status: str,
    actionable: bool,
) -> str:
    if actionable:
        return "账户事实与风控闸门均已通过，组合构建建议可进入人工复核。"
    if account_truth_gate_status != "pass":
        return "账户事实未通过，组合构建建议只能用于复核，不能作为可执行候选。"
    if risk_gate_status == "blocked":
        return "风控闸门阻断了该组合构建建议，需要先复核风险原因。"
    return "风控闸门尚未完成检查，该组合构建建议不能作为可执行候选。"


__all__ = (
    "dict_payload",
    "overview_daily_operations_summary",
    "overview_today_pnl_update",
    "portfolio_account_truth_gate_status",
    "portfolio_construction_rationale",
    "portfolio_construction_recommendations",
    "portfolio_construction_required_actions",
    "portfolio_construction_status",
)
