"""MyQuant — 个人量化交易系统入口。"""

from __future__ import annotations

import os
from datetime import datetime

# 触发所有策略注册
from analytics.report import generate_report
from backtest.engine import BacktestEngine
from server.bootstrap import build_strategy, create_runtime_context, load_runtime_config


def main() -> None:
    """主入口：加载配置 → 拉取真实数据 → 多资产回测 → 输出报告。"""
    config = load_runtime_config()
    runtime = create_runtime_context(config)
    manager = runtime.data_manager

    start = datetime.strptime(config.start_date, "%Y-%m-%d")
    end = datetime.strptime(config.end_date, "%Y-%m-%d")

    # 遍历资产配置，拉取数据 + 创建标的
    data_handlers = {}
    for sym, ac in runtime.watchlist:
        print(f"拉取数据: {sym} ({ac.value}) ...")
        handler = manager.get_bars(
            sym,
            start=start,
            end=end,
            asset_class=ac,
        )
        data_handlers[sym] = handler

        print(f"  → {handler.total_bars} 根K线")

    if not runtime.instruments:
        print("未配置任何标的，退出。")
        return

    # 创建策略（使用注册表）
    bus_placeholder = type("FakeBus", (), {"publish": lambda self, e: None})()
    strategy = build_strategy(config, bus_placeholder)

    # 创建并运行回测引擎
    engine = BacktestEngine(
        strategy=strategy,
        instruments=runtime.instruments,
        data_handlers=data_handlers,
        initial_cash=config.initial_cash,
    )

    result = engine.run()

    # 生成报告
    report = generate_report(result)
    print(report)


if __name__ == "__main__":
    main()
