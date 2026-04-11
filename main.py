"""MyQuant — 个人量化交易系统入口。"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from analytics.report import generate_report
from backtest.engine import BacktestEngine
from config import BacktestConfig
from core.event_bus import EventBus
from core.types import Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from strategy.examples.dual_ma import DualMAStrategy


def make_synthetic_data(
    symbol: str = "600519",
    base_price: float = 1800.0,
    n_days: int = 120,
    seed: int = 42,
) -> pd.DataFrame:
    """生成模拟行情数据（用于演示）。"""
    np.random.seed(seed)
    dates = pd.bdate_range("2024-01-02", periods=n_days)
    changes = np.random.randn(n_days) * 5
    close = base_price + np.cumsum(changes)
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": [10000.0] * n_days,
        }
    )


def main() -> None:
    """主入口：加载配置 → 创建组件 → 运行回测 → 输出报告。"""
    config = BacktestConfig()

    # 创建标的
    instruments = {}
    data_handlers = {}
    for code in config.symbols:
        inst = make_stock(code, f"标的{code}")
        instruments[Symbol(code)] = inst

        # 生成模拟数据（实际使用时应从数据源加载）
        df = make_synthetic_data(code, n_days=120)
        data_handlers[Symbol(code)] = DataHandler(df, Symbol(code))

    # 创建策略
    bus = EventBus()
    strategy = DualMAStrategy(
        bus,
        short_period=config.short_period,
        long_period=config.long_period,
    )

    # 创建并运行回测引擎
    engine = BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers=data_handlers,
        initial_cash=config.initial_cash,
    )

    result = engine.run()

    # 生成报告
    report = generate_report(result)
    print(report)


if __name__ == "__main__":
    main()
