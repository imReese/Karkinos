"""Strict local JSON loading and validation for runtime configuration."""

from __future__ import annotations

import base64
import binascii
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from server.config_contract import (
    MIN_LIVE_POLL_INTERVAL_SECONDS,
    SUPPORTED_DATA_SOURCES,
    SUPPORTED_NOTIFICATION_TYPES,
)
from server.config_fee_schedule import parse_broker_fee_schedule_config
from server.config_safety import contains_sensitive_config_key
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
_SERVER_CONFIG_GROUP_FIELDS = frozenset(
    {
        "host",
        "port",
        "market_calendar_auto_sync",
        "cors_allowed_origins",
        "notification",
    }
)
_IGNORED_LEGACY_CONFIG_FIELDS = frozenset({"live_auto_start"})
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
_ACCOUNT_TRUTH_CONFIG_GROUP_FIELDS = frozenset(
    {"broker_statement_collector", "citic_history_xls_directory"}
)
_BROKER_STATEMENT_COLLECTOR_ALLOWED_FIELDS = frozenset(
    {
        "enabled",
        "daily_snapshot_roll_forward_enabled",
        "path",
        "poll_interval_seconds",
        "stability_delay_seconds",
        "max_file_bytes",
    }
)
_CITIC_HISTORY_XLS_DIRECTORY_ALLOWED_FIELDS = frozenset(
    {
        "enabled",
        "path",
        "max_files",
        "max_file_bytes",
        "max_total_bytes",
    }
)


def _normalize_grouped_config_payload(raw: object) -> dict:
    """Map grouped local JSON sections onto the stable runtime config fields."""

    if not isinstance(raw, dict):
        raise ValueError("config.json root must be an object")
    data = dict(raw)
    for field in _IGNORED_LEGACY_CONFIG_FIELDS:
        data.pop(field, None)

    server = data.pop("server", None)
    if server is not None:
        if not isinstance(server, dict):
            raise ValueError("server config group must be an object")
        server = dict(server)
        for field in _IGNORED_LEGACY_CONFIG_FIELDS:
            server.pop(field, None)
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
        citic_directory = account_truth.get("citic_history_xls_directory")
        if citic_directory is not None:
            if "citic_history_xls_directory" in data:
                raise ValueError(
                    "CITIC history XLS directory config cannot appear both "
                    "grouped and flat"
                )
            data["citic_history_xls_directory"] = citic_directory

    return data


def load_config(config_type: type[Any], path: str | Path) -> Any:
    """Load, normalize, and fail-closed validate one local JSON document."""
    path = Path(path)
    with path.open("r") as f:
        data = _normalize_grouped_config_payload(json.load(f))
    _validate_runtime_config_fields(data, config_type=config_type)

    # 将数值型 initial_cash 转为 Decimal
    if "initial_cash" in data and not isinstance(data["initial_cash"], Decimal):
        data["initial_cash"] = Decimal(str(data["initial_cash"]))
    if "commission_rate" in data and not isinstance(data["commission_rate"], Decimal):
        data["commission_rate"] = Decimal(str(data["commission_rate"]))
    if "account_commission_rate" in data and not isinstance(
        data["account_commission_rate"], Decimal
    ):
        data["account_commission_rate"] = Decimal(str(data["account_commission_rate"]))
    if "account_min_commission" in data and not isinstance(
        data["account_min_commission"], Decimal
    ):
        data["account_min_commission"] = Decimal(str(data["account_min_commission"]))

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
        data["broker_statement_collector"] = _parse_broker_statement_collector_config(
            data["broker_statement_collector"]
        )
    if "citic_history_xls_directory" in data:
        data["citic_history_xls_directory"] = _parse_citic_history_xls_directory_config(
            data["citic_history_xls_directory"]
        )
    _validate_core_runtime_values(data)
    if "controlled_bridge_policy" in data:
        data["controlled_bridge_policy"] = _parse_controlled_bridge_policy_config(
            data["controlled_bridge_policy"]
        )
    if "trusted_operator_identities" in data:
        data["trusted_operator_identities"] = _parse_trusted_operator_identity_configs(
            data["trusted_operator_identities"]
        )
    has_broker_fee_schedule = "broker_fee_schedule" in data
    if has_broker_fee_schedule:
        data["broker_fee_schedule"] = parse_broker_fee_schedule_config(
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

    return config_type(
        **{k: v for k, v in data.items() if k in config_type.__dataclass_fields__}
    )


def _validate_runtime_config_fields(data: dict, *, config_type: type[Any]) -> None:
    """Reject misspelled or unsupported top-level fields before startup."""

    if "tushare_token" in data:
        raise ValueError(
            "tushare_token is not accepted in config.json; set the environment "
            "variable named by data_source.provider_config.tushare_token_env"
        )
    allowed_fields = set(config_type.__dataclass_fields__)
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
        daily_snapshot_roll_forward_enabled=value.get(
            "daily_snapshot_roll_forward_enabled",
            False,
        ),
        path=value.get("path", "broker_statement.csv"),
        poll_interval_seconds=value.get("poll_interval_seconds", 5.0),
        stability_delay_seconds=value.get("stability_delay_seconds", 2.0),
        max_file_bytes=value.get("max_file_bytes", 10 * 1024 * 1024),
    )


def _parse_citic_history_xls_directory_config(
    value: object,
) -> CiticHistoryXlsDirectoryConfig:
    if value is None:
        return CiticHistoryXlsDirectoryConfig()
    if not isinstance(value, dict):
        raise ValueError("account_truth.citic_history_xls_directory must be an object")
    unknown = sorted(set(value) - _CITIC_HISTORY_XLS_DIRECTORY_ALLOWED_FIELDS)
    if unknown:
        raise ValueError(
            "account_truth.citic_history_xls_directory contains unsupported "
            "fields: " + ", ".join(unknown)
        )
    return CiticHistoryXlsDirectoryConfig(
        enabled=value.get("enabled", False),
        path=value.get("path", ""),
        max_files=value.get("max_files", 120),
        max_file_bytes=value.get("max_file_bytes", 10 * 1024 * 1024),
        max_total_bytes=value.get("max_total_bytes", 64 * 1024 * 1024),
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
    if "market_calendar_auto_sync" in data and not isinstance(
        data["market_calendar_auto_sync"], bool
    ):
        raise ValueError("server.market_calendar_auto_sync must be boolean")
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
        if contains_sensitive_config_key(raw_entry):
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
    if contains_sensitive_config_key(value):
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
