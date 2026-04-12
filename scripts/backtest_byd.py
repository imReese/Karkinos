"""拉取比亚迪(002594)自上市以来全部日线，并运行所有注册策略回测对比。"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

# 触发所有策略注册
import strategy.examples  # noqa: F401
from analytics.metrics import AnnualizedReturn, MaxDrawdown, SharpeRatio
from backtest.engine import BacktestEngine
from config import BacktestConfig
from core.types import AssetClass, Symbol
from data.manager import DataManager, build_sources
from data.store import DataStore
from strategy.registry import StrategyRegistry

SYMBOL = Symbol("002594")
START = datetime(2011, 6, 1)  # 比亚迪 2011-06-30 上市，稍早一点确保覆盖
END = datetime.now()
INITIAL_CASH = Decimal("100000")


def main() -> None:
    # 1. 读取配置获取 tushare_token
    config = BacktestConfig.from_json("config.json")

    # 2. 构建数据源
    sources = build_sources(
        data_source=config.data_source,
        tushare_token=os.environ.get("TUSHARE_TOKEN") or config.tushare_token,
    )

    manager = DataManager(sources, store=DataStore("data/store"))

    # 3. 拉取比亚迪日线数据
    print(f"拉取数据: {SYMBOL} (stock) {START.date()} ~ {END.date()} ...")
    handler = manager.get_bars(
        SYMBOL,
        start=START,
        end=END,
        asset_class=AssetClass.STOCK,
    )
    print(f"  -> {handler.total_bars} 根K线")

    instrument = DataManager.get_instrument(SYMBOL, AssetClass.STOCK)

    # 4. 遍历所有注册策略回测
    strategy_names = StrategyRegistry.list_strategies()
    print(f"\n共 {len(strategy_names)} 个策略: {', '.join(strategy_names)}\n")

    results: list[dict] = []

    for name in strategy_names:
        reg = StrategyRegistry.get(name)
        if reg is None:
            continue

        # 为每次回测创建新的 handler（迭代器只能消费一次）
        data_handler = manager.get_bars(
            SYMBOL,
            start=START,
            end=END,
            asset_class=AssetClass.STOCK,
        )

        # 占位 event_bus — BacktestEngine 会用内部 bus 覆盖
        bus_placeholder = type("FakeBus", (), {"publish": lambda self, e: None})()

        # 只传该策略声明的参数（使用默认值即可）
        strategy = StrategyRegistry.create(name, bus_placeholder)

        engine = BacktestEngine(
            strategy=strategy,
            instruments={SYMBOL: instrument},
            data_handlers={SYMBOL: data_handler},
            initial_cash=INITIAL_CASH,
        )

        result = engine.run()

        equities = [float(e) for _, e in result.equity_curve]
        # 计算日收益率（与 generate_report 一致）
        returns = [
            Decimal(str((equities[i] - equities[i - 1]) / equities[i - 1]))
            for i in range(1, len(equities))
            if equities[i - 1] != 0
        ]

        total_return = result.total_return  # Decimal ratio, e.g. 0.5 = 50%
        ann_return = (
            AnnualizedReturn.calculate(equities) if len(equities) > 1 else Decimal(0)
        )
        sharpe = SharpeRatio.calculate(returns) if returns else Decimal(0)
        max_dd = MaxDrawdown.calculate(equities) if len(equities) > 1 else Decimal(0)

        results.append(
            {
                "strategy": name,
                "total_return": total_return,
                "annualized_return": ann_return,
                "sharpe": sharpe,
                "max_drawdown": max_dd,
                "final_equity": result.final_equity,
            }
        )

        print(f"  [{name}] done")

    # 5. 打印对比表格
    print("\n" + "=" * 80)
    print(f"比亚迪(002594) 多策略回测对比  ({START.date()} ~ {END.date()})")
    print(f"初始资金: {INITIAL_CASH}")
    print("=" * 80)
    print(
        f"{'策略':<22} {'总收益%':>10} {'年化%':>10} {'夏普':>10} {'最大回撤%':>10} {'终值':>14}"
    )
    print("-" * 80)
    for r in results:
        print(
            f"{r['strategy']:<22} "
            f"{float(r['total_return']) * 100:>9.2f}% "
            f"{float(r['annualized_return']) * 100:>9.2f}% "
            f"{float(r['sharpe']):>10.4f} "
            f"{float(r['max_drawdown']) * 100:>9.2f}% "
            f"{float(r['final_equity']):>14.2f}"
        )
    print("=" * 80)


if __name__ == "__main__":
    main()
