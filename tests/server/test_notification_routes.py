"""Notification probes exercise real adapters without external delivery."""

from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from notification.notifier import build_notifier
from server.routes.settings import create_router


@pytest.mark.parametrize("kind", ["telegram", "wechat"])
@pytest.mark.parametrize(
    "outcome", ["success", "transport", "provider", "invalid_json"]
)
def test_settings_notification_probe_reports_real_adapter_outcome(
    monkeypatch, kind, outcome
):
    environment = {
        "KARKINOS_TELEGRAM_BOT_TOKEN": "fixture-token",
        "KARKINOS_TELEGRAM_CHAT_ID": "fixture-chat",
        "KARKINOS_WECHAT_SENDKEY": "fixture-sendkey",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    calls = []

    def send(request, *, timeout):
        calls.append(request)
        if outcome == "transport":
            raise URLError(
                "https://provider/fixture-token/fixture-sendkey private-body"
            )
        payload = {"ok": True} if kind == "telegram" else {"code": 0}
        if outcome == "provider":
            payload = (
                {"ok": False, "description": "fixture-token private-body"}
                if kind == "telegram"
                else {"code": 40001, "message": "fixture-sendkey private-body"}
            )
        body = (
            b"invalid-json"
            if outcome == "invalid_json"
            else json.dumps(payload).encode()
        )
        return nullcontext(SimpleNamespace(status=200, read=lambda: body))

    monkeypatch.setattr(f"notification.{kind}.urlopen", send)
    state = SimpleNamespace(
        config=SimpleNamespace(notification={"type": kind}),
        notifier=build_notifier({"type": kind}, environ=environment),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    endpoint = next(
        route.endpoint
        for route in create_router().routes
        if route.path == "/api/settings/notification/test"
    )

    response = asyncio.run(endpoint())

    assert len(calls) == 1
    if outcome == "success":
        assert response == {"status": "ok", "message": "Test notification sent"}
    else:
        label = "Telegram" if kind == "telegram" else "WeChat"
        assert response == {
            "status": "error",
            "message": f"{label} notification delivery failed",
        }
