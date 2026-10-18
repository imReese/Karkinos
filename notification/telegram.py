"""TelegramNotifier — 通过 Telegram Bot API 推送。"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from notification.base import Notifier

logger = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """通过 Telegram Bot API 推送通知。"""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, title: str, message: str) -> None:
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram 配置缺失，跳过推送")
            return

        try:
            req = Request(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                data=urlencode(
                    {"chat_id": self.chat_id, "text": f"{title}\n\n{message}"}
                ).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    raise ValueError("notification_http_failure")
                payload = json.loads(resp.read())
                if not isinstance(payload, dict) or payload.get("ok") is not True:
                    raise ValueError("notification_provider_failure")
        except Exception:
            logger.error("Telegram notification delivery failed")
            raise RuntimeError("Telegram notification delivery failed") from None
