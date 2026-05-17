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


class MarketDataHealthResponse(BaseModel):
    quotes: list[MarketHealthQuote]
    market_open: bool = False
    refresh_policy: str = "cache_only"


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
    quantity: float
    available_qty: float
    frozen_qty: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    commission_paid: float
    quote_timestamp: str | None = None
    quote_status: str = "stale"


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


class ExplainabilityTimelinePoint(BaseModel):
    date: str
    equity: float
    delta: float
    external_flow: float
    market_pnl: float
    events: list[ExplainabilityTimelineEvent]


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
    commission: float = 0.0
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
    total: float
    stocks: float
    funds: float
    others: float
    cash: float
    unrealized_pnl: float | None = None
    quote_status: str = "live"


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
    direction: str | None = None
    quantity: float | None = None
    price: float | None = None
    commission: float = 0.0
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
    assets: list[dict[str, str]] | None = None


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


class BacktestResponse(BaseModel):
    id: int
    created_at: str
    config: BacktestRequest
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    cost_summary_json: dict[str, Any] = Field(default_factory=dict)
    fills: list[BacktestFill] = Field(default_factory=list)


class CompareRequest(BaseModel):
    start_date: str = "2011-06-01"
    end_date: str = Field(default_factory=lambda: _DEFAULT_END_DATE)
    initial_cash: float = 100_000
    strategies: list[str] | None = None  # None = 全部策略
    assets: list[dict[str, str]] | None = None


class StrategyCompareItem(BaseModel):
    strategy: str
    description: str
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]


class CompareResponse(BaseModel):
    results: list[StrategyCompareItem]


class BacktestSummary(BaseModel):
    id: int
    created_at: str
    strategy: str
    total_return: float
    sharpe: float
    max_drawdown: float


# ---------- Settings ----------


class SettingsResponse(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    live_auto_start: bool = True
    initial_cash: float = 100_000
    start_date: str = "2025-01-02"
    end_date: str = Field(default_factory=lambda: _DEFAULT_END_DATE)
    assets: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"symbol": "600519", "asset_class": "stock"},
            {"symbol": "510300", "asset_class": "etf"},
            {"symbol": "Au99.99", "asset_class": "gold"},
        ]
    )
    strategy: str = "dual_ma"
    short_period: int = 5
    long_period: int = 20
    data_source: str = "akshare"
    tushare_token: str = ""
    notification: dict = Field(default_factory=lambda: {"type": "console"})
    live_poll_interval: int = 60


class DataSourceSettingsUpdate(BaseModel):
    data_source: str = "akshare"
    tushare_token: str = ""
    live_poll_interval: int = 60


class LiveStatusResponse(BaseModel):
    running: bool
    market_open: bool = False
