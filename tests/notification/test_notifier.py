"""测试通知模块。"""

from __future__ import annotations

from notification.console import ConsoleNotifier
from notification.notifier import (
    build_notifier,
    format_signal_message,
    notification_configuration_status,
)
from notification.telegram import TelegramNotifier
from notification.wechat import WeChatNotifier


class TestConsoleNotifier:
    """ConsoleNotifier 测试。"""

    def test_send_prints_to_console(self, capsys):
        notifier = ConsoleNotifier()
        notifier.send("Test Title", "Test Message")

        captured = capsys.readouterr()
        assert "Test Title" in captured.out
        assert "Test Message" in captured.out


class TestTelegramNotifier:
    """TelegramNotifier 测试。"""

    def test_send_skips_when_no_token(self):
        """缺少 token 时跳过推送。"""
        notifier = TelegramNotifier(bot_token="", chat_id="")
        # 不应抛异常
        notifier.send("Title", "Message")


class TestWeChatNotifier:
    """WeChatNotifier 测试。"""

    def test_send_skips_when_no_sendkey(self):
        """缺少 sendkey 时跳过推送。"""
        notifier = WeChatNotifier(sendkey="")
        # 不应抛异常
        notifier.send("Title", "Message")


class TestBuildNotifier:
    """build_notifier 工厂测试。"""

    def test_default_console(self):
        notifier = build_notifier({})
        assert isinstance(notifier, ConsoleNotifier)

    def test_console_type(self):
        notifier = build_notifier({"type": "console"})
        assert isinstance(notifier, ConsoleNotifier)

    def test_telegram_type(self):
        notifier = build_notifier(
            {"type": "telegram"},
            environ={
                "KARKINOS_TELEGRAM_BOT_TOKEN": "test",
                "KARKINOS_TELEGRAM_CHAT_ID": "123",
            },
        )
        assert isinstance(notifier, TelegramNotifier)
        assert notifier.bot_token == "test"
        assert notifier.chat_id == "123"

    def test_wechat_type(self):
        notifier = build_notifier(
            {"type": "wechat"},
            environ={"KARKINOS_WECHAT_SENDKEY": "test_key"},
        )
        assert isinstance(notifier, WeChatNotifier)
        assert notifier.sendkey == "test_key"

    def test_public_status_reports_only_type_and_configuration_state(self):
        status = notification_configuration_status(
            {"type": "telegram", "telegram_bot_token": "must-be-ignored"},
            environ={
                "KARKINOS_TELEGRAM_BOT_TOKEN": "environment-token",
                "KARKINOS_TELEGRAM_CHAT_ID": "environment-chat",
            },
        )

        assert status == {"type": "telegram", "configured": True}
        assert "environment-token" not in repr(status)
        assert "must-be-ignored" not in repr(status)


class TestFormatSignalMessage:
    """format_signal_message 测试。"""

    def test_format_buy_signal(self):
        msg = format_signal_message(
            symbol="600519",
            direction="买入",
            target_weight=1.0,
            price=1850.0,
            strategy_id="dual_ma",
            asset_class="stock",
        )
        assert "600519" in msg
        assert "买入" in msg
        assert "100%" in msg
        assert "1850.00" in msg
        assert "dual_ma" in msg
        assert "A股" in msg

    def test_format_sell_signal(self):
        msg = format_signal_message(
            symbol="510300",
            direction="卖出",
            target_weight=0.0,
            price=4.05,
            strategy_id="dual_ma",
            asset_class="etf",
        )
        assert "510300" in msg
        assert "卖出" in msg
        assert "0%" in msg
        assert "ETF" in msg

    def test_format_gold_signal(self):
        msg = format_signal_message(
            symbol="Au99.99",
            direction="买入",
            target_weight=0.5,
            price=600.0,
            strategy_id="dual_ma",
            asset_class="gold",
        )
        assert "Au99.99" in msg
        assert "黄金" in msg
        assert "50%" in msg

    def test_format_no_price(self):
        msg = format_signal_message(
            symbol="600519",
            direction="买入",
            target_weight=1.0,
            price=None,
            strategy_id="dual_ma",
        )
        assert "N/A" in msg
