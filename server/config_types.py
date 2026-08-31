"""Typed, authority-neutral runtime configuration contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


@dataclass(frozen=True)
class BrokerConnectorConfig:
    """Read-only broker connector runtime config stored only in local config."""

    connector_id: str
    connector_type: str = "local_export_readonly"
    enabled: bool = False
    client_path: str = ""
    account_alias: str = ""


@dataclass(frozen=True)
class ControlledBridgePolicyConfig:
    """Local future bridge whitelist config that never enables submission."""

    policy_id: str = "default-controlled-bridge-disabled"
    enabled: bool = False
    allowed_connector_ids: tuple[str, ...] = ()
    allowed_account_aliases: tuple[str, ...] = ()
    allowed_strategy_ids: tuple[str, ...] = ()
    allowed_symbols: tuple[str, ...] = ()
    per_order_confirmation_required: bool = True
    automation_allowed: bool = False


@dataclass(frozen=True)
class TrustedOperatorIdentityConfig:
    """Public verification key only; never an execution authorization."""

    operator_id: str
    key_id: str
    algorithm: str = "ed25519"
    public_key_base64: str = ""
    enabled: bool = False


@dataclass(frozen=True)
class BrokerFeeScheduleConfig:
    """Local broker fee rules stored in ignored runtime config."""

    schedule_id: str = "local_broker_fee_schedule_v1"
    account_profile_id: str = ""
    broker_name: str = ""
    stock_a_commission_rate: Decimal = Decimal("0.0001")
    stock_a_min_commission: Decimal = Decimal("5")
    fund_etf_commission_rate: Decimal = Decimal("0.0001")
    fund_etf_min_commission: Decimal = Decimal("5")
    stamp_tax_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")
    fund_etf_transfer_fee_rate: Decimal = Decimal("0.00001")
    exchange_transfer_fee_rates: dict[str, Decimal] = field(default_factory=dict)
    other_fee_rate: Decimal = Decimal("0")
    money_precision: Decimal | None = None
    money_rounding_mode: str = "none"
    limitations: tuple[str, ...] = (
        "transfer_fee_exchange_not_split",
        "broker_regulatory_fees_assumed_absorbed",
    )


@dataclass(frozen=True)
class AIProviderConfig:
    """Provider-neutral external-model settings without runtime authority."""

    enabled: bool = False
    provider: str = ""
    model: str = ""
    base_url: str = ""
    adapter_kind: str = "openai_compatible_https"
    timeout_seconds: float = 20.0
    api_key_env: str = "KARKINOS_AI_API_KEY"

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("ai.enabled must be boolean")
        for field_name in (
            "provider",
            "model",
            "base_url",
            "adapter_kind",
            "api_key_env",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise ValueError(f"ai.{field_name} must be a string")
        if self.adapter_kind != "openai_compatible_https":
            raise ValueError(
                "ai.adapter_kind must be the reviewed openai_compatible_https adapter"
            )
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, int | float
        ):
            raise ValueError("ai.timeout_seconds must be numeric")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("ai.timeout_seconds must be within (0, 60]")
        if not _ENV_NAME_PATTERN.fullmatch(self.api_key_env):
            raise ValueError("ai.api_key_env name is invalid")
        if self.base_url:
            parsed = urlparse(self.base_url)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "ai.base_url must be a credential-free HTTPS origin/path"
                )
        if self.enabled and (
            not self.provider.strip()
            or not self.model.strip()
            or not self.base_url.strip()
        ):
            raise ValueError(
                "enabled AI config requires ai.provider, ai.model, and ai.base_url"
            )


@dataclass(frozen=True)
class BrokerStatementCollectorConfig:
    """Explicitly enabled local-file ingestion with evidence-only authority."""

    enabled: bool = False
    daily_snapshot_roll_forward_enabled: bool = False
    path: str = "broker_statement.csv"
    poll_interval_seconds: float = 5.0
    stability_delay_seconds: float = 2.0
    max_file_bytes: int = 10 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError(
                "account_truth.broker_statement_collector.enabled must be boolean"
            )
        if not isinstance(self.daily_snapshot_roll_forward_enabled, bool):
            raise ValueError(
                "account_truth.broker_statement_collector."
                "daily_snapshot_roll_forward_enabled must be boolean"
            )
        if self.daily_snapshot_roll_forward_enabled and not self.enabled:
            raise ValueError(
                "account_truth.broker_statement_collector."
                "daily_snapshot_roll_forward_enabled requires enabled=true"
            )
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError(
                "account_truth.broker_statement_collector.path must be a "
                "non-empty string"
            )
        for field_name, value, minimum, maximum in (
            (
                "poll_interval_seconds",
                self.poll_interval_seconds,
                0.5,
                3600.0,
            ),
            (
                "stability_delay_seconds",
                self.stability_delay_seconds,
                0.0,
                60.0,
            ),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or value < minimum
                or value > maximum
            ):
                raise ValueError(
                    "account_truth.broker_statement_collector."
                    f"{field_name} must be numeric within [{minimum}, {maximum}]"
                )
        if (
            isinstance(self.max_file_bytes, bool)
            or not isinstance(self.max_file_bytes, int)
            or self.max_file_bytes < 1024
            or self.max_file_bytes > 100 * 1024 * 1024
        ):
            raise ValueError(
                "account_truth.broker_statement_collector.max_file_bytes must be "
                "an integer within [1024, 104857600]"
            )


@dataclass(frozen=True)
class CiticHistoryXlsDirectoryConfig:
    """Explicit local directory used only by human-triggered read-only scans."""

    enabled: bool = False
    path: str = ""
    max_files: int = 120
    max_file_bytes: int = 10 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        prefix = "account_truth.citic_history_xls_directory"
        if not isinstance(self.enabled, bool):
            raise ValueError(f"{prefix}.enabled must be boolean")
        if not isinstance(self.path, str):
            raise ValueError(f"{prefix}.path must be a string")
        normalized_path = self.path.strip()
        if self.enabled and not normalized_path:
            raise ValueError(f"enabled {prefix} requires a non-empty path")
        if normalized_path and not Path(normalized_path).is_absolute():
            raise ValueError(f"{prefix}.path must be absolute when provided")
        for field_name, value, minimum, maximum in (
            ("max_files", self.max_files, 1, 600),
            ("max_file_bytes", self.max_file_bytes, 1024, 10 * 1024 * 1024),
            ("max_total_bytes", self.max_total_bytes, 1024, 100 * 1024 * 1024),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < minimum
                or value > maximum
            ):
                raise ValueError(
                    f"{prefix}.{field_name} must be an integer within "
                    f"[{minimum}, {maximum}]"
                )
        if self.max_total_bytes < self.max_file_bytes:
            raise ValueError(
                f"{prefix}.max_total_bytes must be greater than or equal to "
                "max_file_bytes"
            )


@dataclass(frozen=True)
class DataSourceProviderConfig:
    """Credential-free provider edge settings for market-data startup."""

    tushare_token_env: str = "KARKINOS_TUSHARE_TOKEN"

    def __post_init__(self) -> None:
        if not _ENV_NAME_PATTERN.fullmatch(self.tushare_token_env):
            raise ValueError(
                "data_source.provider_config.tushare_token_env must be an "
                "uppercase environment variable name"
            )
