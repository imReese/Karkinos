"""WeChatNotifier — 通过 Server酱 (ServerChan) 推送。"""

from __future__ import annotations

import json
import logging
from urllib.request import Request, urlopen

from notification.base import Notifier

logger = logging.getLogger(__name__)


class WeChatNotifier(Notifier):
    """通过 Server酱 (ServerChan) 推送微信通知。"""

    def __init__(self, sendkey: str) -> None:
        self.sendkey = sendkey

    def send(self, title: str, message: str) -> None:
        if not self.sendkey:
            logger.warning("Server酱 sendkey 未配置，跳过推送")
            return

        try:
            req = Request(
                f"https://sctapi.ftqq.com/{self.sendkey}.send",
                data=json.dumps({"title": title, "desp": message}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    raise ValueError("notification_http_failure")
                payload = json.loads(resp.read())
                if (
                    not isinstance(payload, dict)
                    or type(payload.get("code")) is not int
                    or payload["code"] != 0
                ):
                    raise ValueError("notification_provider_failure")
        except Exception:
            logger.error("WeChat notification delivery failed")
            raise RuntimeError("WeChat notification delivery failed") from None
