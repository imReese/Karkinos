"""Portfolio, risk, and signal-journal HTTP schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from server.contracts.http.strategy_models import SignalResponse


class PositionResponse(BaseModel):
    symbol: str
    name: str | None = None
    display_name: str | None = None
    asset_class: str | None = None
    instrument_type: str | None = None
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
    market_value: float | None
    unrealized_pnl: float | None
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
    valuation_available: bool = True
    valuation_blockers: list[str] = Field(default_factory=list)


class PositionEvidenceReviewResponse(BaseModel):
    """Non-current position facts that require explicit evidence review."""

    status: str = "review_required"
    reason_codes: list[str] = Field(default_factory=list)
    position: PositionResponse


class ClosedPositionResponse(PositionResponse):
    """Historical position with its canonical ledger close timestamp."""

    closed_at: str | None = None


class CurrentHoldingMarketEvidenceReviewItem(BaseModel):
    """One current holding whose persisted quote evidence is not authoritative."""

    symbol: str
    name: str
    asset_class: str
    quantity: float
    quote_status: str
    quote_source: str | None = None
    quote_timestamp: str | None = None
    stale_reason: str | None = None
    nav_date: str | None = None
    review_reason: str
    next_manual_action: str
    explicit_refresh_eligible: bool = True
    blocks_authoritative_decisions: bool = True


class CurrentHoldingMarketEvidenceLane(BaseModel):
    """Current non-zero holding evidence summarized by asset-class lane."""

    asset_class: str
    status: str
    current_holding_count: int
    confirmed_holding_count: int
    review_required_count: int
    blocker_statuses: list[str] = Field(default_factory=list)


class ValuationLaneResponse(BaseModel):
    """Persisted valuation quote completeness under one snapshot identity."""

    asset_class: str
    status: str
    quote_count: int
    complete_quote_count: int
    review_required_quote_count: int
    blocker_statuses: list[str] = Field(default_factory=list)


class CurrentHoldingMarketEvidenceReviewResponse(BaseModel):
    """Evidence-bound review queue for canonical non-zero holdings."""

    schema_version: str = "karkinos.current_holding_market_evidence_review.v1"
    status: str
    next_manual_action: str
    current_holding_count: int
    confirmed_holding_count: int
    review_required_count: int
    fund_nav_review_count: int
    estimated_review_count: int
    stale_or_cached_review_count: int
    missing_or_error_review_count: int
    unknown_status_review_count: int
    refreshable_symbols: list[str] = Field(default_factory=list)
    quote_refresh_symbols: list[str] = Field(default_factory=list)
    confirmed_fund_nav_refresh_symbols: list[str] = Field(default_factory=list)
    evidence_lanes: list[CurrentHoldingMarketEvidenceLane] = Field(default_factory=list)
    items: list[CurrentHoldingMarketEvidenceReviewItem] = Field(default_factory=list)
    source_blockers: list[str] = Field(default_factory=list)
    review_fingerprint: str
    valuation_snapshot_id: str | None = None
    valuation_as_of: str | None = None
    valuation_trade_date: str | None = None
    valuation_policy: str | None = None
    valuation_status: str = "missing"
    ledger_cutoff_id: int = 0
    ledger_fingerprint: str | None = None
    quote_set_fingerprint: str | None = None
    reads_persisted_facts_only: bool = True
    provider_contact_performed: bool = False
    runtime_connector_query_performed: bool = False
    database_writes_performed: bool = False
    does_not_mutate_oms: bool = True
    does_not_mutate_production_ledger: bool = True
    does_not_mutate_risk: bool = True
    does_not_mutate_kill_switch: bool = True
    does_not_change_capital_authority: bool = True
    authorizes_execution: bool = False


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
    total_equity: float | None
    total_deposits: float = 0.0
    positions: list[PositionResponse]
    allocation: list[AllocationItem]
    allocation_grouped: list[AllocationGroup] = Field(default_factory=list)
    closed_positions: list[ClosedPositionResponse] = Field(default_factory=list)
    position_review_items: list[PositionEvidenceReviewResponse] = Field(
        default_factory=list
    )
    realized_pnl_total: float | None = None
    valuation_snapshot_id: str | None = None
    valuation_as_of: str | None = None
    valuation_trade_date: str | None = None
    valuation_policy: str | None = None
    valuation_status: str = "missing"
    valuation_lanes: list[ValuationLaneResponse] = Field(default_factory=list)
    ledger_cutoff_id: int = 0
    ledger_fingerprint: str | None = None
    quote_set_fingerprint: str | None = None
    missing_price_symbols: list[str] = Field(default_factory=list)
    valuation_blockers: list[str] = Field(default_factory=list)


class LiveHoldingItemResponse(BaseModel):
    symbol: str
    name: str
    display_name: str | None = None
    asset_class: str
    instrument_type: str | None = None
    quantity: float
    avg_cost: float
    market_value: float | None
    latest_price: float | None = None
    quote_timestamp: str | None = None
    since_buy_pnl: float | None
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
    valuation_available: bool = True
    valuation_blockers: list[str] = Field(default_factory=list)


class LiveHoldingGroupResponse(BaseModel):
    asset_class: str
    label: str
    total_market_value: float | None
    total_today_change: float | None
    total_since_buy_pnl: float | None
    items: list[LiveHoldingItemResponse]


class LiveHoldingsResponse(BaseModel):
    groups: list[LiveHoldingGroupResponse]
    valuation_snapshot_id: str | None = None
    valuation_as_of: str | None = None
    valuation_trade_date: str | None = None
    valuation_policy: str | None = None
    valuation_status: str = "missing"
    ledger_cutoff_id: int = 0
    ledger_fingerprint: str | None = None
    quote_set_fingerprint: str | None = None
    missing_price_symbols: list[str] = Field(default_factory=list)
    valuation_blockers: list[str] = Field(default_factory=list)


class TodayPnlBreakdown(BaseModel):
    stocks: float = 0.0
    funds: float = 0.0
    others: float = 0.0
    total: float = 0.0


class TodayPnlContributor(BaseModel):
    symbol: str
    name: str | None = None
    display_name: str | None = None
    asset_class: str
    today_change: float
    today_change_pct: float | None = None
    quote_status: str = "live"


class DailyOperationsSummary(BaseModel):
    candidate_pool_count: int = 0
    evidence_passed_count: int = 0
    risk_checked_count: int = 0
    risk_passed_count: int = 0
    risk_blocked_count: int = 0
    paper_shadow_review_count: int = 0
    manual_ready_count: int = 0
    pending_manual_order_count: int = 0
    execution_record_count: int = 0
    fill_record_count: int = 0
    ledger_review_count: int = 0
    execution_exception_count: int = 0
    default_execution_mode: str = "manual_confirmation"
    broker_bridge_status: str = "disabled"
    conclusion_status: str = "no_manual_action"
    primary_target: str = "decision"
    limitations: list[str] = Field(default_factory=list)


class AccountOverview(BaseModel):
    total_equity: float | None
    available_cash: float
    total_deposits: float = 0.0
    positions_count: int
    unrealized_pnl: float | None
    realized_pnl: float
    cash_ratio: float | None
    today_pnl: float | None = None
    today_pnl_breakdown: TodayPnlBreakdown | None = None
    today_contributors: list[TodayPnlContributor] = Field(default_factory=list)
    current_drawdown: float | None = None
    current_drawdown_amount: float | None = None
    drawdown_peak_equity: float | None = None
    drawdown_latest_equity: float | None = None
    drawdown_peak_timestamp: str | None = None
    valuation_timestamp: str | None = None
    quote_status: str = "live"
    quote_age_seconds: int | None = None
    quote_source: str | None = None
    stale_reason: str | None = None
    refresh_policy: str | None = None
    using_persistent_cache: bool = False
    daily_operations: DailyOperationsSummary | None = None
    valuation_snapshot_id: str | None = None
    valuation_as_of: str | None = None
    valuation_trade_date: str | None = None
    valuation_policy: str | None = None
    valuation_status: str = "missing"
    ledger_cutoff_id: int = 0
    ledger_fingerprint: str | None = None
    quote_set_fingerprint: str | None = None
    missing_price_symbols: list[str] = Field(default_factory=list)
    valuation_blockers: list[str] = Field(default_factory=list)


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
    value: float | None
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
    asset_class: str
    quantity: float
    avg_cost: float
    market_value: float | None
    unrealized_pnl: float | None
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
    equity: float | None
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
    valuation_snapshot_id: str | None = None
    valuation_as_of: str | None = None
    valuation_trade_date: str | None = None
    valuation_policy: str | None = None
    valuation_status: str = "missing"
    ledger_cutoff_id: int = 0
    ledger_fingerprint: str | None = None
    quote_set_fingerprint: str | None = None


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
    status: str = "complete"
    blockers: list[str] = Field(default_factory=list)
    metrics: list[RiskMetricItem]
    drawdown: RiskDrawdownSummary | None
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
    market_value: float | None
    actual_weight: float | None
    target_weight: float | None
    drift: float | None
    action_task: ActionCard | None = None


class PortfolioConstructionRecommendation(BaseModel):
    symbol: str
    name: str
    asset_class: str
    direction: str
    status: str
    actionable: bool
    actual_weight: float | None
    target_weight: float | None
    drift: float | None
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
