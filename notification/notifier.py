"""Notifier — 通知抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    """通知推送抽象基类。"""

    @abstractmethod
    def send(self, title: str, message: str) -> None:
        """发送通知。"""


def build_notifier(config: dict) -> Notifier:
    """根据配置创建通知器。"""
    notif_type = config.get("type", "console")

    if notif_type == "telegram":
        from notification.telegram import TelegramNotifier

        return TelegramNotifier(
            bot_token=config.get("telegram_bot_token", ""),
            chat_id=config.get("telegram_chat_id", ""),
        )
    elif notif_type == "wechat":
        from notification.wechat import WeChatNotifier

        return WeChatNotifier(sendkey=config.get("wechat_sendkey", ""))
    else:
        from notification.console import ConsoleNotifier

        return ConsoleNotifier()


def format_signal_message(
    symbol: str,
    direction: str,
    target_weight: float,
    price: float | None,
    strategy_id: str,
    asset_class: str = "stock",
    timestamp: str | None = None,
) -> str:
    """格式化信号通知消息。"""
    from datetime import datetime

    asset_names = {
        "stock": "A股",
        "fund": "ETF",
        "gold": "黄金",
        "bond": "债券",
    }
    asset_label = asset_names.get(asset_class, asset_class.upper())
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    weight_pct = f"{target_weight * 100:.0f}%"
    price_str = f"{price:.2f}" if price is not None else "N/A"

    return (
        f"MyQuant 信号提醒\n"
        f"标的: {symbol} [{asset_label}]\n"
        f"方向: {direction}\n"
        f"目标权重: {weight_pct}\n"
        f"当前价: {price_str}\n"
        f"策略: {strategy_id}\n"
        f"时间: {ts}"
    )
