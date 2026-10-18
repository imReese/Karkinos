"""测试通知模块。"""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from notification.console import ConsoleNotifier
from notification.notifier import (
    build_notifier,
    format_signal_message,
    notification_configuration_status,
)
from notification.telegram import TelegramNotifier
from notification.wechat import WeChatNotifier

_ENVIRONMENT = {
    "KARKINOS_TELEGRAM_BOT_TOKEN": "fixture-bot-token",
    "KARKINOS_TELEGRAM_CHAT_ID": "fixture-chat",
    "KARKINOS_WECHAT_SENDKEY": "fixture-sendkey",
}


@pytest.mark.parametrize("kind", ["telegram", "wechat"])
def test_configured_notifier_posts_signal_as_encoded_plain_text(monkeypatch, kind):
    title = "Karkinos 信号: 510300 *_[] & + #"
    message = format_signal_message(
        symbol="510300",
        direction="买入",
        target_weight=0.25,
        price=4.05,
        strategy_id="dual_ma",
        asset_class="fund",
        timestamp="2026-10-18 09:35:00",
    )
    requests = []

    def send(request, *, timeout):
        requests.append(request)
        assert timeout == 10
        payload = {"ok": True} if kind == "telegram" else {"code": 0}
        return nullcontext(
            SimpleNamespace(status=200, read=lambda: json.dumps(payload).encode())
        )

    monkeypatch.setattr(f"notification.{kind}.urlopen", send)
    notifier = build_notifier({"type": kind}, environ=_ENVIRONMENT)
    assert notifier.send(title, message) is None

    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "POST"
    assert urlsplit(request.full_url).query == ""
    if kind == "telegram":
        assert request.get_header("Content-type") == (
            "application/x-www-form-urlencoded"
        )
        assert parse_qs(request.data.decode("utf-8")) == {
            "chat_id": ["fixture-chat"],
            "text": [f"{title}\n\n{message}"],
        }
    else:
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data) == {"title": title, "desp": message}


@pytest.mark.parametrize("kind", ["telegram", "wechat"])
@pytest.mark.parametrize(
    "failure",
    [
        "transport",
        "http_status",
        "provider",
        "invalid_json",
        "missing_status",
        "wrong_status_type",
    ],
)
def test_configured_notifier_propagates_only_safe_delivery_failure(
    monkeypatch, caplog, kind, failure
):
    private_error = "https://provider/fixture-bot-token/fixture-sendkey: private-body"

    def send(request, *, timeout):
        if failure == "transport":
            raise URLError(private_error)
        payload = {"ok": True} if kind == "telegram" else {"code": 0}
        if failure == "provider":
            payload = (
                {"ok": False, "description": private_error}
                if kind == "telegram"
                else {"code": 40001, "message": private_error}
            )
        elif failure == "missing_status":
            payload = {}
        elif failure == "wrong_status_type":
            payload = {"ok": 1} if kind == "telegram" else {"code": False}
        body = (
            b"not json" if failure == "invalid_json" else json.dumps(payload).encode()
        )
        return nullcontext(
            SimpleNamespace(
                status=503 if failure == "http_status" else 200,
                read=lambda: body,
            )
        )

    monkeypatch.setattr(f"notification.{kind}.urlopen", send)
    notifier = build_notifier({"type": kind}, environ=_ENVIRONMENT)
    label = "Telegram" if kind == "telegram" else "WeChat"
    with pytest.raises(
        RuntimeError, match=f"^{label} notification delivery failed$"
    ) as exc:
        notifier.send("测试通知", "private-body")

    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True
    assert "fixture-bot-token" not in caplog.text
    assert "fixture-sendkey" not in caplog.text
    assert "private-body" not in caplog.text


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
