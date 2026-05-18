"""类型化配置加载。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


@dataclass
class BacktestConfig:
    """回测配置。"""

    initial_cash: Decimal = Decimal("100000")
    start_date: str = "2025-01-02"
    end_date: str = field(default_factory=lambda: _DEFAULT_END_DATE)
    assets: list[dict] = field(
        default_factory=lambda: [
            {"symbol": "600519", "asset_class": "stock"},
            {"symbol": "510300", "asset_class": "etf"},
            {"symbol": "Au99.99", "asset_class": "gold"},
        ]
    )
    strategy: str = "dual_ma"
    short_period: int = 5
    long_period: int = 20
    commission_rate: Decimal = Decimal("0.0003")
    data_source: str = "akshare"
    tushare_token: str = ""
    notification: dict = field(default_factory=lambda: {"type": "console"})
    live_poll_interval: int = 60

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

        # 空字符串视为"使用默认值"（config.example.json 中 end_date 为 ""）
        if data.get("end_date") == "":
            del data["end_date"]

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
