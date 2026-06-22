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


@dataclass(frozen=True)
class BrokerConnectorConfig:
    """Read-only broker connector runtime config stored only in local config."""

    connector_id: str
    connector_type: str = "qmt_readonly"
    enabled: bool = False
    client_path: str = ""
    account_alias: str = ""


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
