"""TelegramNotifier — 通过 Telegram Bot API 推送。"""

from __future__ import annotations

import logging
from urllib.request import Request, urlopen

from notification.notifier import Notifier

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

        text = f"*{title}*\n\n{message}"
        url = (
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            f"?chat_id={self.chat_id}&text={text}&parse_mode=Markdown"
        )
        try:
            req = Request(url)
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    logger.error("Telegram 推送失败: HTTP %d", resp.status)
        except Exception:
            logger.exception("Telegram 推送异常")
