"""MyQuant 实时信号监控入口。

盘中轮询行情，策略产生信号后通过微信/Telegram 推送买卖建议。
仅做建议，不自动下单。
"""

from __future__ import annotations

import os
import time

from core.event_bus import EventBus
from core.events import SignalEvent
from data.live import LiveDataFeed
from notification.notifier import build_notifier, format_signal_message
from server.bootstrap import build_strategy, create_runtime_context, load_runtime_config


def main() -> None:
    """实时监控主循环。"""
    config = load_runtime_config()
    runtime = create_runtime_context(config)
    event_bus = EventBus()
    source = runtime.sources.get(config.data_source, runtime.sources["akshare"])
    feed = LiveDataFeed(source, event_bus)
    watchlist = runtime.watchlist

    if not watchlist:
        print("未配置任何标的，退出。")
        return

    # 配置通知
    notifier = build_notifier(config.notification)

    # 创建策略
    strategy = build_strategy(config, event_bus)
    strategy.on_init([sym for sym, _ in watchlist])

    # 订阅 SignalEvent → 推送通知
    def on_signal(event: SignalEvent) -> None:
        direction = "买入" if event.target_weight > 0 else "卖出"
        # 查找 asset_class
        ac_str = "stock"
        for sym, ac in watchlist:
            if sym == event.symbol:
                ac_str = ac.value
                break

        message = format_signal_message(
            symbol=str(event.symbol),
            direction=direction,
            target_weight=float(event.target_weight),
            price=float(event.price) if event.price else None,
            strategy_id=event.strategy_id,
            asset_class=ac_str,
            timestamp=str(event.timestamp),
        )
        notifier.send(title=f"MyQuant 信号: {event.symbol}", message=message)

    event_bus.subscribe(SignalEvent, on_signal)

    # 主循环
    print(f"MyQuant 实时监控启动，关注 {len(watchlist)} 个标的")
    print(f"轮询间隔: {config.live_poll_interval}s")
    print("按 Ctrl+C 退出\n")

    try:
        while True:
            events = feed.poll_all(watchlist)
            if events:
                # 推送行情到策略
                for market_event in events:
                    strategy.on_data(market_event)
                # 处理产生的信号
                event_bus.drain()
            time.sleep(config.live_poll_interval)
    except KeyboardInterrupt:
        print("\n实时监控已停止。")


if __name__ == "__main__":
    main()
