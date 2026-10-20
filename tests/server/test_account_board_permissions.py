from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.config import AccountBoardPermissionsConfig, ServerConfig
from server.contracts.http.settings_models import BoardBuyPermissionsUpdate
from server.routes.settings import create_router
from server.services.account.account_board_permissions import (
    BOARD_PERMISSION_SOURCE,
    entry_board_policy_blocker,
    entry_board_policy_symbols,
    freeze_entry_board_policy,
    resolve_board_buy_permissions,
    validate_entry_board_policy,
)
from server.services.market.hours import get_shanghai_now


def _review(
    reviewed_at: str, *, chinext: str = "enabled", star: str = "disabled"
) -> AccountBoardPermissionsConfig:
    return AccountBoardPermissionsConfig(
        reviewed_at=reviewed_at,
        reviewed_by="local_user",
        source=BOARD_PERMISSION_SOURCE,
        boards={"chinext": chinext, "star": star},
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


def test_frozen_entry_mask_is_explicit_and_star_never_silently_enabled():
    unknown = freeze_entry_board_policy(ServerConfig(), "2026-09-24")
    assert unknown["allowed_boards"] == ["main"]
    assert entry_board_policy_blocker(unknown, {}, decision_date="2026-09-24") is None
    config = ServerConfig(
        account_board_permissions=_review("2026-09-24T01:00:00+00:00", star="enabled")
    )
    frozen = freeze_entry_board_policy(config, "2026-09-24")
    assert frozen["allowed_boards"] == ["chinext", "main"]
    assert entry_board_policy_symbols(
        frozen, ["600000", "000001", "300001", "688001", "920001"]
    ) == {"600000", "000001", "300001"}
    assert frozen["excluded_boards"]["star"] == "unsupported_trade_unit"
    current = resolve_board_buy_permissions(config, "2026-09-24")
    assert (
        entry_board_policy_blocker(frozen, current, decision_date="2026-09-24") is None
    )
    for changed in (
        {**current, "resolved_for_date": "2026-09-23"},
        {**current, "evidence_fingerprint": None},
        {**current, "boards": {"chinext": "disabled"}},
    ):
        assert entry_board_policy_blocker(frozen, changed, decision_date="2026-09-24")
    renewed = ServerConfig(
        account_board_permissions=_review("2026-10-23T01:00:00+00:00")
    )
    assert (
        entry_board_policy_blocker(
            frozen,
            resolve_board_buy_permissions(renewed, "2026-10-24"),
            decision_date="2026-10-24",
        )
        is None
    )
    modified = deepcopy(frozen)
    modified["allowed_boards"].append("star")
    import pytest

    with pytest.raises(ValueError, match="entry_board_policy_invalid"):
        validate_entry_board_policy(modified)


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
