from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.config import AccountBoardPermissionsConfig, ServerConfig
from server.contracts.http.settings_models import BoardBuyPermissionsUpdate
from server.routes.settings import create_router
from server.services.account_board_permissions import (
    BOARD_PERMISSION_SOURCE,
    resolve_board_buy_permissions,
)
from server.services.market_hours import get_shanghai_now


def _review(
    reviewed_at: str, *, chinext: str = "enabled"
) -> AccountBoardPermissionsConfig:
    return AccountBoardPermissionsConfig(
        reviewed_at=reviewed_at,
        reviewed_by="local_user",
        source=BOARD_PERMISSION_SOURCE,
        boards={"chinext": chinext, "star": "disabled"},
    )


def test_board_permission_review_is_dated_and_unknown_fails_closed() -> None:
    day = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)
    decision_date = "2026-09-24"
    assert resolve_board_buy_permissions(ServerConfig(), decision_date)["status"] == (
        "unavailable"
    )

    config = ServerConfig(account_board_permissions=_review(day.isoformat()))
    current = resolve_board_buy_permissions(config, decision_date)
    assert current["status"] == "current"
    assert current["boards"] == {
        "chinext": "enabled",
        "star": "disabled",
        "beijing": "unknown",
    }
    assert current["evidence_fingerprint"].startswith("sha256:")
    assert resolve_board_buy_permissions(config, "2026-09-23")["status"] == (
        "unavailable"
    )
    assert resolve_board_buy_permissions(config, "2026-10-25")["boards"] == {
        "chinext": "unknown",
        "star": "unknown",
        "beijing": "unknown",
    }


def test_board_permission_review_persists_and_reloads_locally(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"strategy":"dual_ma"}', encoding="utf-8")
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(config_path))
    state = SimpleNamespace(config=ServerConfig())
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    router = create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/settings/board-buy-permissions"
        and "PUT" in route.methods
    )
    response = asyncio.run(
        endpoint(
            BoardBuyPermissionsUpdate(
                reviewed_by="local_user",
                boards={"chinext": "disabled", "star": "unknown"},
                confirmation="I_checked_these_board_permissions_in_my_broker_account",
            )
        )
    )

    assert response["status"] == "current"
    assert response["boards"]["chinext"] == "disabled"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["strategy"] == "dual_ma"
    assert persisted["account_board_permissions"]["source"] == (BOARD_PERMISSION_SOURCE)
    reloaded = ServerConfig.from_json(config_path)
    assert (
        resolve_board_buy_permissions(reloaded, get_shanghai_now().date().isoformat())[
            "evidence_fingerprint"
        ]
        == response["evidence_fingerprint"]
    )


def test_expired_review_never_qualifies_buy() -> None:
    reviewed_at = datetime.now(timezone.utc) - timedelta(days=40)
    config = ServerConfig(account_board_permissions=_review(reviewed_at.isoformat()))
    current = resolve_board_buy_permissions(
        config, get_shanghai_now().date().isoformat()
    )
    assert current["status"] == "unavailable"
    assert current["boards"]["chinext"] == "unknown"
