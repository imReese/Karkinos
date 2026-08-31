"""Settings and runtime-status HTTP schemas."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.config_contract import (
    MIN_LIVE_POLL_INTERVAL_SECONDS,
    SUPPORTED_DATA_SOURCES,
    SUPPORTED_NOTIFICATION_TYPES,
)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


class NotificationSettingsStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "console"
    configured: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in SUPPORTED_NOTIFICATION_TYPES:
            raise ValueError("unsupported notification type")
        return value


class SettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8000
    initial_cash: float = 0
    start_date: str = "2025-01-02"
    end_date: str = Field(default_factory=lambda: _DEFAULT_END_DATE)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    strategy: str = "dual_ma"
    short_period: int = 5
    long_period: int = 20
    data_source: str = "akshare"
    tushare_token_configured: bool = False
    notification: NotificationSettingsStatus = Field(
        default_factory=NotificationSettingsStatus
    )
    live_poll_interval: int = Field(
        default=60,
        ge=MIN_LIVE_POLL_INTERVAL_SECONDS,
    )
    account_commission_rate: float = 0.0001
    account_min_commission: float = 5.0

    @field_validator("data_source")
    @classmethod
    def validate_data_source(cls, value: str) -> str:
        if value not in SUPPORTED_DATA_SOURCES:
            raise ValueError("unsupported data source")
        return value


class DataSourceSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_source: str = "akshare"
    live_poll_interval: int = Field(
        default=60,
        ge=MIN_LIVE_POLL_INTERVAL_SECONDS,
    )

    @field_validator("data_source")
    @classmethod
    def validate_data_source(cls, value: str) -> str:
        if value not in SUPPORTED_DATA_SOURCES:
            raise ValueError("unsupported data source")
        return value


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
    initialized: bool
    activation_guarded: bool
    scheduler_activation_guarded: bool
    completed_iterations: int = Field(ge=0)
    market_open: bool = False
