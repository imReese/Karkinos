"""Signal, backtest, and account-strategy HTTP schemas."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from server.contracts.http.ledger_models import EquityPoint

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


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
    schema_version: str = "karkinos.account_strategy_contribution.v2"
    strategy_id: str
    contribution_status: str
    evidence_binding_status: str = "blocked"
    next_manual_action: str = "review_strategy_contribution_evidence"
    blockers: list[str] = Field(default_factory=list)
    strategy_health_status: str = "needs_review"
    strategy_health_reasons: list[str] = Field(default_factory=list)
    linked_fill_count: int = 0
    ledger_posted_fill_count: int = 0
    unposted_linked_fill_count: int = 0
    unattributed_fill_count: int = 0
    gross_realized_pnl: float | None = None
    gross_unrealized_pnl: float | None = None
    total_commission: float | None = None
    total_slippage: float | None = None
    total_tax: float | None = None
    net_contribution: float | None = None
    unattributed_account_pnl: float | None = None
    manual_unattributed_pnl: float | None = None
    cash_flow_pnl: float | None = None
    missing_valuation_symbols: list[str] = Field(default_factory=list)
    valuation_snapshot_id: str | None = None
    valuation_as_of: str | None = None
    valuation_status: str = "unavailable"
    valuation_scope_status: str = "blocked"
    ledger_cutoff_id: int = 0
    ledger_fingerprint: str | None = None
    quote_set_fingerprint: str | None = None
    contribution_fingerprint: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    persisted_facts_only: bool = True
    provider_contacted: bool = False
    database_writes_performed: bool = False
    authorizes_execution: bool = False
    limitations: list[str] = Field(default_factory=list)


class AttributionReviewPrerequisite(BaseModel):
    key: str
    passed: bool
    evidence_count: int = 0


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
    review_prerequisites: list[AttributionReviewPrerequisite] = Field(
        default_factory=list
    )
    limitations: list[str] = Field(default_factory=list)
