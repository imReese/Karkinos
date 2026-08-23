"""Focused contracts for low-authority SQLite repositories."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from server.db import AppDatabase
from server.persistence.automation_alerts import AutomationAlertRepository
from server.persistence.backtest_results import BacktestResultsRepository
from server.persistence.event_log import EventLogRepository, insert_event_sync
from server.persistence.instrument_metadata import InstrumentMetadataRepository
from server.persistence.research_notes import ResearchNotesRepository
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


def test_automation_alert_repository_preserves_storage_and_ordering_contract(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = AutomationAlertRepository(database.path)

    info = repository.upsert_alert(
        alert_key="info:one",
        severity="info",
        category="operations",
        title="Info",
        detail="Informational evidence",
        source="unit",
    )
    warning_one = repository.upsert_alert(
        alert_key="warning:one",
        severity="warning",
        category="operations",
        title="Warning one",
        detail="First warning",
        source="unit",
    )
    warning_two = repository.upsert_alert(
        alert_key="warning:two",
        severity="warning",
        category="operations",
        title="Warning two",
        detail="Second warning",
        source="unit",
    )
    critical = repository.upsert_alert(
        alert_key="critical:one",
        severity="critical",
        category="trading_control",
        title="Critical",
        detail="Requires operator review",
        source="unit",
        source_ref="critical-source",
        payload={"z": "中文", "a": 1},
    )

    with sqlite3.connect(database.path) as conn:
        conn.execute(
            "UPDATE automation_alerts SET updated_at = ? WHERE id IN (?, ?)",
            (
                "2026-08-24T09:30:00",
                warning_one["id"],
                warning_two["id"],
            ),
        )
        conn.commit()

    rows = repository.list_alerts()
    assert [row["id"] for row in rows] == [
        critical["id"],
        warning_two["id"],
        warning_one["id"],
        info["id"],
    ]
    assert critical["payload_json"] == '{"a": 1, "z": "中文"}'
    assert datetime.fromisoformat(critical["created_at"]).tzinfo is not None
    assert repository.list_alerts(limit=2, offset=1) == rows[1:3]

    acknowledged = repository.acknowledge_alert(
        alert_id=critical["id"],
        actor="operator-review",
    )
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_by"] == "operator-review"
    assert datetime.fromisoformat(acknowledged["acknowledged_at"]).tzinfo is None

    rescanned = repository.upsert_alert(
        alert_key="critical:one",
        severity="critical",
        category="trading_control",
        title="Critical updated",
        detail="Still requires operator review",
        source="unit",
        source_ref="critical-source-updated",
        payload={"phase": "rescanned"},
    )
    assert rescanned["id"] == critical["id"]
    assert rescanned["created_at"] == critical["created_at"]
    assert rescanned["status"] == "acknowledged"
    assert rescanned["acknowledged_at"] == acknowledged["acknowledged_at"]
    assert rescanned["acknowledged_by"] == "operator-review"
    assert rescanned["source_ref"] == "critical-source-updated"
    assert repository.list_alerts(status="acknowledged") == [rescanned]

    with pytest.raises(KeyError, match="automation alert not found: 999999"):
        repository.acknowledge_alert(alert_id=999999)


def test_app_database_automation_alert_facades_delegate_to_repository(
    tmp_path,
    monkeypatch,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    expected = {"id": 11, "alert_key": "test:alert"}
    upsert_alert = Mock(return_value=expected)
    list_alerts = Mock(return_value=[expected])
    acknowledge_alert = Mock(return_value={**expected, "status": "acknowledged"})
    monkeypatch.setattr(database._automation_alerts, "upsert_alert", upsert_alert)
    monkeypatch.setattr(database._automation_alerts, "list_alerts", list_alerts)
    monkeypatch.setattr(
        database._automation_alerts,
        "acknowledge_alert",
        acknowledge_alert,
    )

    assert (
        database.upsert_automation_alert_sync(
            alert_key="test:alert",
            severity="warning",
            category="operations",
            title="Test alert",
            detail="Requires review",
            source="unit",
            payload={"safe": True},
        )
        == expected
    )
    assert database.list_automation_alerts_sync(
        status="open",
        limit=5,
        offset=1,
    ) == [expected]
    assert database.acknowledge_automation_alert_sync(
        alert_id=11,
        actor="operator-review",
    ) == {**expected, "status": "acknowledged"}

    upsert_alert.assert_called_once_with(
        alert_key="test:alert",
        severity="warning",
        category="operations",
        title="Test alert",
        detail="Requires review",
        source="unit",
        source_ref=None,
        payload={"safe": True},
    )
    list_alerts.assert_called_once_with(status="open", limit=5, offset=1)
    acknowledge_alert.assert_called_once_with(
        alert_id=11,
        actor="operator-review",
    )


def test_instrument_metadata_repository_preserves_storage_contract(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = InstrumentMetadataRepository(database.path)

    created = repository.upsert_metadata(
        symbol=" 600001 ",
        asset_type="stock",
        display_name=" 示例能源 ",
        provider_symbol="600001.SH",
        exchange="SSE",
        provider_name="fixture",
        fetched_at="2026-08-22T09:30:00+08:00",
        metadata={"currency": "人民币", "lot_size": 100},
    )
    updated = repository.upsert_metadata(
        symbol="600001",
        asset_type="stock",
        display_name="示例能源股份",
        provider_symbol="600001.SH",
        exchange="SSE",
        provider_name="fixture",
        fetched_at="2026-08-23T09:30:00+08:00",
        metadata='{"raw":true}',
    )
    repository.upsert_metadata(
        symbol="600001",
        asset_type="fund",
        display_name="同代码示例基金",
        fetched_at="2026-08-21T09:30:00+08:00",
        metadata=None,
    )

    assert created is not None
    assert updated is not None
    assert updated["id"] == created["id"]
    assert updated["created_at"] == created["created_at"]
    assert updated["symbol"] == "600001"
    assert updated["display_name"] == "示例能源股份"
    assert updated["metadata_json"] == '{"raw":true}'
    assert repository.get_metadata("600001", "fund")["display_name"] == (
        "同代码示例基金"
    )
    assert repository.get_metadata("600001")["asset_type"] == "stock"
    assert [row["asset_type"] for row in repository.list_metadata()] == [
        "stock",
        "fund",
    ]
    assert repository.upsert_metadata(symbol=" ", display_name="missing") is None
    assert repository.upsert_metadata(symbol="600002", display_name=" ") is None


def test_event_log_repository_preserves_payload_and_query_contract(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = EventLogRepository(database.path)

    first_id = repository.append(
        event_type="test.event",
        timestamp="2026-08-22T09:30:00+08:00",
        entity_type="instrument",
        entity_id="600001",
        source="unit",
        source_ref="fixture-1",
        payload={"label": "中文", "amount": Decimal("1.20")},
    )
    second_id = repository.append(
        event_type="test.event",
        timestamp="2026-08-23T09:30:00+08:00",
        entity_type="instrument",
        entity_id="600001",
        source="unit",
        payload='{"raw": true}',
    )

    assert first_id > 0
    assert second_id > first_id
    rows = repository.list_events(
        event_type="test.event",
        entity_type="instrument",
        entity_id="600001",
        source="unit",
    )
    assert [row["id"] for row in rows] == [second_id, first_id]
    assert rows[0]["payload_json"] == '{"raw": true}'
    assert rows[1]["payload_json"] == '{"label":"中文","amount":"1.20"}'
    assert repository.list_events(event_type="test.event", limit=1, offset=1) == [
        rows[1]
    ]


def test_insert_event_sync_uses_caller_transaction(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = EventLogRepository(database.path)

    with sqlite3.connect(database.path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = insert_event_sync(
            conn,
            event_type="test.rolled_back",
            timestamp="2026-08-23T09:30:00+08:00",
            entity_type=None,
            entity_id=None,
            source="unit",
            source_ref=None,
            payload=None,
        )
        assert cursor.lastrowid is not None
        assert (
            conn.execute(
                "SELECT payload_json FROM event_log WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()[0]
            == "{}"
        )
        conn.rollback()

    assert repository.list_events(event_type="test.rolled_back") == []


def test_app_database_instrument_and_event_facades_delegate_to_repositories(
    tmp_path,
    monkeypatch,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    expected_instrument = {"symbol": "600001"}
    expected_event = {"id": 7, "event_type": "test.event"}
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        database._instrument_metadata,
        "upsert_metadata",
        lambda **payload: calls.append(("instrument_upsert", payload))
        or expected_instrument,
    )
    monkeypatch.setattr(
        database._instrument_metadata,
        "get_metadata",
        lambda symbol, asset_type=None: calls.append(
            ("instrument_get", (symbol, asset_type))
        )
        or expected_instrument,
    )
    monkeypatch.setattr(
        database._instrument_metadata,
        "list_metadata",
        lambda: calls.append(("instrument_list", None)) or [expected_instrument],
    )
    monkeypatch.setattr(
        database._event_log,
        "append",
        lambda **payload: calls.append(("event_append", payload)) or 7,
    )
    monkeypatch.setattr(
        database._event_log,
        "list_events",
        lambda **filters: calls.append(("event_list", filters)) or [expected_event],
    )

    assert (
        database.upsert_instrument_metadata_sync(
            symbol="600001",
            display_name="示例能源",
            metadata={"lot_size": 100},
        )
        == expected_instrument
    )
    assert database.get_instrument_metadata_sync("600001", "stock") == (
        expected_instrument
    )
    assert database.list_instrument_metadata_sync() == [expected_instrument]
    assert (
        database.append_event_sync(
            event_type="test.event",
            timestamp="2026-08-23T09:30:00+08:00",
            payload={"safe": True},
        )
        == 7
    )
    assert database.list_events_sync(event_type="test.event", limit=5) == [
        expected_event
    ]

    assert calls == [
        (
            "instrument_upsert",
            {
                "symbol": "600001",
                "asset_type": "stock",
                "display_name": "示例能源",
                "provider_symbol": None,
                "exchange": None,
                "market": None,
                "provider_name": None,
                "source": "provider",
                "fetched_at": None,
                "metadata": {"lot_size": 100},
            },
        ),
        ("instrument_get", ("600001", "stock")),
        ("instrument_list", None),
        (
            "event_append",
            {
                "event_type": "test.event",
                "timestamp": "2026-08-23T09:30:00+08:00",
                "entity_type": None,
                "entity_id": None,
                "source": "app",
                "source_ref": None,
                "payload": {"safe": True},
            },
        ),
        (
            "event_list",
            {
                "event_type": "test.event",
                "entity_type": None,
                "entity_id": None,
                "source": None,
                "limit": 5,
                "offset": 0,
            },
        ),
    ]


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


def test_backtest_results_repository_preserves_columns_order_and_json(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = BacktestResultsRepository(database.path)

    first_id = asyncio.run(
        repository.save(
            config_json='{"strategy":"first"}',
            initial_cash=100000.0,
            final_equity=112000.0,
            total_return=0.12,
            sharpe=1.3,
            max_dd=0.08,
            equity_curve_json='[{"equity":100000.0}]',
            annual_return=0.11,
            sortino=1.7,
            win_rate=0.56,
            duration_days=252,
            metrics_json='{"calmar":1.5}',
            cost_summary_json='{"commission":12.3}',
        )
    )
    second_id = asyncio.run(
        repository.save(
            config_json='{"strategy":"second"}',
            initial_cash=100000.0,
            final_equity=101000.0,
            total_return=0.01,
            sharpe=0.2,
            max_dd=0.03,
            equity_curve_json="[]",
        )
    )

    summaries = asyncio.run(repository.list_results())
    detail = asyncio.run(repository.get_result(first_id))

    assert [row["id"] for row in summaries] == [second_id, first_id]
    assert set(summaries[0]) == {
        "id",
        "created_at",
        "config_json",
        "initial_cash",
        "final_equity",
        "total_return",
        "sharpe",
        "max_drawdown",
        "equity_curve_json",
        "metrics_json",
        "cost_summary_json",
    }
    assert detail is not None
    assert detail["config_json"] == '{"strategy":"first"}'
    assert detail["sortino"] == 1.7
    assert detail["win_rate"] == 0.56
    assert detail["duration_days"] == 252
    assert detail["metrics_json"] == '{"calmar":1.5}'
    assert detail["cost_summary_json"] == '{"commission":12.3}'
    assert "annual_return" not in detail
    assert asyncio.run(repository.get_result(999999)) is None


def test_research_notes_repository_preserves_queries_mutations_and_event(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = ResearchNotesRepository(database.path)
    events = EventLogRepository(database.path)

    first_id = asyncio.run(
        repository.add(
            symbol="600519",
            asset_class="stock",
            entry_kind="earnings",
            title="业绩跟踪",
            content="毛利率改善",
            priority="high",
            event_date="2026-08-20",
        )
    )
    second_id = asyncio.run(
        repository.add(
            symbol="510300",
            asset_class="etf",
            entry_kind="note",
            title="指数观察",
            content="保持只读观察",
        )
    )

    async_filtered = asyncio.run(
        repository.list_notes(
            symbol="600519",
            entry_kind="earnings",
            priority="high",
            event_date_from="2026-08-01",
            event_date_to="2026-08-31",
            limit=5,
            offset=0,
        )
    )
    sync_filtered = repository.list_notes_sync(
        symbol="600519",
        entry_kind="earnings",
        priority="high",
        event_date_from="2026-08-01",
        event_date_to="2026-08-31",
        limit=5,
        offset=0,
    )

    assert async_filtered == sync_filtered
    assert [row["id"] for row in async_filtered] == [first_id]
    assert repository.list_notes_sync(limit=1, offset=0)[0]["id"] == second_id
    assert repository.list_notes_sync(limit=1, offset=1)[0]["id"] == first_id
    event_rows = events.list_events(
        event_type="research.note.created",
        entity_type="instrument",
        entity_id="600519",
    )
    assert len(event_rows) == 1
    assert event_rows[0]["source"] == "market_research_notes"
    assert event_rows[0]["source_ref"] == str(first_id)
    assert event_rows[0]["payload_json"] == (
        '{"note_id":1,"symbol":"600519","asset_class":"stock",'
        '"entry_kind":"earnings","title":"业绩跟踪","content":"毛利率改善",'
        '"priority":"high","event_date":"2026-08-20"}'
    )

    assert (
        asyncio.run(
            repository.update(
                note_id=first_id,
                entry_kind="follow_up",
                title="业绩复核",
                content="等待下一份持久化证据",
                priority="normal",
                event_date=None,
            )
        )
        is True
    )
    updated = repository.list_notes_sync(symbol="600519")[0]
    assert updated["entry_kind"] == "follow_up"
    assert updated["title"] == "业绩复核"
    assert updated["content"] == "等待下一份持久化证据"
    assert updated["priority"] == "normal"
    assert updated["event_date"] is None
    assert (
        asyncio.run(
            repository.update(
                note_id=999999,
                entry_kind="note",
                title="missing",
                content="missing",
                priority="normal",
            )
        )
        is False
    )
    assert asyncio.run(repository.delete(second_id)) is True
    assert asyncio.run(repository.delete(second_id)) is False


def test_research_note_event_failure_rolls_back_note_insert(
    tmp_path,
    monkeypatch,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    repository = ResearchNotesRepository(database.path)

    def fail_event_insert(*_args, **_kwargs):
        raise RuntimeError("event insert failed")

    monkeypatch.setattr(
        "server.persistence.research_notes.insert_event_sync",
        fail_event_insert,
    )

    with pytest.raises(RuntimeError, match="event insert failed"):
        asyncio.run(
            repository.add(
                symbol="600519",
                asset_class="stock",
                entry_kind="note",
                title="必须原子回滚",
                content="不得留下孤立研究记录",
            )
        )

    assert repository.list_notes_sync() == []
    assert EventLogRepository(database.path).list_events() == []


def test_app_database_backtest_result_facade_preserves_async_contract(
    tmp_path,
    monkeypatch,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    save = AsyncMock(return_value=17)
    list_results = AsyncMock(return_value=[{"id": 17}])
    get_result = AsyncMock(return_value={"id": 17, "sortino": 1.8})
    monkeypatch.setattr(database._backtest_results, "save", save)
    monkeypatch.setattr(database._backtest_results, "list_results", list_results)
    monkeypatch.setattr(database._backtest_results, "get_result", get_result)

    saved_id = asyncio.run(
        database.save_backtest_result(
            config_json="{}",
            initial_cash=100000.0,
            final_equity=110000.0,
            total_return=0.1,
            sharpe=1.2,
            max_dd=0.08,
            equity_curve_json="[]",
        )
    )

    assert saved_id == 17
    assert asyncio.run(database.get_backtest_results()) == [{"id": 17}]
    assert asyncio.run(database.get_backtest_result(17)) == {
        "id": 17,
        "sortino": 1.8,
    }
    save.assert_awaited_once_with(
        config_json="{}",
        initial_cash=100000.0,
        final_equity=110000.0,
        total_return=0.1,
        sharpe=1.2,
        max_dd=0.08,
        equity_curve_json="[]",
        annual_return=0.0,
        sortino=0.0,
        win_rate=0.0,
        duration_days=0,
        metrics_json="{}",
        cost_summary_json="{}",
    )
    list_results.assert_awaited_once_with()
    get_result.assert_awaited_once_with(17)


def test_app_database_research_note_facade_preserves_async_and_sync_contracts(
    tmp_path,
    monkeypatch,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    add = AsyncMock(return_value=23)
    list_notes = AsyncMock(return_value=[{"id": 23}])
    list_notes_sync = Mock(return_value=[{"id": 23}])
    delete = AsyncMock(return_value=True)
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(database._research_notes, "add", add)
    monkeypatch.setattr(database._research_notes, "list_notes", list_notes)
    monkeypatch.setattr(database._research_notes, "list_notes_sync", list_notes_sync)
    monkeypatch.setattr(database._research_notes, "delete", delete)
    monkeypatch.setattr(database._research_notes, "update", update)

    assert (
        asyncio.run(
            database.add_research_note(
                symbol="600519",
                asset_class="stock",
                entry_kind="note",
                title="研究记录",
                content="只记录证据",
            )
        )
        == 23
    )
    filters = {
        "symbol": "600519",
        "entry_kind": "note",
        "priority": "high",
        "event_date_from": "2026-08-01",
        "event_date_to": "2026-08-31",
        "limit": 5,
        "offset": 1,
    }
    assert asyncio.run(database.get_research_notes(**filters)) == [{"id": 23}]
    assert database.get_research_notes_sync(**filters) == [{"id": 23}]
    assert asyncio.run(database.delete_research_note(23)) is True
    assert (
        asyncio.run(
            database.update_research_note(
                note_id=23,
                entry_kind="follow_up",
                title="研究复核",
                content="等待确认",
                priority="normal",
            )
        )
        is True
    )

    add.assert_awaited_once_with(
        symbol="600519",
        asset_class="stock",
        entry_kind="note",
        title="研究记录",
        content="只记录证据",
        priority="normal",
        event_date=None,
    )
    list_notes.assert_awaited_once_with(**filters)
    list_notes_sync.assert_called_once_with(**filters)
    delete.assert_awaited_once_with(23)
    update.assert_awaited_once_with(
        note_id=23,
        entry_kind="follow_up",
        title="研究复核",
        content="等待确认",
        priority="normal",
        event_date=None,
    )
