"""Market and research HTTP schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MarketQuote(BaseModel):
    symbol: str
    price: float
    volume: float | None = None
    timestamp: str | None = None
    asset_class: str | None = None


class WatchlistItem(BaseModel):
    symbol: str
    asset_class: str
    instrument_type: str | None = None
    identity_provenance: str | None = None
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
    instrument_type: str | None = None
    identity_provenance: str | None = None
    name: str | None = None
    display_name: str | None = None
    timestamp: str | None = None
    price: float | None = None
    daily_change: float | None = None
    daily_change_pct: float | None = None
    change: float | None = None
    change_pct: float | None = None
    pct_chg: float | None = None
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


class MarketCalendarDayResponse(BaseModel):
    schema_version: str
    date: str
    day_type: str
    reason_code: str
    reason: str
    is_trading_day: bool


class MarketCalendarSnapshotResponse(BaseModel):
    schema_version: str = "karkinos.market_calendar.v1"
    exchange: str
    year: int
    provider: str
    status: str
    trading_day_count: int = 0
    closed_day_count: int = 0
    source_fingerprint: str | None = None
    official_verification_status: str = "unverified"
    official_source_url: str | None = None
    verification_source_fingerprint: str | None = None
    official_source_fingerprint: str | None = None
    official_verified_at: str | None = None
    official_verified_by: str | None = None
    limitations: list[str] = Field(default_factory=list)
    days: list[MarketCalendarDayResponse] = Field(default_factory=list)
    updated_at: str | None = None


class MarketCalendarSyncRequest(BaseModel):
    exchange: str = "SSE"
    year: int = 2026
    provider: str | None = None


class MarketCalendarVerificationRequest(BaseModel):
    exchange: str = "SSE"
    year: int = 2026
    expected_source_fingerprint: str
    verification_status: Literal["unverified", "needs_review", "verified"]
    official_source_url: str | None = None
    official_source_fingerprint: str | None = None
    verified_by: str | None = None
    review_notes: str | None = None
    day_labels: dict[str, str] = Field(default_factory=dict)


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
