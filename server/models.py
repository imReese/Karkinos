"""Pydantic v2 schemas for API request/response."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


# ---------- Market ----------


class MarketQuote(BaseModel):
    symbol: str
    price: float
    volume: float | None = None
    timestamp: str | None = None
    asset_class: str | None = None


class WatchlistItem(BaseModel):
    symbol: str
    asset_class: str
    name: str = ""
    is_holding: bool = False
    quantity: float | None = None
    avg_cost: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    last_snapshot_at: str | None = None


class WatchlistCreateRequest(BaseModel):
    symbol: str
    asset_class: str = "stock"


class KlineBar(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketHealthQuote(BaseModel):
    symbol: str
    asset_class: str
    timestamp: str | None = None
    price: float | None = None
    quote_status: str = "unknown"
    quote_source: str | None = None
    quote_age_seconds: int | None = None
    stale_reason: str | None = None
    last_refresh_attempt: str | None = None
    last_refresh_error: str | None = None
    using_persistent_cache: bool = False
    nav_date: str | None = None


class MarketDataHealthResponse(BaseModel):
    quotes: list[MarketHealthQuote]
    market_open: bool = False
    refresh_policy: str = "cache_only"
    provider_status: str = "unknown"
    provider_name: str = "unknown"
    provider_configured: bool = False
    provider_requires_token: bool = False
    provider_supports_funds: bool | None = None
    provider_last_error: str | None = None
    provider_timeout_seconds: float | None = None
    next_action: str | None = None
    metadata_configured_count: int = 0
    source_health: str = "unknown"
    cache_age_seconds: int | None = None
    latest_quote_timestamp: str | None = None
    last_refresh_attempt: str | None = None
    last_refresh_error: str | None = None
    stale_symbols_count: int = 0
    stale_symbols_sample: list[str] = Field(default_factory=list)
    real_data_available: bool = False
    has_persistent_cache: bool = False
    latest_persistent_quote_timestamp: str | None = None
    persistent_cache_status: str = "unknown"


class QuoteFetchRunResponse(BaseModel):
    run_id: str
    trigger: str
    provider: str | None = None
    asset_type: str | None = None
    status: str
    started_at: str
    finished_at: str | None = None
    symbol_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    cache_hit_count: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


class ResearchBoardItem(BaseModel):
    symbol: str
    asset_class: str
    name: str = ""
    is_holding: bool = False
    quantity: float | None = None
    avg_cost: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    last_snapshot_at: str | None = None
    price: float | None = None
    volume: float | None = None
    research_count: int = 0
    last_research_at: str | None = None


class ResearchBoardResponse(BaseModel):
    items: list[ResearchBoardItem]
    health: MarketDataHealthResponse


class ResearchNoteCreate(BaseModel):
    symbol: str
    asset_class: str = "stock"
    entry_kind: str = "note"
    title: str
    content: str
    priority: str = "normal"
    event_date: str | None = None


class ResearchNoteUpdate(BaseModel):
    entry_kind: str = "note"
    title: str
    content: str
    priority: str = "normal"
    event_date: str | None = None


class ResearchNoteResponse(BaseModel):
    id: int
    symbol: str
    asset_class: str = "stock"
    entry_kind: str
    title: str
    content: str
    priority: str = "normal"
    event_date: str | None = None
    created_at: str
    updated_at: str


class ResearchNoteListResponse(BaseModel):
    items: list[ResearchNoteResponse]


# ---------- Portfolio ----------


class PositionResponse(BaseModel):
    symbol: str
    name: str | None = None
    display_name: str | None = None
    asset_class: str | None = None
    quantity: float
    available_qty: float
    frozen_qty: float
    avg_cost: float
    broker_displayed_unit_cost: float | None = None
    broker_displayed_cost_basis: float | None = None
    broker_cost_basis_difference: float | None = None
    broker_cost_basis_method: str | None = None
    broker_cost_basis_status: str | None = None
    latest_price: float | None = None
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    commission_paid: float
    today_change: float | None = None
    today_change_pct: float | None = None
    baseline_price: float | None = None
    baseline_timestamp: str | None = None
    baseline_source: str = "unavailable"
    quote_timestamp: str | None = None
    quote_status: str = "stale"
    quote_source: str | None = None
    quote_age_seconds: int | None = None
    stale_reason: str | None = None
    refresh_policy: str | None = None
    using_persistent_cache: bool = False
    nav_date: str | None = None


class AllocationItem(BaseModel):
    symbol: str
    name: str
    weight: float
    value: float
    asset_class: str


class AllocationGroup(BaseModel):
    """按资产类别聚合的配置。"""

    asset_class: str
    name: str
    value: float
    weight: float
    items: list[AllocationItem]


class PortfolioSnapshot(BaseModel):
    cash: float
    total_equity: float
    total_deposits: float = 0.0
    positions: list[PositionResponse]
    allocation: list[AllocationItem]
    allocation_grouped: list[AllocationGroup] = []


class LiveHoldingItemResponse(BaseModel):
    symbol: str
    name: str
    display_name: str | None = None
    asset_class: str
    quantity: float
    avg_cost: float
    market_value: float
    latest_price: float | None = None
    quote_timestamp: str | None = None
    since_buy_pnl: float
    since_buy_pnl_pct: float | None = None
    today_change: float | None = None
    today_change_pct: float | None = None
    baseline_price: float | None = None
    baseline_timestamp: str | None = None
    baseline_source: str = "unavailable"
    quote_status: str = "stale"
    quote_source: str | None = None
    quote_age_seconds: int | None = None
    stale_reason: str | None = None
    refresh_policy: str | None = None
    using_persistent_cache: bool = False
    nav_date: str | None = None


class LiveHoldingGroupResponse(BaseModel):
    asset_class: str
    label: str
    total_market_value: float
    total_today_change: float
    total_since_buy_pnl: float
    items: list[LiveHoldingItemResponse]


class LiveHoldingsResponse(BaseModel):
    groups: list[LiveHoldingGroupResponse]


class AccountOverview(BaseModel):
    total_equity: float
    available_cash: float
    total_deposits: float = 0.0
    positions_count: int
    unrealized_pnl: float
    realized_pnl: float
    cash_ratio: float
    valuation_timestamp: str | None = None
    quote_status: str = "live"
    quote_age_seconds: int | None = None
    quote_source: str | None = None
    stale_reason: str | None = None
    refresh_policy: str | None = None
    using_persistent_cache: bool = False


class AccountStateResponse(BaseModel):
    summary: AccountOverview
    snapshot: PortfolioSnapshot
    risks: list["RiskSummaryItem"]
    next_step: str


class RiskSummaryItem(BaseModel):
    kind: str
    level: str
    title: str
    detail: str


class ExplainabilityBridgeItem(BaseModel):
    key: str
    label: str
    value: float
    detail: str


class ExplainabilityDriver(BaseModel):
    kind: str
    title: str
    detail: str
    timestamp: str
    symbol: str | None = None
    amount: float | None = None
    quantity: float | None = None
    price: float | None = None
    commission: float | None = None
    gross_amount: float | None = None
    net_cash_impact: float | None = None
    fee_breakdown: dict[str, Any] | None = None
    fee_rule_id: str | None = None
    fee_rule_version: str | None = None
    asset_class: str | None = None


class ExplainabilityPositionDriver(BaseModel):
    symbol: str
    asset_class: str = "stock"
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    last_activity_at: str | None = None
    last_activity_note: str | None = None


class ExplainabilityTimelineEvent(BaseModel):
    category: str
    impact_source: str
    kind: str
    title: str
    detail: str
    timestamp: str
    symbol: str | None = None
    amount: float | None = None
    quantity: float | None = None
    price: float | None = None
    commission: float | None = None
    gross_amount: float | None = None
    net_cash_impact: float | None = None
    fee_breakdown: dict[str, Any] | None = None
    fee_rule_id: str | None = None
    fee_rule_version: str | None = None
    asset_class: str | None = None


class ExplainabilityTimelineBreakdownItem(BaseModel):
    key: str
    label: str
    value: float


class ExplainabilityTimelinePoint(BaseModel):
    date: str
    equity: float
    delta: float
    external_flow: float
    market_pnl: float
    events: list[ExplainabilityTimelineEvent]
    valuation_status: str = "complete"
    missing_price_symbols: list[str] = Field(default_factory=list)
    market_breakdown: list[ExplainabilityTimelineBreakdownItem] = Field(
        default_factory=list
    )
    external_flow_breakdown: list[ExplainabilityTimelineBreakdownItem] = Field(
        default_factory=list
    )


class ExplainabilityResponse(BaseModel):
    equity_bridge: list[ExplainabilityBridgeItem]
    recent_drivers: list[ExplainabilityDriver]
    positions: list[ExplainabilityPositionDriver]
    timeline: list[ExplainabilityTimelinePoint] = []


class RiskMetricItem(BaseModel):
    key: str
    label: str
    value: float
    display_value: str
    level: str = "low"
    detail: str


class RiskDrawdownPoint(BaseModel):
    timestamp: str
    equity: float
    peak_equity: float
    drawdown: float


class RiskDrawdownSummary(BaseModel):
    current_drawdown: float
    max_drawdown: float
    latest_equity: float
    peak_equity: float
    peak_timestamp: str | None = None
    trough_timestamp: str | None = None


class RiskExposureBucket(BaseModel):
    bucket: str
    label: str
    value: float
    weight: float
    positions_count: int
    symbols: list[str]


class RiskConcentrationItem(BaseModel):
    symbol: str
    asset_class: str
    market_value: float
    weight: float
    unrealized_pnl: float
    avg_cost: float
    quantity: float


class RiskWorkspaceResponse(BaseModel):
    metrics: list[RiskMetricItem]
    drawdown: RiskDrawdownSummary
    drawdown_series: list[RiskDrawdownPoint]
    exposure_buckets: list[RiskExposureBucket]
    concentration: list[RiskConcentrationItem]


class ActionCard(BaseModel):
    id: int | None = None
    source_signal_id: int | None = None
    symbol: str
    title: str
    detail: str
    direction: str
    urgency: str
    target_weight: float
    price: float | None = None
    strategy_id: str
    timestamp: str
    asset_class: str = "stock"
    status: str = "pending"
    risk_decision_id: str | None = None
    risk_gate_passed: bool | None = None
    risk_gate_status: str = "not_checked"
    risk_gate_severity: str | None = None
    risk_gate_reasons: list[str] = Field(default_factory=list)
    manual_confirmation_required: bool = True
    manual_confirmation_status: str = "awaiting_risk_gate"
    manual_confirmation_reason: str = "Risk gate has not produced a decision yet."


class PortfolioCockpitPosition(BaseModel):
    symbol: str
    name: str
    asset_class: str
    market_value: float
    actual_weight: float
    target_weight: float
    drift: float
    action_task: ActionCard | None = None


class PortfolioConstructionRecommendation(BaseModel):
    symbol: str
    name: str
    asset_class: str
    direction: str
    status: str
    actionable: bool
    actual_weight: float
    target_weight: float
    drift: float
    account_truth_gate_status: str
    risk_gate_status: str
    required_actions: list[str] = Field(default_factory=list)
    rationale: str
    source_action_task_id: int | None = None


class PortfolioCockpitResponse(BaseModel):
    summary: AccountOverview
    positions: list[PortfolioCockpitPosition]
    action_queue: list[ActionCard]
    risk_alerts: list[RiskSummaryItem]
    construction_recommendations: list[PortfolioConstructionRecommendation] = Field(
        default_factory=list
    )


class SignalJournalRiskDecision(BaseModel):
    id: int | None = None
    decision_id: str
    intent_id: str | None = None
    timestamp: str
    passed: bool
    symbol: str
    side: str
    reasons: list[str] = Field(default_factory=list)
    resulting_order_id: str | None = None
    severity: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class SignalJournalEvent(BaseModel):
    id: int | None = None
    event_type: str
    timestamp: str
    entity_type: str | None = None
    entity_id: str | None = None
    source: str
    source_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_json: str | None = None
    created_at: str | None = None


class SignalJournalReview(BaseModel):
    signal_id: int
    reviewed_at: str
    user_decision: str
    outcome: str
    review_notes: str
    reviewer: str | None = None


class SignalJournalEntry(BaseModel):
    signal: SignalResponse
    action_task: ActionCard | None = None
    risk_decision: SignalJournalRiskDecision | None = None
    review: SignalJournalReview | None = None
    latest_event: SignalJournalEvent | None = None


class CashFlowCreate(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    amount: float
    flow_type: str = "deposit"
    note: str = ""


class CashFlowResponse(BaseModel):
    id: int
    timestamp: str
    amount: float
    flow_type: str
    note: str
    created_at: str


class TradeCreate(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    symbol: str
    direction: str  # 'buy' / 'sell'
    quantity: float | None = None
    price: float | None = None
    amount: float | None = None
    commission: float | None = None
    asset_class: str = "stock"
    note: str = ""


class TradeResponse(BaseModel):
    id: int
    timestamp: str
    symbol: str
    direction: str
    quantity: float
    price: float
    commission: float
    asset_class: str
    note: str
    created_at: str


class TradePreviewResponse(BaseModel):
    symbol: str
    direction: str
    quantity: float
    price: float
    gross_amount: float
    commission: float
    total_fee: float
    net_cash_impact: float
    fee_breakdown: dict[str, Any] = Field(default_factory=dict)
    fee_rule_id: str
    fee_rule_version: str
    cost_basis_method: str
    note: str


class PendingFundOrderResponse(BaseModel):
    id: int
    submitted_at: str
    symbol: str
    display_name: str
    amount: float
    commission: float
    asset_class: str
    target_trade_date: str
    status: str
    note: str
    confirmed_nav: float | None = None
    confirmed_quantity: float | None = None
    confirmed_trade_date: str | None = None
    trade_id: int | None = None
    created_at: str
    updated_at: str


class EquityPoint(BaseModel):
    timestamp: str
    equity: float


class EquitySeriesPoint(BaseModel):
    timestamp: str
    total: float | None
    stocks: float | None
    funds: float | None
    others: float | None
    cash: float
    unrealized_pnl: float | None = None
    total_daily_change: float | None = None
    stocks_daily_change: float | None = None
    funds_daily_change: float | None = None
    others_daily_change: float | None = None
    quote_status: str = "live"
    missing_price_symbols: list[str] = []


class ActivityItem(BaseModel):
    kind: str
    title: str
    detail: str
    timestamp: str
    amount: float | None = None
    symbol: str | None = None


class LedgerEntryCreatedResponse(BaseModel):
    id: int
    entry_type: str
    status: str = "ok"


class LedgerEntryResponse(BaseModel):
    id: int
    entry_type: str
    timestamp: str
    amount: float | None = None
    symbol: str | None = None
    display_name: str | None = None
    direction: str | None = None
    quantity: float | None = None
    price: float | None = None
    commission: float = 0.0
    gross_amount: float | None = None
    net_cash_impact: float | None = None
    fee_breakdown: dict[str, Any] | None = None
    fee_rule_id: str | None = None
    fee_rule_version: str | None = None
    cost_basis_method: str | None = None
    asset_class: str = "stock"
    note: str = ""
    source: str = "manual"
    source_ref: str | None = None
    created_at: str | None = None


class LedgerTradeCreate(BaseModel):
    occurred_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    symbol: str
    asset_class: str = "stock"
    direction: str  # buy / sell
    quantity: float
    unit_price: float
    fee: float = 0.0
    note: str = ""
    source: str = "manual"
    source_ref: str | None = None


class LedgerCashFlowCreate(BaseModel):
    occurred_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    amount: float
    flow_type: str = "deposit"  # deposit / withdrawal
    note: str = ""
    source: str = "manual"
    source_ref: str | None = None


class LedgerDividendCreate(BaseModel):
    occurred_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    symbol: str
    asset_class: str = "stock"
    amount: float
    note: str = ""
    source: str = "manual"
    source_ref: str | None = None


class LedgerAdjustmentCreate(BaseModel):
    occurred_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    symbol: str | None = None
    asset_class: str = "stock"
    amount: float | None = None
    quantity: float | None = None
    price: float | None = None
    note: str = ""
    source: str = "manual"
    source_ref: str | None = None


# ---------- Signals ----------


class SignalResponse(BaseModel):
    id: int | None = None
    timestamp: str
    strategy_id: str
    symbol: str
    direction: str
    target_weight: float
    price: float | None = None
    asset_class: str = "stock"


class ActionTaskStatusUpdate(BaseModel):
    status: str


# ---------- Backtest ----------


class BacktestRequest(BaseModel):
    start_date: str = "2025-01-02"
    end_date: str = Field(default_factory=lambda: _DEFAULT_END_DATE)
    initial_cash: float = 100_000
    strategy: str = "dual_ma"
    short_period: int = 5
    long_period: int = 20
    params: dict[str, Any] | None = None
    assets: list[dict[str, str]] | None = None
    oos_mode: str = "single_split"
    oos_split_date: str | None = None
    oos_min_train_points: int = 4
    oos_test_window_points: int = 3
    oos_step_points: int = 1
    benchmark_return: float | None = None


class BacktestMetrics(BaseModel):
    initial_cash: float
    final_equity: float
    total_return: float
    annual_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float | str = 0.0
    volatility: float = 0.0
    win_rate: float
    duration_days: int
    total_commission: float = 0.0
    total_slippage: float = 0.0
    total_trades: int = 0
    gross_turnover: float = 0.0


class BacktestFill(BaseModel):
    fill_id: str | None = None
    order_id: str | None = None
    timestamp: str | None = None
    symbol: str
    side: str
    fill_price: float
    fill_quantity: float
    commission: float
    slippage: float
    fee_breakdown: dict[str, Any] | None = None
    fee_rule_id: str | None = None
    fee_rule_version: str | None = None


class BacktestResponse(BaseModel):
    id: int
    created_at: str
    config: BacktestRequest
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    research_evidence_bundle: dict[str, Any] = Field(default_factory=dict)
    cost_summary_json: dict[str, Any] = Field(default_factory=dict)
    evidence_json: dict[str, Any] = Field(default_factory=dict)
    fills: list[BacktestFill] = Field(default_factory=list)


class BacktestSweepRequest(BaseModel):
    start_date: str = "2025-01-02"
    end_date: str = Field(default_factory=lambda: _DEFAULT_END_DATE)
    initial_cash: float = 100_000
    strategy: str = "dual_ma"
    params: dict[str, Any] | None = None
    param_grid: dict[str, list[Any]]
    assets: list[dict[str, str]] | None = None
    rank_by: str = "total_return"
    max_combinations: int = Field(default=25, ge=1, le=100)


class BacktestSweepResult(BaseModel):
    rank: int
    result_id: int
    strategy: str
    params: dict[str, Any]
    metrics: BacktestMetrics
    score: float
    research_evidence_bundle: dict[str, Any] = Field(default_factory=dict)


class BacktestSweepResponse(BaseModel):
    strategy: str
    rank_by: str
    tested_count: int
    results: list[BacktestSweepResult]
    robustness_evidence: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class CompareRunRequest(BaseModel):
    strategy: str
    params: dict[str, Any] | None = None


class CompareRequest(BaseModel):
    start_date: str = "2011-06-01"
    end_date: str = Field(default_factory=lambda: _DEFAULT_END_DATE)
    initial_cash: float = 100_000
    strategies: list[str] | None = None  # None = 全部策略
    runs: list[CompareRunRequest] | None = None
    assets: list[dict[str, str]] | None = None


class StrategyCompareItem(BaseModel):
    strategy: str
    description: str
    result_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    dataset_snapshot_id: str | None = None
    dataset_snapshot: dict[str, Any] = Field(default_factory=dict)
    research_evidence_bundle: dict[str, Any] = Field(default_factory=dict)
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]


class CompareResponse(BaseModel):
    results: list[StrategyCompareItem]
    compared_count: int = 0
    dataset_snapshot_id: str | None = None
    dataset_snapshot: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class BacktestSummary(BaseModel):
    id: int
    created_at: str
    strategy: str
    total_return: float
    sharpe: float
    max_drawdown: float


# ---------- Account Strategy ----------


class AccountStrategyAssignment(BaseModel):
    strategy_id: str = "dual_ma"
    strategy_name: str = "dual_ma"
    status: str = "research_only"
    scope: str = "account"
    asset_class: str | None = None
    symbol: str | None = None
    effective_from: str | None = None
    auto_trade_enabled: bool = False
    attribution_status: str = "not_started"
    attributed_pnl: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    total_fees: float | None = None
    notes: str = ""
    updated_at: str | None = None
    limitations: list[str] = Field(default_factory=list)


class AccountStrategyAssignmentUpdate(BaseModel):
    strategy_id: str
    status: str = "research_only"
    scope: str = "account"
    asset_class: str | None = None
    symbol: str | None = None
    effective_from: str | None = None
    notes: str = ""


class AccountStrategyAttributionSummary(BaseModel):
    strategy_id: str
    attribution_status: str
    signal_count: int = 0
    action_count: int = 0
    risk_decision_count: int = 0
    order_count: int = 0
    fill_count: int = 0
    unattributed_fill_count: int = 0
    total_fees: float = 0.0
    attributed_pnl: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AccountStrategyContributionReport(BaseModel):
    strategy_id: str
    contribution_status: str
    strategy_health_status: str = "needs_review"
    strategy_health_reasons: list[str] = Field(default_factory=list)
    linked_fill_count: int = 0
    gross_realized_pnl: float = 0.0
    gross_unrealized_pnl: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    total_tax: float = 0.0
    net_contribution: float = 0.0
    unattributed_account_pnl: float | None = None
    manual_unattributed_pnl: float | None = None
    cash_flow_pnl: float | None = None
    missing_valuation_symbols: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class HoldingStrategyAttributionReport(BaseModel):
    strategy_id: str
    symbol: str
    assignment_scope: str
    assignment_applies_to_symbol: bool = False
    attribution_status: str = "not_started"
    signal_count: int = 0
    action_count: int = 0
    risk_decision_count: int = 0
    order_count: int = 0
    fill_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# ---------- Settings ----------


class SettingsResponse(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    live_auto_start: bool = True
    initial_cash: float = 0
    start_date: str = "2025-01-02"
    end_date: str = Field(default_factory=lambda: _DEFAULT_END_DATE)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    strategy: str = "dual_ma"
    short_period: int = 5
    long_period: int = 20
    data_source: str = "akshare"
    tushare_token: str = ""
    notification: dict = Field(default_factory=lambda: {"type": "console"})
    live_poll_interval: int = 60
    account_commission_rate: float = 0.0001
    account_min_commission: float = 5.0


class DataSourceSettingsUpdate(BaseModel):
    data_source: str = "akshare"
    tushare_token: str = ""
    live_poll_interval: int = 60


class DataSourceStatusResponse(BaseModel):
    data_source: str = "akshare"
    provider_name: str = "akshare"
    provider_configured: bool = True
    provider_supports_funds: bool | None = None
    provider_requires_token: bool = False
    requires_restart: bool = False
    next_action: str | None = None
    metadata_configured_count: int = 0
    has_persistent_cache: bool = False
    latest_persistent_quote_timestamp: str | None = None
    persistent_cache_status: str = "unknown"
    available_providers: list[str] = Field(
        default_factory=lambda: ["akshare", "tushare"]
    )


class AssetMetadataStatusResponse(BaseModel):
    configured_count: int = 0
    missing_symbols: list[str] = Field(default_factory=list)
    configured_assets: list[dict[str, Any]] = Field(default_factory=list)
    suggested_config: dict[str, Any] = Field(default_factory=dict)
    metadata_source: str = "config"
    has_missing_metadata: bool = False


class LiveStatusResponse(BaseModel):
    running: bool
    market_open: bool = False
