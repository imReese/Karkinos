"""Stable facade for typed runtime configuration contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from server.config_loading import load_config
from server.config_types import (
    AIProviderConfig,
    BrokerConnectorConfig,
    BrokerFeeScheduleConfig,
    BrokerStatementCollectorConfig,
    CiticHistoryXlsDirectoryConfig,
    ControlledBridgePolicyConfig,
    DataSourceProviderConfig,
    TrustedOperatorIdentityConfig,
)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


@dataclass
class BacktestConfig:
    """回测配置。"""

    initial_cash: Decimal = Decimal("0")
    start_date: str = "2025-01-02"
    end_date: str = field(default_factory=lambda: _DEFAULT_END_DATE)
    # Backtest-only and legacy migration inputs. Live watchlists and asset
    # identities belong in SQLite (`watchlist_assets`, `instrument_metadata`).
    assets: list[dict] | dict = field(default_factory=list)
    instruments: list[dict] | dict = field(default_factory=list)
    strategy: str = "dual_ma"
    short_period: int = 5
    long_period: int = 20
    commission_rate: Decimal = Decimal("0.0003")
    account_commission_rate: Decimal = Decimal("0.0001")
    account_min_commission: Decimal = Decimal("5")
    data_source: str = "akshare"
    data_source_provider_config: DataSourceProviderConfig = field(
        default_factory=DataSourceProviderConfig
    )
    tushare_token: str = ""
    notification: dict = field(default_factory=lambda: {"type": "console"})
    live_poll_interval: int = 60
    broker_connectors: list[BrokerConnectorConfig] = field(default_factory=list)
    broker_fee_schedule: BrokerFeeScheduleConfig = field(
        default_factory=BrokerFeeScheduleConfig
    )
    ai: AIProviderConfig = field(default_factory=AIProviderConfig)

    @classmethod
    def from_json(cls, path: str | Path) -> BacktestConfig:
        """Load a validated runtime configuration from local JSON."""

        return load_config(cls, path)


@dataclass
class ServerConfig(BacktestConfig):
    """服务器配置 — 继承 BacktestConfig，添加服务器相关字段。"""

    host: str = "0.0.0.0"
    port: int = 8000
    market_calendar_auto_sync: bool = True
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    broker_statement_collector: BrokerStatementCollectorConfig = field(
        default_factory=BrokerStatementCollectorConfig
    )
    citic_history_xls_directory: CiticHistoryXlsDirectoryConfig = field(
        default_factory=CiticHistoryXlsDirectoryConfig
    )
    controlled_bridge_policy: ControlledBridgePolicyConfig = field(
        default_factory=ControlledBridgePolicyConfig
    )
    trusted_operator_identities: list[TrustedOperatorIdentityConfig] = field(
        default_factory=list
    )


__all__ = [
    "AIProviderConfig",
    "BacktestConfig",
    "BrokerConnectorConfig",
    "BrokerFeeScheduleConfig",
    "BrokerStatementCollectorConfig",
    "CiticHistoryXlsDirectoryConfig",
    "ControlledBridgePolicyConfig",
    "DataSourceProviderConfig",
    "ServerConfig",
    "TrustedOperatorIdentityConfig",
]
