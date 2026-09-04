"""Portfolio snapshot HTTP endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from server.contracts.http.ledger_models import EquityPoint
from server.contracts.http.portfolio_models import (
    AccountOverview,
    AccountStateResponse,
    ActionCard,
    AllocationItem,
    CurrentHoldingMarketEvidenceReviewResponse,
    LiveHoldingsResponse,
    PortfolioCockpitPosition,
    PortfolioCockpitResponse,
    PortfolioSnapshot,
    PositionResponse,
    RiskSummaryItem,
)
from server.http.portfolio_endpoints.dependencies import (
    PortfolioPerformanceOperations,
    PortfolioSnapshotDependencies,
    PortfolioSnapshotOperations,
)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotEndpoints:
    router: APIRouter
    operations: PortfolioSnapshotOperations


def create_router(
    dependencies: PortfolioSnapshotDependencies,
    performance: PortfolioPerformanceOperations,
) -> PortfolioSnapshotEndpoints:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    _build_live_holdings_response = dependencies.build_live_holdings_response
    _cash_flow_adjusted_equity_points_from_series = (
        dependencies.cash_flow_adjusted_equity_points_from_series
    )
    _collect_latest_quote_timestamps = dependencies.collect_latest_quote_timestamps
    _equity_series_matches_valuation = dependencies.equity_series_matches_valuation
    _overview_daily_operations_summary = dependencies.overview_daily_operations_summary
    _overview_today_pnl_update = dependencies.overview_today_pnl_update
    _portfolio_account_truth_gate_status = (
        dependencies.portfolio_account_truth_gate_status
    )
    _portfolio_construction_recommendations = (
        dependencies.portfolio_construction_recommendations
    )
    _with_overview_quote_metadata = dependencies.with_overview_quote_metadata
    build_account_state_projection = dependencies.build_account_state_projection
    build_account_state_response = dependencies.build_account_state_response
    build_current_holding_market_evidence_review = (
        dependencies.build_current_holding_market_evidence_review
    )
    build_current_valuation_snapshot = dependencies.build_current_valuation_snapshot
    build_portfolio_snapshot = dependencies.build_portfolio_snapshot
    build_risk_summary = dependencies.build_risk_summary
    build_risk_workspace = dependencies.build_risk_workspace
    get_shanghai_now = dependencies.get_shanghai_now
    valuation_snapshot_from_row = dependencies.valuation_snapshot_from_row

    @r.post("/valuation-snapshots")
    async def create_valuation_snapshot() -> dict:
        """Persist an immutable valuation identity from current database facts."""
        state = dependencies.get_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        return build_current_valuation_snapshot(
            state.db,
            persist=True,
            now=get_shanghai_now(),
        )

    @r.get("/valuation-snapshots/{snapshot_id}")
    async def get_valuation_snapshot(snapshot_id: str) -> dict:
        """Read one persisted valuation snapshot without refreshing providers."""
        state = dependencies.get_state()
        if state.db is None or not hasattr(state.db, "get_valuation_snapshot_sync"):
            raise HTTPException(status_code=503, detail="database unavailable")
        row = state.db.get_valuation_snapshot_sync(snapshot_id)
        if row is None:
            raise HTTPException(status_code=404, detail="valuation snapshot not found")
        return valuation_snapshot_from_row(row)

    @r.get("", response_model=PortfolioSnapshot)
    async def get_portfolio() -> PortfolioSnapshot:
        """获取当前持仓 + 现金 + 总权益 + 资产配置。"""
        return await build_portfolio_snapshot(dependencies.get_state())

    @r.get(
        "/market-evidence-review",
        response_model=CurrentHoldingMarketEvidenceReviewResponse,
    )
    async def get_current_holding_market_evidence_review() -> (
        CurrentHoldingMarketEvidenceReviewResponse
    ):
        """Project current holding quote blockers from one persisted snapshot."""
        snapshot = await build_portfolio_snapshot(dependencies.get_state())
        return build_current_holding_market_evidence_review(snapshot)

    @r.get("/live-holdings", response_model=LiveHoldingsResponse)
    async def get_live_holdings() -> LiveHoldingsResponse:
        """按资产类别返回当前持仓的实时价格、累计收益和日内变化。"""
        state = dependencies.get_state()
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
        state = dependencies.get_state()
        snapshot = await get_portfolio()
        projection = build_account_state_projection(
            snapshot,
            build_risk_summary(snapshot, _collect_latest_quote_timestamps(state)),
        )
        overview = _with_overview_quote_metadata(projection.summary, snapshot)
        live_holdings = _build_live_holdings_response(state)
        equity_series = await performance.get_equity_curve_series("all")
        equity_curve = _cash_flow_adjusted_equity_points_from_series(
            state,
            equity_series,
        )
        equity_valuation_consistent = _equity_series_matches_valuation(
            equity_series,
            snapshot.valuation_snapshot_id,
        )
        if not equity_valuation_consistent and snapshot.total_equity is not None:
            equity_curve = [
                EquityPoint(
                    timestamp=snapshot.valuation_as_of
                    or get_shanghai_now().isoformat(),
                    equity=snapshot.total_equity,
                )
            ]
        elif not equity_curve:
            equity_curve = await performance.get_equity_curve()
        risk_workspace = build_risk_workspace(snapshot, equity_curve)
        valuation_consistent = (
            snapshot.valuation_snapshot_id == live_holdings.valuation_snapshot_id
            and equity_valuation_consistent
        )
        today_pnl_update = (
            _overview_today_pnl_update(live_holdings, snapshot)
            if valuation_consistent
            else {
                "today_pnl": None,
                "today_pnl_breakdown": None,
                "today_contributors": [],
                "quote_status": "missing",
                "stale_reason": "valuation_snapshot_changed_during_request",
            }
        )
        drawdown = risk_workspace.drawdown
        return overview.model_copy(
            update={
                **today_pnl_update,
                "current_drawdown": (
                    None if drawdown is None else drawdown.current_drawdown
                ),
                "current_drawdown_amount": (
                    None
                    if drawdown is None
                    else max(drawdown.peak_equity - drawdown.latest_equity, 0.0)
                ),
                "drawdown_peak_equity": (
                    None if drawdown is None else drawdown.peak_equity
                ),
                "drawdown_latest_equity": (
                    None if drawdown is None else drawdown.latest_equity
                ),
                "drawdown_peak_timestamp": (
                    None if drawdown is None else drawdown.peak_timestamp
                ),
                "daily_operations": _overview_daily_operations_summary(state),
            }
        )

    @r.get("/state", response_model=AccountStateResponse)
    async def get_account_state() -> AccountStateResponse:
        """获取规范化账户状态投影。"""
        return await build_account_state_response(dependencies.get_state())

    @r.get("/cockpit", response_model=PortfolioCockpitResponse)
    async def get_portfolio_cockpit() -> PortfolioCockpitResponse:
        """Return portfolio weights, drift, action queue, and risk alerts."""
        state = dependencies.get_state()
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
                float(position.market_value) / snapshot.total_equity
                if position.market_value is not None
                and snapshot.total_equity is not None
                and snapshot.total_equity > 0
                else None
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
                    drift=(
                        None
                        if target_weight is None or actual_weight is None
                        else target_weight - actual_weight
                    ),
                    action_task=action,
                )
            )

        return PortfolioCockpitResponse(
            summary=_with_overview_quote_metadata(projection.summary, snapshot),
            positions=positions,
            action_queue=action_queue,
            risk_alerts=projection.risks,
            construction_recommendations=_portfolio_construction_recommendations(
                positions,
                account_truth_gate_status=_portfolio_account_truth_gate_status(state),
            ),
        )

    @r.get("/risk-summary", response_model=list[RiskSummaryItem])
    async def get_risk_summary() -> list[RiskSummaryItem]:
        """获取首页风险摘要。"""
        state = dependencies.get_state()
        snapshot = await get_portfolio()
        return build_risk_summary(snapshot, _collect_latest_quote_timestamps(state))

    return PortfolioSnapshotEndpoints(
        router=r,
        operations=PortfolioSnapshotOperations(get_portfolio=get_portfolio),
    )


__all__ = ["PortfolioSnapshotEndpoints", "create_router"]
