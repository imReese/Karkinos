"""Portfolio snapshot HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any, endpoints: dict[str, Any]) -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    AccountOverview = dependency("AccountOverview")
    AccountStateResponse = dependency("AccountStateResponse")
    ActionCard = dependency("ActionCard")
    AllocationItem = dependency("AllocationItem")
    CurrentHoldingMarketEvidenceReviewResponse = dependency(
        "CurrentHoldingMarketEvidenceReviewResponse"
    )
    EquityPoint = dependency("EquityPoint")
    HTTPException = dependency("HTTPException")
    LiveHoldingsResponse = dependency("LiveHoldingsResponse")
    PortfolioCockpitPosition = dependency("PortfolioCockpitPosition")
    PortfolioCockpitResponse = dependency("PortfolioCockpitResponse")
    PortfolioSnapshot = dependency("PortfolioSnapshot")
    PositionResponse = dependency("PositionResponse")
    RiskSummaryItem = dependency("RiskSummaryItem")
    _build_live_holdings_response = dependency("_build_live_holdings_response")
    _cash_flow_adjusted_equity_points_from_series = dependency(
        "_cash_flow_adjusted_equity_points_from_series"
    )
    _collect_latest_quote_timestamps = dependency("_collect_latest_quote_timestamps")
    _equity_series_matches_valuation = dependency("_equity_series_matches_valuation")
    _overview_daily_operations_summary = dependency(
        "_overview_daily_operations_summary"
    )
    _overview_today_pnl_update = dependency("_overview_today_pnl_update")
    _portfolio_account_truth_gate_status = dependency(
        "_portfolio_account_truth_gate_status"
    )
    _portfolio_construction_recommendations = dependency(
        "_portfolio_construction_recommendations"
    )
    _with_overview_quote_metadata = dependency("_with_overview_quote_metadata")
    build_account_state_projection = dependency("build_account_state_projection")
    build_account_state_response = dependency("build_account_state_response")
    build_current_holding_market_evidence_review = dependency(
        "build_current_holding_market_evidence_review"
    )
    build_current_valuation_snapshot = dependency("build_current_valuation_snapshot")
    build_portfolio_snapshot = dependency("build_portfolio_snapshot")
    build_risk_summary = dependency("build_risk_summary")
    build_risk_workspace = dependency("build_risk_workspace")
    get_shanghai_now = dependency("get_shanghai_now")
    valuation_snapshot_from_row = dependency("valuation_snapshot_from_row")

    def get_equity_curve(*args, **kwargs):
        return endpoints["get_equity_curve"](*args, **kwargs)

    def get_equity_curve_series(*args, **kwargs):
        return endpoints["get_equity_curve_series"](*args, **kwargs)

    @r.post("/valuation-snapshots")
    async def create_valuation_snapshot() -> dict:
        """Persist an immutable valuation identity from current database facts."""
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        return build_current_valuation_snapshot(state.db)

    @r.get("/valuation-snapshots/{snapshot_id}")
    async def get_valuation_snapshot(snapshot_id: str) -> dict:
        """Read one persisted valuation snapshot without refreshing providers."""
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "get_valuation_snapshot_sync"):
            raise HTTPException(status_code=503, detail="database unavailable")
        row = state.db.get_valuation_snapshot_sync(snapshot_id)
        if row is None:
            raise HTTPException(status_code=404, detail="valuation snapshot not found")
        return valuation_snapshot_from_row(row)

    @r.get("", response_model=PortfolioSnapshot)
    async def get_portfolio() -> PortfolioSnapshot:
        """获取当前持仓 + 现金 + 总权益 + 资产配置。"""
        from server.dependencies import get_app_state

        return await build_portfolio_snapshot(get_app_state())

    @r.get(
        "/market-evidence-review",
        response_model=CurrentHoldingMarketEvidenceReviewResponse,
    )
    async def get_current_holding_market_evidence_review() -> (
        CurrentHoldingMarketEvidenceReviewResponse
    ):
        """Project current holding quote blockers from one persisted snapshot."""
        from server.dependencies import get_app_state

        snapshot = await build_portfolio_snapshot(get_app_state())
        return build_current_holding_market_evidence_review(snapshot)

    @r.get("/live-holdings", response_model=LiveHoldingsResponse)
    async def get_live_holdings() -> LiveHoldingsResponse:
        """按资产类别返回当前持仓的实时价格、累计收益和日内变化。"""
        from server.dependencies import get_app_state

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
        from server.dependencies import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        projection = build_account_state_projection(
            snapshot,
            build_risk_summary(snapshot, _collect_latest_quote_timestamps(state)),
        )
        overview = _with_overview_quote_metadata(projection.summary, snapshot)
        live_holdings = _build_live_holdings_response(state)
        equity_series = await get_equity_curve_series("all")
        equity_curve = _cash_flow_adjusted_equity_points_from_series(
            state,
            equity_series,
        )
        equity_valuation_consistent = _equity_series_matches_valuation(
            equity_series,
            snapshot.valuation_snapshot_id,
        )
        if not equity_valuation_consistent:
            equity_curve = [
                EquityPoint(
                    timestamp=snapshot.valuation_as_of
                    or get_shanghai_now().isoformat(),
                    equity=snapshot.total_equity,
                )
            ]
        elif not equity_curve:
            equity_curve = await get_equity_curve()
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
        return overview.model_copy(
            update={
                **today_pnl_update,
                "current_drawdown": risk_workspace.drawdown.current_drawdown,
                "current_drawdown_amount": max(
                    risk_workspace.drawdown.peak_equity
                    - risk_workspace.drawdown.latest_equity,
                    0.0,
                ),
                "drawdown_peak_equity": risk_workspace.drawdown.peak_equity,
                "drawdown_latest_equity": risk_workspace.drawdown.latest_equity,
                "drawdown_peak_timestamp": risk_workspace.drawdown.peak_timestamp,
                "daily_operations": _overview_daily_operations_summary(state),
            }
        )

    @r.get("/state", response_model=AccountStateResponse)
    async def get_account_state() -> AccountStateResponse:
        """获取规范化账户状态投影。"""
        from server.dependencies import get_app_state

        return await build_account_state_response(get_app_state())

    @r.get("/cockpit", response_model=PortfolioCockpitResponse)
    async def get_portfolio_cockpit() -> PortfolioCockpitResponse:
        """Return portfolio weights, drift, action queue, and risk alerts."""
        from server.dependencies import get_app_state

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
            construction_recommendations=_portfolio_construction_recommendations(
                positions,
                account_truth_gate_status=_portfolio_account_truth_gate_status(state),
            ),
        )

    @r.get("/risk-summary", response_model=list[RiskSummaryItem])
    async def get_risk_summary() -> list[RiskSummaryItem]:
        """获取首页风险摘要。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        return build_risk_summary(snapshot, _collect_latest_quote_timestamps(state))

    endpoints["get_portfolio"] = get_portfolio
    return r
