"""WeChatNotifier — 通过 Server酱 (ServerChan) 推送。"""

from __future__ import annotations

import logging
from urllib.request import Request, urlopen

from notification.notifier import Notifier

logger = logging.getLogger(__name__)


class WeChatNotifier(Notifier):
    """通过 Server酱 (ServerChan) 推送微信通知。"""

    def __init__(self, sendkey: str) -> None:
        self.sendkey = sendkey

    def send(self, title: str, message: str) -> None:
        if not self.sendkey:
            logger.warning("Server酱 sendkey 未配置，跳过推送")
            return

        url = f"https://sctapi.ftqq.com/{self.sendkey}.send"
        import json

        data = json.dumps({"title": title, "desp": message}).encode("utf-8")
        req = Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    logger.error("Server酱推送失败: HTTP %d", resp.status)
        except Exception:
            logger.exception("Server酱推送异常")
