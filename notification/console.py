"""ConsoleNotifier — 控制台输出通知。"""

from __future__ import annotations

from notification.notifier import Notifier


class ConsoleNotifier(Notifier):
    """控制台通知（默认，无需配置）。"""

    def send(self, title: str, message: str) -> None:
        print(f"\n{'=' * 40}")
        print(f"  {title}")
        print(f"{'=' * 40}")
        print(message)
        print(f"{'=' * 40}\n")
