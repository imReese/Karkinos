"""Manual-trade, activity, and ledger HTTP schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
    valuation_snapshot_id: str | None = None
    valuation_as_of: str | None = None
    valuation_trade_date: str | None = None
    valuation_policy: str | None = None
    valuation_status: str = "missing"
    ledger_cutoff_id: int = 0
    ledger_fingerprint: str | None = None
    quote_set_fingerprint: str | None = None


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
    estimated_commission: float | None = None
    estimated_net_cash_impact: float | None = None
    estimated_fee_breakdown: dict[str, Any] | None = None
    estimated_fee_rule_id: str | None = None
    estimated_fee_rule_version: str | None = None
    settlement_status: str | None = None
    settled_at: str | None = None
    settlement_source: str | None = None
    settlement_source_ref: str | None = None
    settlement_note: str = ""
    cost_basis_method: str | None = None
    correction_payload: dict[str, Any] | None = None
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


class LedgerTradeSettlementCreate(BaseModel):
    settled_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    commission: float = Field(ge=0)
    stamp_tax: float = Field(default=0.0, ge=0)
    transfer_fee: float = Field(default=0.0, ge=0)
    other_fees: float = Field(default=0.0, ge=0)
    net_cash_impact: float
    source: str = Field(default="broker_statement", min_length=1)
    source_ref: str = Field(min_length=1)
    note: str = ""


class LedgerTradeSettlementResponse(BaseModel):
    id: int
    entry_type: str
    settlement_status: str
    estimated_net_cash_impact: float | None
    settled_net_cash_impact: float
    cash_adjustment: float | None
    fee_breakdown: dict[str, Any]
    audit_event_type: str = "portfolio.trade_settlement.confirmed"
    does_not_submit_broker_order: bool = True


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
