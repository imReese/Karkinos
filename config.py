"""类型化配置加载。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass
class BacktestConfig:
    """回测配置。"""

    initial_cash: Decimal = Decimal("1000000")
    start_date: str = "2024-01-02"
    end_date: str = "2024-12-31"
    symbols: list[str] = field(default_factory=lambda: ["600519"])
    strategy: str = "dual_ma"
    short_period: int = 5
    long_period: int = 20
    commission_rate: Decimal = Decimal("0.0003")

    @classmethod
    def from_json(cls, path: str | Path) -> BacktestConfig:
        """从 JSON 文件加载配置。"""
        path = Path(path)
        with path.open("r") as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
