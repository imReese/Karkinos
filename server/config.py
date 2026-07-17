"""类型化配置加载。"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from server.config_contract import (
    MIN_LIVE_POLL_INTERVAL_SECONDS,
    SUPPORTED_DATA_SOURCES,
    SUPPORTED_NOTIFICATION_TYPES,
)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
_BROKER_CONNECTOR_ALLOWED_FIELDS = frozenset(
    {
        "connector_id",
        "connector_type",
        "enabled",
        "client_path",
        "account_alias",
    }
)
_CONTROLLED_BRIDGE_POLICY_ALLOWED_FIELDS = frozenset(
    {
        "policy_id",
        "enabled",
        "allowed_connector_ids",
        "allowed_account_aliases",
        "allowed_strategy_ids",
        "allowed_symbols",
        "per_order_confirmation_required",
        "automation_allowed",
    }
)
_TRUSTED_OPERATOR_IDENTITY_ALLOWED_FIELDS = frozenset(
    {
        "operator_id",
        "key_id",
        "algorithm",
        "public_key_base64",
        "enabled",
    }
)
_TRUSTED_OPERATOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BROKER_CONNECTOR_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "credential",
)
_BROKER_FEE_SCHEDULE_ALLOWED_FIELDS = frozenset(
    {
        "schedule_id",
        "profile_id",
        "account_profile_id",
        "broker_name",
        "display_name",
        "schema_version",
        "source",
        "source_type",
        "currency",
        "effective_from",
        "captured_at",
        "precedence",
        "rounding",
        "rule_application",
        "rules",
        "broker_absorbed_components",
        "account_identifier_saved",
        "screenshots_saved",
        "private_exports_saved",
        "commission",
        "taxes_and_fees",
        "stock_a_commission_rate",
        "stock_a_min_commission",
        "fund_etf_commission_rate",
        "fund_etf_min_commission",
        "stamp_tax_rate",
        "transfer_fee_rate",
        "exchange_transfer_fee_rates",
        "other_fee_rate",
        "limitations",
    }
)
_EXCHANGE_ALIASES = {
    "sh": "shanghai",
    "sse": "shanghai",
    "shanghai": "shanghai",
    "上海": "shanghai",
    "沪": "shanghai",
    "sz": "shenzhen",
    "szse": "shenzhen",
    "shenzhen": "shenzhen",
    "深圳": "shenzhen",
    "深": "shenzhen",
}

_SERVER_CONFIG_GROUP_FIELDS = frozenset(
    {"host", "port", "live_auto_start", "cors_allowed_origins", "notification"}
)
_DATA_SOURCE_CONFIG_GROUP_FIELDS = frozenset(
    {"provider", "live_poll_interval", "provider_config"}
)
_AI_CONFIG_GROUP_FIELDS = frozenset(
    {
        "enabled",
        "provider",
        "model",
        "base_url",
        "adapter_kind",
        "timeout_seconds",
        "api_key_env",
    }
)
_ACCOUNT_TRUTH_CONFIG_GROUP_FIELDS = frozenset({"broker_statement_collector"})
_BROKER_STATEMENT_COLLECTOR_ALLOWED_FIELDS = frozenset(
    {
        "enabled",
        "path",
        "poll_interval_seconds",
        "stability_delay_seconds",
        "max_file_bytes",
    }
)
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def _normalize_grouped_config_payload(raw: object) -> dict:
    """Map grouped local JSON sections onto the stable runtime config fields."""

    if not isinstance(raw, dict):
        raise ValueError("config.json root must be an object")
    data = dict(raw)

    server = data.pop("server", None)
    if server is not None:
        if not isinstance(server, dict):
            raise ValueError("server config group must be an object")
        unknown = sorted(set(server) - _SERVER_CONFIG_GROUP_FIELDS)
        if unknown:
            raise ValueError(
                "server config group contains unsupported fields: " + ", ".join(unknown)
            )
        for field, value in server.items():
            if field in data:
                raise ValueError(
                    f"config field {field} cannot appear both grouped and flat"
                )
            data[field] = value

    data_source = data.get("data_source")
    if isinstance(data_source, dict):
        group = dict(data_source)
        if "tushare_token" in group:
            raise ValueError(
                "data_source.tushare_token is not accepted in config.json; "
                "set the environment variable named by "
                "data_source.provider_config.tushare_token_env"
            )
        unknown = sorted(set(group) - _DATA_SOURCE_CONFIG_GROUP_FIELDS)
        if unknown:
            raise ValueError(
                "data_source config group contains unsupported fields: "
                + ", ".join(unknown)
            )
        data.pop("data_source")
        field_mapping = {
            "provider": "data_source",
            "live_poll_interval": "live_poll_interval",
            "provider_config": "data_source_provider_config",
        }
        for grouped_field, value in group.items():
            runtime_field = field_mapping[grouped_field]
            if runtime_field in data:
                raise ValueError(
                    f"config field {runtime_field} cannot appear both grouped and flat"
                )
            data[runtime_field] = value

    broker_fee = data.pop("broker_fee", None)
    if broker_fee is not None:
        if not isinstance(broker_fee, dict):
            raise ValueError("broker_fee config group must be an object")
        if "broker_fee_schedule" in data:
            raise ValueError("broker fee config cannot appear both grouped and flat")
        data["broker_fee_schedule"] = broker_fee

    ai = data.pop("ai", None)
    if ai is not None:
        if not isinstance(ai, dict):
            raise ValueError("ai config group must be an object")
        if "allow_financial_context" in ai:
            raise ValueError(
                "ai.allow_financial_context was removed; external financial "
                "evidence must be authorized by its workflow-specific contract"
            )
        if "api_keys" in ai:
            raise ValueError(
                "ai.api_keys is not accepted in config.json; set the environment "
                "variable named by ai.api_key_env"
            )
        unknown = sorted(set(ai) - _AI_CONFIG_GROUP_FIELDS)
        if unknown:
            raise ValueError(
                "ai config group contains unsupported fields: " + ", ".join(unknown)
            )
        data["ai"] = dict(ai)

    account_truth = data.pop("account_truth", None)
    if account_truth is not None:
        if not isinstance(account_truth, dict):
            raise ValueError("account_truth config group must be an object")
        unknown = sorted(set(account_truth) - _ACCOUNT_TRUTH_CONFIG_GROUP_FIELDS)
        if unknown:
            raise ValueError(
                "account_truth config group contains unsupported fields: "
                + ", ".join(unknown)
            )
        collector = account_truth.get("broker_statement_collector")
        if collector is not None:
            if "broker_statement_collector" in data:
                raise ValueError(
                    "broker statement collector config cannot appear both grouped "
                    "and flat"
                )
            data["broker_statement_collector"] = collector

    return data


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
    exchange_transfer_fee_rates: dict[str, Decimal] = field(default_factory=dict)
    other_fee_rate: Decimal = Decimal("0")
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
    path: str = "broker_statement.csv"
    poll_interval_seconds: float = 5.0
    stability_delay_seconds: float = 2.0
    max_file_bytes: int = 10 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError(
                "account_truth.broker_statement_collector.enabled must be boolean"
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
class DataSourceProviderConfig:
    """Credential-free provider edge settings for market-data startup."""

    tushare_token_env: str = "KARKINOS_TUSHARE_TOKEN"

    def __post_init__(self) -> None:
        if not _ENV_NAME_PATTERN.fullmatch(self.tushare_token_env):
            raise ValueError(
                "data_source.provider_config.tushare_token_env must be an "
                "uppercase environment variable name"
            )


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
        """从 JSON 文件加载配置。"""
        path = Path(path)
        with path.open("r") as f:
            data = _normalize_grouped_config_payload(json.load(f))
        _validate_runtime_config_fields(data)

        # 将数值型 initial_cash 转为 Decimal
        if "initial_cash" in data and not isinstance(data["initial_cash"], Decimal):
            data["initial_cash"] = Decimal(str(data["initial_cash"]))
        if "commission_rate" in data and not isinstance(
            data["commission_rate"], Decimal
        ):
            data["commission_rate"] = Decimal(str(data["commission_rate"]))
        if "account_commission_rate" in data and not isinstance(
            data["account_commission_rate"], Decimal
        ):
            data["account_commission_rate"] = Decimal(
                str(data["account_commission_rate"])
            )
        if "account_min_commission" in data and not isinstance(
            data["account_min_commission"], Decimal
        ):
            data["account_min_commission"] = Decimal(
                str(data["account_min_commission"])
            )

        # 空字符串视为"使用默认值"（config.example.json 中 end_date 为 ""）
        if data.get("end_date") == "":
            del data["end_date"]
        if "broker_connectors" in data:
            data["broker_connectors"] = _parse_broker_connector_configs(
                data["broker_connectors"]
            )
        if "data_source_provider_config" in data:
            data["data_source_provider_config"] = _parse_data_source_provider_config(
                data["data_source_provider_config"]
            )
        if "ai" in data:
            data["ai"] = _parse_ai_provider_config(data["ai"])
        if "broker_statement_collector" in data:
            data["broker_statement_collector"] = (
                _parse_broker_statement_collector_config(
                    data["broker_statement_collector"]
                )
            )
        _validate_core_runtime_values(data)
        if "controlled_bridge_policy" in data:
            data["controlled_bridge_policy"] = _parse_controlled_bridge_policy_config(
                data["controlled_bridge_policy"]
            )
        if "trusted_operator_identities" in data:
            data["trusted_operator_identities"] = (
                _parse_trusted_operator_identity_configs(
                    data["trusted_operator_identities"]
                )
            )
        has_broker_fee_schedule = "broker_fee_schedule" in data
        if has_broker_fee_schedule:
            data["broker_fee_schedule"] = _parse_broker_fee_schedule_config(
                data["broker_fee_schedule"]
            )
        elif "account_commission_rate" in data or "account_min_commission" in data:
            # Backward-compatible migration path: older ignored local
            # config.json files stored account cost inputs at top level.
            data["broker_fee_schedule"] = BrokerFeeScheduleConfig(
                stock_a_commission_rate=data.get(
                    "account_commission_rate",
                    BrokerFeeScheduleConfig().stock_a_commission_rate,
                ),
                stock_a_min_commission=data.get(
                    "account_min_commission",
                    BrokerFeeScheduleConfig().stock_a_min_commission,
                ),
            )
        if "broker_fee_schedule" in data:
            schedule = data["broker_fee_schedule"]
            data["account_commission_rate"] = schedule.stock_a_commission_rate
            data["account_min_commission"] = schedule.stock_a_min_commission

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ServerConfig(BacktestConfig):
    """服务器配置 — 继承 BacktestConfig，添加服务器相关字段。"""

    host: str = "0.0.0.0"
    port: int = 8000
    live_auto_start: bool = True
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    broker_statement_collector: BrokerStatementCollectorConfig = field(
        default_factory=BrokerStatementCollectorConfig
    )
    controlled_bridge_policy: ControlledBridgePolicyConfig = field(
        default_factory=ControlledBridgePolicyConfig
    )
    trusted_operator_identities: list[TrustedOperatorIdentityConfig] = field(
        default_factory=list
    )


def _validate_runtime_config_fields(data: dict) -> None:
    """Reject misspelled or unsupported top-level fields before startup."""

    if "tushare_token" in data:
        raise ValueError(
            "tushare_token is not accepted in config.json; set the environment "
            "variable named by data_source.provider_config.tushare_token_env"
        )
    allowed_fields = set(ServerConfig.__dataclass_fields__)
    unknown = sorted(set(data) - allowed_fields)
    if unknown:
        raise ValueError(
            "config.json contains unsupported top-level fields: " + ", ".join(unknown)
        )


def _parse_ai_provider_config(value: object) -> AIProviderConfig:
    if value is None:
        return AIProviderConfig()
    if not isinstance(value, dict):
        raise ValueError("ai config group must be an object")
    timeout_seconds = value.get("timeout_seconds", 20.0)
    if isinstance(timeout_seconds, bool):
        raise ValueError("ai.timeout_seconds must be numeric")
    try:
        timeout_seconds = float(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("ai.timeout_seconds must be numeric") from exc
    return AIProviderConfig(
        enabled=value.get("enabled", False),
        provider=value.get("provider", ""),
        model=value.get("model", ""),
        base_url=value.get("base_url", ""),
        adapter_kind=value.get("adapter_kind", "openai_compatible_https"),
        timeout_seconds=timeout_seconds,
        api_key_env=value.get("api_key_env") or "KARKINOS_AI_API_KEY",
    )


def _parse_broker_statement_collector_config(
    value: object,
) -> BrokerStatementCollectorConfig:
    if value is None:
        return BrokerStatementCollectorConfig()
    if not isinstance(value, dict):
        raise ValueError("account_truth.broker_statement_collector must be an object")
    unknown = sorted(set(value) - _BROKER_STATEMENT_COLLECTOR_ALLOWED_FIELDS)
    if unknown:
        raise ValueError(
            "account_truth.broker_statement_collector contains unsupported fields: "
            + ", ".join(unknown)
        )
    return BrokerStatementCollectorConfig(
        enabled=value.get("enabled", False),
        path=value.get("path", "broker_statement.csv"),
        poll_interval_seconds=value.get("poll_interval_seconds", 5.0),
        stability_delay_seconds=value.get("stability_delay_seconds", 2.0),
        max_file_bytes=value.get("max_file_bytes", 10 * 1024 * 1024),
    )


def _parse_data_source_provider_config(
    value: object,
) -> DataSourceProviderConfig:
    if value is None:
        return DataSourceProviderConfig()
    if not isinstance(value, dict):
        raise ValueError("data_source.provider_config must be an object")
    unknown = sorted(set(value) - {"tushare_token_env"})
    if unknown:
        raise ValueError(
            "data_source.provider_config contains unsupported fields: "
            + ", ".join(unknown)
        )
    return DataSourceProviderConfig(
        tushare_token_env=str(
            value.get("tushare_token_env") or "KARKINOS_TUSHARE_TOKEN"
        )
    )


def _validate_core_runtime_values(data: dict) -> None:
    if "host" in data and (
        not isinstance(data["host"], str) or not data["host"].strip()
    ):
        raise ValueError("server.host must be a non-empty string")
    if "port" in data and (
        isinstance(data["port"], bool)
        or not isinstance(data["port"], int)
        or data["port"] <= 0
        or data["port"] > 65_535
    ):
        raise ValueError("server.port must be an integer within [1, 65535]")
    if "live_auto_start" in data and not isinstance(data["live_auto_start"], bool):
        raise ValueError("server.live_auto_start must be boolean")
    if "cors_allowed_origins" in data:
        origins = data["cors_allowed_origins"]
        if (
            not isinstance(origins, list)
            or not origins
            or any(
                not isinstance(origin, str) or not origin.strip() for origin in origins
            )
        ):
            raise ValueError(
                "server.cors_allowed_origins must be a non-empty string list"
            )
    if "notification" in data:
        _validate_notification_config(data["notification"])
    if "data_source" in data and data["data_source"] not in SUPPORTED_DATA_SOURCES:
        raise ValueError("data_source.provider must be akshare or tushare")
    if "live_poll_interval" in data and (
        isinstance(data["live_poll_interval"], bool)
        or not isinstance(data["live_poll_interval"], int)
        or data["live_poll_interval"] < MIN_LIVE_POLL_INTERVAL_SECONDS
    ):
        raise ValueError(
            "data_source.live_poll_interval must be an integer greater than or "
            f"equal to {MIN_LIVE_POLL_INTERVAL_SECONDS}"
        )


def _validate_notification_config(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError("server.notification must be an object")
    unknown = sorted(set(value) - {"type"})
    if unknown:
        raise ValueError(
            "server.notification contains unsupported or credential-bearing fields: "
            + ", ".join(unknown)
        )
    notification_type = value.get("type", "console")
    if notification_type not in SUPPORTED_NOTIFICATION_TYPES:
        raise ValueError(
            "server.notification.type must be console, telegram, or wechat"
        )


def _parse_broker_connector_configs(value: object) -> list[BrokerConnectorConfig]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("broker connector config must be a list")

    configs: list[BrokerConnectorConfig] = []
    for index, raw_entry in enumerate(value):
        if not isinstance(raw_entry, dict):
            raise ValueError(
                f"broker connector config at index {index} must be an object"
            )
        if _contains_sensitive_connector_key(raw_entry):
            raise ValueError(
                "broker connector config must not contain password, secret, "
                "token, or credential fields"
            )
        unknown_fields = sorted(set(raw_entry) - _BROKER_CONNECTOR_ALLOWED_FIELDS)
        if unknown_fields:
            raise ValueError(
                "broker connector config contains unsupported fields: "
                + ", ".join(unknown_fields)
            )
        connector_id = str(raw_entry.get("connector_id", "")).strip()
        if not connector_id:
            raise ValueError("broker connector config requires connector_id")
        enabled = raw_entry.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("broker connector config enabled must be boolean")
        configs.append(
            BrokerConnectorConfig(
                connector_id=connector_id,
                connector_type=str(
                    raw_entry.get("connector_type", "local_export_readonly")
                ).strip()
                or "local_export_readonly",
                enabled=enabled,
                client_path=str(raw_entry.get("client_path", "")).strip(),
                account_alias=str(raw_entry.get("account_alias", "")).strip(),
            )
        )
    return configs


def _parse_trusted_operator_identity_configs(
    value: object,
) -> list[TrustedOperatorIdentityConfig]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("trusted operator identities must be a list")
    results: list[TrustedOperatorIdentityConfig] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_entry in enumerate(value):
        if not isinstance(raw_entry, dict):
            raise ValueError(
                f"trusted operator identity at index {index} must be an object"
            )
        unknown_fields = sorted(
            set(raw_entry) - _TRUSTED_OPERATOR_IDENTITY_ALLOWED_FIELDS
        )
        if unknown_fields:
            raise ValueError(
                "trusted operator identity contains unsupported fields: "
                + ", ".join(unknown_fields)
            )
        operator_id = str(raw_entry.get("operator_id") or "").strip()
        key_id = str(raw_entry.get("key_id") or "").strip()
        algorithm = str(raw_entry.get("algorithm") or "ed25519").strip().lower()
        public_key_base64 = str(raw_entry.get("public_key_base64") or "").strip()
        enabled = raw_entry.get("enabled", False)
        if not _TRUSTED_OPERATOR_ID_PATTERN.fullmatch(operator_id):
            raise ValueError("trusted operator identity operator_id invalid")
        if not _TRUSTED_OPERATOR_ID_PATTERN.fullmatch(key_id):
            raise ValueError("trusted operator identity key_id invalid")
        if algorithm != "ed25519":
            raise ValueError("trusted operator identity algorithm must be ed25519")
        if not isinstance(enabled, bool):
            raise ValueError("trusted operator identity enabled must be boolean")
        try:
            public_key = base64.b64decode(public_key_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "trusted operator identity public key must be valid base64"
            ) from exc
        if len(public_key) != 32:
            raise ValueError(
                "trusted operator identity Ed25519 public key must be 32 bytes"
            )
        identity = (operator_id, key_id)
        if identity in seen:
            raise ValueError("trusted operator identity operator_id/key_id duplicated")
        seen.add(identity)
        results.append(
            TrustedOperatorIdentityConfig(
                operator_id=operator_id,
                key_id=key_id,
                algorithm=algorithm,
                public_key_base64=public_key_base64,
                enabled=enabled,
            )
        )
    return results


def _contains_sensitive_connector_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            any(
                part in str(key).lower()
                for part in _BROKER_CONNECTOR_SENSITIVE_KEY_PARTS
            )
            or _contains_sensitive_connector_key(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_connector_key(item) for item in value)
    return False


def _tuple_of_strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError("controlled bridge policy whitelist fields must be lists")
    return tuple(
        dict.fromkeys(str(item).strip() for item in value if str(item).strip())
    )


def _parse_controlled_bridge_policy_config(
    value: object,
) -> ControlledBridgePolicyConfig:
    if value is None:
        return ControlledBridgePolicyConfig()
    if not isinstance(value, dict):
        raise ValueError("controlled bridge policy config must be an object")
    if _contains_sensitive_connector_key(value):
        raise ValueError(
            "controlled bridge policy config must not contain password, secret, "
            "token, or credential fields"
        )
    unknown_fields = sorted(set(value) - _CONTROLLED_BRIDGE_POLICY_ALLOWED_FIELDS)
    if unknown_fields:
        raise ValueError(
            "controlled bridge policy config contains unsupported fields: "
            + ", ".join(unknown_fields)
        )

    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("controlled bridge policy enabled must be boolean")
    per_order_confirmation_required = value.get(
        "per_order_confirmation_required",
        True,
    )
    if not isinstance(per_order_confirmation_required, bool):
        raise ValueError(
            "controlled bridge policy per_order_confirmation_required must be boolean"
        )
    if not per_order_confirmation_required:
        raise ValueError("controlled bridge policy must require per-order confirmation")
    automation_allowed = value.get("automation_allowed", False)
    if not isinstance(automation_allowed, bool):
        raise ValueError("controlled bridge policy automation_allowed must be boolean")
    if automation_allowed:
        raise ValueError("controlled bridge policy cannot enable automation in v1.7")

    return ControlledBridgePolicyConfig(
        policy_id=str(
            value.get(
                "policy_id",
                ControlledBridgePolicyConfig().policy_id,
            )
        ).strip()
        or ControlledBridgePolicyConfig().policy_id,
        enabled=enabled,
        allowed_connector_ids=_tuple_of_strings(value.get("allowed_connector_ids", ())),
        allowed_account_aliases=_tuple_of_strings(
            value.get("allowed_account_aliases", ())
        ),
        allowed_strategy_ids=_tuple_of_strings(value.get("allowed_strategy_ids", ())),
        allowed_symbols=_tuple_of_strings(value.get("allowed_symbols", ())),
        per_order_confirmation_required=per_order_confirmation_required,
        automation_allowed=False,
    )


def _parse_broker_fee_schedule_config(value: object) -> BrokerFeeScheduleConfig:
    if value is None:
        return BrokerFeeScheduleConfig()
    if not isinstance(value, dict):
        raise ValueError("broker fee schedule config must be an object")
    if _contains_sensitive_connector_key(value):
        raise ValueError(
            "broker fee schedule config must not contain password, secret, "
            "token, or credential fields"
        )
    if any(
        bool(value.get(flag))
        for flag in (
            "account_identifier_saved",
            "screenshots_saved",
            "private_exports_saved",
        )
    ):
        raise ValueError(
            "broker fee schedule config must not store account identifiers, "
            "screenshots, or private exports"
        )
    unknown_fields = sorted(set(value) - _BROKER_FEE_SCHEDULE_ALLOWED_FIELDS)
    if unknown_fields:
        raise ValueError(
            "broker fee schedule config contains unsupported fields: "
            + ", ".join(unknown_fields)
        )

    limitations = value.get(
        "limitations",
        BrokerFeeScheduleConfig.__dataclass_fields__["limitations"].default,
    )
    if not isinstance(limitations, list | tuple):
        raise ValueError("broker fee schedule limitations must be a list")
    exchange_transfer_fee_rates = _exchange_transfer_fee_rates(value)
    limitation_values = [str(item).strip() for item in limitations if str(item).strip()]
    if exchange_transfer_fee_rates:
        limitation_values = [
            item
            for item in limitation_values
            if item != "transfer_fee_exchange_not_split"
        ]
    if _has_nested_broker_fee_schedule(value):
        limitation_values.append("nested_fee_schedule_flattened_for_current_contract")

    return BrokerFeeScheduleConfig(
        schedule_id=str(_fee_schedule_id(value)).strip()
        or BrokerFeeScheduleConfig().schedule_id,
        account_profile_id=str(value.get("account_profile_id", "")).strip(),
        broker_name=str(value.get("broker_name", "")).strip(),
        stock_a_commission_rate=_decimal_fee_config(
            value,
            "stock_a_commission_rate",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("stock",),
                field_name="rate",
                default=_nested_fee_value(
                    value,
                    section="commission",
                    names=("stock_a", "stock", "a_share", "ashare"),
                    default="0.0001",
                ),
            ),
        ),
        stock_a_min_commission=_decimal_fee_config(
            value,
            "stock_a_min_commission",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("stock",),
                field_name="min_fee",
                default="5",
            ),
        ),
        fund_etf_commission_rate=_decimal_fee_config(
            value,
            "fund_etf_commission_rate",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("fund", "etf"),
                field_name="rate",
                default=_nested_fee_value(
                    value,
                    section="commission",
                    names=("fund_etf", "etf", "fund"),
                    default="0.0001",
                ),
            ),
        ),
        fund_etf_min_commission=_decimal_fee_config(
            value,
            "fund_etf_min_commission",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("fund", "etf"),
                field_name="min_fee",
                default="5",
            ),
        ),
        stamp_tax_rate=_decimal_fee_config(
            value,
            "stamp_tax_rate",
            _rule_fee_value(
                value,
                component="stamp_tax",
                asset_classes=("stock",),
                field_name="rate",
                side="sell",
                default=_nested_fee_value(
                    value,
                    section="taxes_and_fees",
                    names=("stamp_tax", "stamp", "stock_stamp_tax"),
                    default="0.0005",
                ),
            ),
        ),
        transfer_fee_rate=_decimal_fee_config(
            value,
            "transfer_fee_rate",
            _rule_fee_value(
                value,
                component="transfer_fee",
                asset_classes=("stock",),
                field_name="rate",
                default=_nested_fee_value(
                    value,
                    section="taxes_and_fees",
                    names=("transfer_fee", "stock_transfer_fee"),
                    default="0.00001",
                ),
            ),
        ),
        exchange_transfer_fee_rates=exchange_transfer_fee_rates,
        other_fee_rate=_decimal_fee_config(
            value,
            "other_fee_rate",
            _nested_fee_value(
                value,
                section="taxes_and_fees",
                names=("other_fee", "other_fees"),
                default="0",
            ),
        ),
        limitations=tuple(dict.fromkeys(limitation_values)),
    )


def _decimal_fee_config(
    value: dict[str, object], field_name: str, default: str
) -> Decimal:
    raw_value = value.get(field_name, default)
    return Decimal(str(raw_value))


def _fee_schedule_id(value: dict[str, object]) -> object:
    return value.get(
        "schedule_id",
        value.get(
            "profile_id",
            value.get("source", BrokerFeeScheduleConfig().schedule_id),
        ),
    )


def _has_nested_broker_fee_schedule(value: dict[str, object]) -> bool:
    return any(
        isinstance(value.get(section), dict)
        for section in ("commission", "taxes_and_fees")
    ) or isinstance(value.get("rules"), list)


def _nested_fee_value(
    value: dict[str, object],
    *,
    section: str,
    names: tuple[str, ...],
    default: str,
) -> object:
    section_value = value.get(section)
    if not isinstance(section_value, dict):
        return default
    for name in names:
        if name in section_value:
            return _first_decimal_like(section_value[name], default=default)
    return default


def _rule_fee_value(
    value: dict[str, object],
    *,
    component: str,
    asset_classes: tuple[str, ...],
    field_name: str,
    default: object,
    side: str | None = None,
) -> object:
    rules = value.get("rules")
    if not isinstance(rules, list):
        return default
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        if str(raw_rule.get("component", "")).strip().lower() != component:
            continue
        if not _rule_has_any(raw_rule.get("asset_classes"), asset_classes):
            continue
        if side is not None and not _rule_side_matches(raw_rule.get("side"), side):
            continue
        raw_value = raw_rule.get(field_name)
        if raw_value is not None:
            return raw_value
    return default


def _rule_has_any(value: object, expected: tuple[str, ...]) -> bool:
    expected_values = {item.strip().lower() for item in expected}
    if isinstance(value, list | tuple):
        return any(str(item).strip().lower() in expected_values for item in value)
    return str(value).strip().lower() in expected_values


def _rule_side_matches(value: object, expected: str) -> bool:
    side = str(value or "both").strip().lower()
    return side in {expected, "both", "all"}


def _exchange_transfer_fee_rates(value: dict[str, object]) -> dict[str, Decimal]:
    direct_value = value.get("exchange_transfer_fee_rates")
    raw_rates: dict[str, object] = {}
    if isinstance(direct_value, dict):
        raw_rates.update(direct_value)

    taxes_and_fees = value.get("taxes_and_fees")
    if isinstance(taxes_and_fees, dict):
        transfer_fee = taxes_and_fees.get("transfer_fee")
        if isinstance(transfer_fee, dict):
            for raw_key, raw_value in transfer_fee.items():
                exchange = _normalize_exchange_key(raw_key)
                if exchange:
                    raw_rates.setdefault(exchange, raw_value)

    rules = value.get("rules")
    if isinstance(rules, list):
        for raw_rule in rules:
            if not isinstance(raw_rule, dict):
                continue
            if str(raw_rule.get("component", "")).strip().lower() != "transfer_fee":
                continue
            raw_rate = raw_rule.get("rate")
            if raw_rate is None:
                continue
            markets = raw_rule.get("markets")
            if not isinstance(markets, list | tuple):
                markets = [markets]
            for market in markets:
                exchange = _normalize_exchange_key(market)
                if exchange:
                    raw_rates.setdefault(exchange, raw_rate)

    parsed: dict[str, Decimal] = {}
    for raw_key, raw_value in raw_rates.items():
        exchange = _normalize_exchange_key(raw_key)
        if exchange:
            parsed[exchange] = Decimal(str(raw_value))
    return parsed


def _normalize_exchange_key(value: object) -> str | None:
    key = str(value).strip().lower()
    if not key or key in {"rate", "sell", "buy", "value", "default"}:
        return None
    return _EXCHANGE_ALIASES.get(key)


def _first_decimal_like(value: object, *, default: str) -> object:
    if isinstance(value, int | float | str | Decimal):
        return value
    if isinstance(value, dict):
        for key in ("rate", "sell", "sh", "sz", "value"):
            if key in value:
                return _first_decimal_like(value[key], default=default)
    return default
