"""Shared market-data HTTP contracts."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from server.models import QuoteFetchRunResponse


class ConfirmedFundNavRefreshRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=50)
    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
    )


class ConfirmedFundNavRefreshResponse(BaseModel):
    schema_version: str = "karkinos.confirmed_fund_nav_refresh.v1"
    request_id: str
    idempotent_replay: bool = False
    status: str
    next_manual_action: str
    requested_symbols: list[str]
    refreshed_symbols: list[str] = Field(default_factory=list)
    skipped_symbols: list[str] = Field(default_factory=list)
    failed_symbols: dict[str, str] = Field(default_factory=dict)
    run: QuoteFetchRunResponse
    valuation_snapshot_id: str | None = None
    provider_contact_performed: bool = True
    writes_market_data_only: bool = True
    does_not_mutate_oms: bool = True
    does_not_mutate_production_ledger: bool = True
    does_not_mutate_risk: bool = True
    does_not_mutate_kill_switch: bool = True
    does_not_change_capital_authority: bool = True
    authorizes_execution: bool = False


class InstrumentMetadataBackfillRequest(BaseModel):
    symbols: list[str] | None = None
    instrument_type: (
        Literal[
            "stock",
            "etf",
            "open_end_fund",
            "gold",
            "bond",
            "index",
        ]
        | None
    ) = None
    force: bool = False


class InstrumentMetadataBackfillItem(BaseModel):
    symbol: str
    asset_class: str
    status: str
    display_name: str | None = None
    provider: str | None = None
    error: str | None = None


class InstrumentMetadataBackfillResponse(BaseModel):
    provider: str
    requested_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    items: list[InstrumentMetadataBackfillItem] = Field(default_factory=list)


class MarketBarsBackfillRequest(BaseModel):
    symbols: list[str] | None = None
    asset_class: str | None = None
    instrument_type: (
        Literal[
            "stock",
            "etf",
            "open_end_fund",
            "gold",
            "bond",
            "index",
        ]
        | None
    ) = None
    start: str | None = None
    end: str | None = None
    interval: str = "1d"
    force: bool = False


class MarketBarsBackfillItem(BaseModel):
    symbol: str
    asset_class: str
    status: str
    row_count: int = 0
    stored_start: str | None = None
    stored_end: str | None = None
    error: str | None = None


class MarketBarsBackfillResponse(BaseModel):
    provider: str
    interval: str
    start: str
    end: str
    requested_count: int
    updated_count: int
    cached_count: int
    failed_count: int
    items: list[MarketBarsBackfillItem] = Field(default_factory=list)


class QuoteRefreshRequest(BaseModel):
    symbols: list[str] | None = None
    force: bool = False


class QuoteRefreshSymbolResult(BaseModel):
    symbol: str
    asset_class: str
    status: str
    quote_timestamp: str | None = None
    quote_source: str | None = None
    quote_age_seconds: int | None = None
    error: str | None = None
    reason: str | None = None
    last_refresh_attempt: str | None = None
    last_refresh_error: str | None = None
    using_persistent_cache: bool = False


class QuoteRefreshResponse(BaseModel):
    requested_symbols: list[str]
    refreshed: list[QuoteRefreshSymbolResult] = Field(default_factory=list)
    failed: list[QuoteRefreshSymbolResult] = Field(default_factory=list)
    skipped: list[QuoteRefreshSymbolResult] = Field(default_factory=list)
    refresh_policy: str
    market_open: bool
    started_at: str
    completed_at: str
    duration_ms: int
    quote_status: str
    last_refresh_attempt: str | None = None
    last_refresh_error: str | None = None
    message: str
    real_data_available: bool = False
    has_persistent_cache: bool = False


__all__ = (
    "ConfirmedFundNavRefreshRequest",
    "ConfirmedFundNavRefreshResponse",
    "InstrumentMetadataBackfillItem",
    "InstrumentMetadataBackfillRequest",
    "InstrumentMetadataBackfillResponse",
    "MarketBarsBackfillItem",
    "MarketBarsBackfillRequest",
    "MarketBarsBackfillResponse",
    "QuoteRefreshRequest",
    "QuoteRefreshResponse",
    "QuoteRefreshSymbolResult",
)
