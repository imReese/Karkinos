"""Notifier — 通知抽象基类。"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping

from server.config_contract import SUPPORTED_NOTIFICATION_TYPES


class Notifier(ABC):
    """通知推送抽象基类。"""

    @abstractmethod
    def send(self, title: str, message: str) -> None:
        """发送通知。"""


def _notification_type(config: Mapping[str, object]) -> str:
    notification_type = str(config.get("type") or "console").strip().lower()
    if notification_type not in SUPPORTED_NOTIFICATION_TYPES:
        raise ValueError(f"Unsupported notification type: {notification_type}")
    return notification_type


def notification_configuration_status(
    config: Mapping[str, object],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str | bool]:
    """Return public notification metadata without exposing edge credentials."""
    environment = os.environ if environ is None else environ
    notification_type = _notification_type(config)
    if notification_type == "telegram":
        configured = bool(
            str(environment.get("KARKINOS_TELEGRAM_BOT_TOKEN") or "").strip()
            and str(environment.get("KARKINOS_TELEGRAM_CHAT_ID") or "").strip()
        )
    elif notification_type == "wechat":
        configured = bool(str(environment.get("KARKINOS_WECHAT_SENDKEY") or "").strip())
    else:
        configured = True
    return {"type": notification_type, "configured": configured}


def build_notifier(
    config: Mapping[str, object],
    *,
    environ: Mapping[str, str] | None = None,
) -> Notifier:
    """根据配置创建通知器。"""
    environment = os.environ if environ is None else environ
    notif_type = _notification_type(config)

    if notif_type == "telegram":
        from notification.telegram import TelegramNotifier

        return TelegramNotifier(
            bot_token=str(environment.get("KARKINOS_TELEGRAM_BOT_TOKEN") or "").strip(),
            chat_id=str(environment.get("KARKINOS_TELEGRAM_CHAT_ID") or "").strip(),
        )
    elif notif_type == "wechat":
        from notification.wechat import WeChatNotifier

        return WeChatNotifier(
            sendkey=str(environment.get("KARKINOS_WECHAT_SENDKEY") or "").strip()
        )
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
        f"Karkinos 信号提醒\n"
        f"标的: {symbol} [{asset_label}]\n"
        f"方向: {direction}\n"
        f"目标权重: {weight_pct}\n"
        f"当前价: {price_str}\n"
        f"策略: {strategy_id}\n"
        f"时间: {ts}"
    )
