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


class KlineBar(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


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
    quantity: float
    price: float
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


class EquityPoint(BaseModel):
    timestamp: str
    equity: float


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
    win_rate: float
    duration_days: int


class BacktestResponse(BaseModel):
    id: int
    created_at: str
    config: BacktestRequest
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]


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


class LiveStatusResponse(BaseModel):
    running: bool
    market_open: bool = False
