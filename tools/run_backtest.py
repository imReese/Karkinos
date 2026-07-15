"""Backtest CLI for Karkinos.

This is a developer/operations tool. The production Web service entry point is
`python -m server` or `./scripts/start_server.sh`.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from analytics.report import generate_report
from backtest.engine import BacktestEngine
from server.bootstrap import (
    build_strategy,
    create_runtime_context,
    load_runtime_config,
    load_selected_runtime_environment_file,
)


def main(argv: list[str] | None = None) -> None:
    """Load runtime config, run a local backtest, and print the report."""
    parser = argparse.ArgumentParser(
        description="Run a local Karkinos backtest from ignored runtime config."
    )
    parser.parse_args(argv)

    load_selected_runtime_environment_file()
    config = load_runtime_config()
    runtime = create_runtime_context(config)
    manager = runtime.data_manager

    start = datetime.strptime(config.start_date, "%Y-%m-%d")
    end = datetime.strptime(config.end_date, "%Y-%m-%d")

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

        print(f"  -> {handler.total_bars} 根K线")

    if not runtime.instruments:
        print("未配置任何标的，退出。")
        return

    bus_placeholder = type("FakeBus", (), {"publish": lambda self, e: None})()
    strategy = build_strategy(config, bus_placeholder)

    engine = BacktestEngine(
        strategy=strategy,
        instruments=runtime.instruments,
        data_handlers=data_handlers,
        initial_cash=config.initial_cash,
    )

    result = engine.run()
    report = generate_report(result)
    print(report)


if __name__ == "__main__":
    main()
