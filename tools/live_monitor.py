"""Standalone live signal monitor CLI.

This is a legacy standalone monitor for local signal notifications. The Web
service uses `server.scheduler.TradingScheduler` for live monitoring and quote
fetch auditing.
"""

from __future__ import annotations

import argparse
import time

from core.event_bus import EventBus
from core.events import SignalEvent
from data.live import LiveDataFeed
from notification.notifier import build_notifier, format_signal_message
from server.bootstrap import build_strategy, create_runtime_context, load_runtime_config


def main(argv: list[str] | None = None) -> None:
    """Run the standalone live signal loop."""
    parser = argparse.ArgumentParser(
        description="Run the legacy standalone Karkinos live signal monitor."
    )
    parser.parse_args(argv)

    config = load_runtime_config()
    runtime = create_runtime_context(config)
    event_bus = EventBus()
    source = runtime.sources.get(config.data_source, runtime.sources["akshare"])
    feed = LiveDataFeed(source, event_bus)
    watchlist = runtime.watchlist

    if not watchlist:
        print("未配置任何标的，退出。")
        return

    notifier = build_notifier(config.notification)
    strategy = build_strategy(config, event_bus)
    strategy.on_init([sym for sym, _ in watchlist])

    def on_signal(event: SignalEvent) -> None:
        direction = "买入" if event.target_weight > 0 else "卖出"
        asset_class = "stock"
        for sym, candidate in watchlist:
            if sym == event.symbol:
                asset_class = candidate.value
                break

        message = format_signal_message(
            symbol=str(event.symbol),
            direction=direction,
            target_weight=float(event.target_weight),
            price=float(event.price) if event.price else None,
            strategy_id=event.strategy_id,
            asset_class=asset_class,
            timestamp=str(event.timestamp),
        )
        notifier.send(title=f"Karkinos 信号: {event.symbol}", message=message)

    event_bus.subscribe(SignalEvent, on_signal)

    print(f"Karkinos 独立实时监控启动，关注 {len(watchlist)} 个标的")
    print(f"轮询间隔: {config.live_poll_interval}s")
    print("Web 服务实时路径请使用 python -m server 或 scripts/start_server.sh")
    print("按 Ctrl+C 退出\n")

    try:
        while True:
            events = feed.poll_all(watchlist)
            if events:
                for market_event in events:
                    strategy.on_data(market_event)
                event_bus.drain()
            time.sleep(config.live_poll_interval)
    except KeyboardInterrupt:
        print("\n实时监控已停止。")


if __name__ == "__main__":
    main()
