"""类型化配置加载。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

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


@dataclass(frozen=True)
class BrokerConnectorConfig:
    """Read-only broker connector runtime config stored only in local config."""

    connector_id: str
    connector_type: str = "qmt_readonly"
    enabled: bool = False
    client_path: str = ""
    account_alias: str = ""


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
    tushare_token: str = ""
    notification: dict = field(default_factory=lambda: {"type": "console"})
    live_poll_interval: int = 60
    broker_connectors: list[BrokerConnectorConfig] = field(default_factory=list)
    broker_fee_schedule: BrokerFeeScheduleConfig = field(
        default_factory=BrokerFeeScheduleConfig
    )

    @classmethod
    def from_json(cls, path: str | Path) -> BacktestConfig:
        """从 JSON 文件加载配置。"""
        path = Path(path)
        with path.open("r") as f:
            data = json.load(f)

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
                    raw_entry.get("connector_type", "qmt_readonly")
                ).strip()
                or "qmt_readonly",
                enabled=enabled,
                client_path=str(raw_entry.get("client_path", "")).strip(),
                account_alias=str(raw_entry.get("account_alias", "")).strip(),
            )
        )
    return configs


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
            _nested_fee_value(
                value,
                section="commission",
                names=("stock_a", "stock", "a_share", "ashare"),
                default="0.0001",
            ),
        ),
        stock_a_min_commission=_decimal_fee_config(
            value, "stock_a_min_commission", "5"
        ),
        fund_etf_commission_rate=_decimal_fee_config(
            value,
            "fund_etf_commission_rate",
            _nested_fee_value(
                value,
                section="commission",
                names=("fund_etf", "etf", "fund"),
                default="0.0001",
            ),
        ),
        fund_etf_min_commission=_decimal_fee_config(
            value, "fund_etf_min_commission", "5"
        ),
        stamp_tax_rate=_decimal_fee_config(
            value,
            "stamp_tax_rate",
            _nested_fee_value(
                value,
                section="taxes_and_fees",
                names=("stamp_tax", "stamp", "stock_stamp_tax"),
                default="0.0005",
            ),
        ),
        transfer_fee_rate=_decimal_fee_config(
            value,
            "transfer_fee_rate",
            _nested_fee_value(
                value,
                section="taxes_and_fees",
                names=("transfer_fee", "stock_transfer_fee"),
                default="0.00001",
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
        for section in ("commission", "taxes_and_fees", "rules")
    )


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
