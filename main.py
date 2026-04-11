"""MyQuant — 个人量化交易系统入口。"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

# 触发所有策略注册
import strategy.examples  # noqa: F401
from analytics.report import generate_report
from backtest.engine import BacktestEngine
from config import BacktestConfig
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.manager import DataManager
from data.providers.akshare_source import AKShareSource
from data.providers.tushare_source import TushareSource
from data.store import DataStore
from strategy.registry import StrategyRegistry

# 配置中的 asset_class 字符串 → AssetClass 枚举
_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}


def main() -> None:
    """主入口：加载配置 → 拉取真实数据 → 多资产回测 → 输出报告。"""
    config = BacktestConfig()

    # 构建数据源
    sources: dict = {"akshare": AKShareSource()}
    tushare_token = os.environ.get("TUSHARE_TOKEN")
    if tushare_token:
        sources["tushare"] = TushareSource(token=tushare_token)

    manager = DataManager(sources, store=DataStore("data/store"))

    start = datetime.strptime(config.start_date, "%Y-%m-%d")
    end = datetime.strptime(config.end_date, "%Y-%m-%d")

    # 遍历资产配置，拉取数据 + 创建标的
    instruments = {}
    data_handlers = {}
    for asset_cfg in config.assets:
        sym = Symbol(asset_cfg["symbol"])
        ac = _ASSET_CLASS_MAP[asset_cfg["asset_class"]]

        print(f"拉取数据: {sym} ({ac.value}) ...")
        handler = manager.get_bars(
            sym,
            start=start,
            end=end,
            asset_class=ac,
        )
        data_handlers[sym] = handler
        instruments[sym] = DataManager.get_instrument(sym, ac)

        print(f"  → {handler.total_bars} 根K线")

    if not instruments:
        print("未配置任何标的，退出。")
        return

    # 创建策略（使用注册表）
    bus_placeholder = type("FakeBus", (), {"publish": lambda self, e: None})()
    strategy_params = {
        k: v
        for k, v in config.__dict__.items()
        if k
        not in (
            "initial_cash",
            "start_date",
            "end_date",
            "assets",
            "data_source",
            "notification",
            "live_poll_interval",
            "strategy",
        )
        and k
        in {
            p["name"]
            for p in (StrategyRegistry.get(config.strategy) or {}).get("params", [])
        }
    }
    strategy = StrategyRegistry.create(
        config.strategy, bus_placeholder, **strategy_params
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
