"""Focused contracts for low-authority SQLite repositories."""

from __future__ import annotations

import sqlite3

import pytest

from server.db import AppDatabase
from server.persistence.runtime_controls import RuntimeControlRepository
from server.persistence.watchlist import WatchlistRepository

pytestmark = pytest.mark.unit


def test_watchlist_repository_preserves_upsert_order_and_delete_semantics(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = WatchlistRepository(database.path)

    created = repository.upsert_asset(
        symbol=" 510300 ",
        asset_class=" ETF ",
        display_name="沪深300ETF",
    )
    updated = repository.upsert_asset(
        symbol="510300",
        asset_class="etf",
        display_name="沪深300 ETF",
        source="manual",
    )
    repository.upsert_asset(symbol="600519", display_name="示例股票")

    assert created is not None
    assert updated is not None
    assert updated["id"] == created["id"]
    assert updated["created_at"] == created["created_at"]
    assert updated["asset_class"] == "etf"
    assert updated["display_name"] == "沪深300 ETF"
    assert [row["symbol"] for row in repository.list_assets()] == [
        "510300",
        "600519",
    ]
    assert repository.delete_asset(" 510300 ") is True
    assert repository.delete_asset("510300") is False
    assert repository.delete_asset(" ") is False


def test_watchlist_repository_seed_is_repeatable_without_duplicate_rows(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = WatchlistRepository(database.path)
    assets = {
        "019999": "示例基金",
        "fallback": {
            "provider_code": "600001",
            "asset_class": "STOCK",
            "name": "示例能源",
        },
        "ignored": object(),
    }

    assert repository.seed_from_config(assets) == 2
    first_rows = repository.list_assets()
    assert repository.seed_from_config(assets) == 2
    second_rows = repository.list_assets()

    assert [(row["symbol"], row["display_name"]) for row in second_rows] == [
        ("019999", "示例基金"),
        ("600001", "示例能源"),
    ]
    assert [row["id"] for row in second_rows] == [row["id"] for row in first_rows]
    assert all(row["source"] == "config_migration" for row in second_rows)
    assert repository.upsert_asset(symbol=" ") is None
    assert repository.seed_from_config(None) == 0


def test_runtime_control_repository_overwrites_one_key_without_duplication(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = RuntimeControlRepository(database.path)

    assert repository.get_value("kill_switch") is None
    repository.set_value("kill_switch", {"enabled": False, "note": "人工确认"})
    repository.set_value("kill_switch", {"enabled": True, "reasons": ["owner"]})

    assert repository.get_value("kill_switch") == {
        "enabled": True,
        "reasons": ["owner"],
    }
    with sqlite3.connect(database.path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM runtime_controls WHERE key = ?",
            ("kill_switch",),
        ).fetchone()[0]
    assert count == 1


def test_app_database_methods_delegate_to_focused_repositories(
    tmp_path,
    monkeypatch,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    expected_row = {"symbol": "510300"}
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        database._watchlist,
        "upsert_asset",
        lambda **payload: calls.append(("watchlist_upsert", payload)) or expected_row,
    )
    monkeypatch.setattr(
        database._watchlist,
        "list_assets",
        lambda: calls.append(("watchlist_list", None)) or [expected_row],
    )
    monkeypatch.setattr(
        database._watchlist,
        "delete_asset",
        lambda symbol: calls.append(("watchlist_delete", symbol)) or True,
    )
    monkeypatch.setattr(
        database._watchlist,
        "seed_from_config",
        lambda assets: calls.append(("watchlist_seed", assets)) or 1,
    )
    monkeypatch.setattr(
        database._runtime_controls,
        "set_value",
        lambda key, value: calls.append(("runtime_set", (key, value))),
    )
    monkeypatch.setattr(
        database._runtime_controls,
        "get_value",
        lambda key: calls.append(("runtime_get", key)) or {"enabled": False},
    )

    assert database.upsert_watchlist_asset_sync(symbol="510300") == expected_row
    assert database.list_watchlist_assets_sync() == [expected_row]
    assert database.delete_watchlist_asset_sync("510300") is True
    assert database.seed_watchlist_assets_from_config_sync(["510300"]) == 1
    database.set_runtime_control_sync("kill_switch", {"enabled": False})
    assert database.get_runtime_control_sync("kill_switch") == {"enabled": False}

    assert calls == [
        (
            "watchlist_upsert",
            {
                "symbol": "510300",
                "asset_class": "stock",
                "display_name": None,
                "source": "manual",
            },
        ),
        ("watchlist_list", None),
        ("watchlist_delete", "510300"),
        ("watchlist_seed", ["510300"]),
        ("runtime_set", ("kill_switch", {"enabled": False})),
        ("runtime_get", "kill_switch"),
    ]
