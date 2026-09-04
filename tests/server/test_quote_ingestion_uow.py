from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.persistence.financial_fact_event_payloads import quote_instant_storage_key
from server.projections.portfolio_quotes import current_valuation_snapshot
from server.projections.valuation_snapshot import (
    build_current_valuation_snapshot,
    select_authoritative_quote_rows,
)
from server.services.market_quote_ingestion import build_quote_ingestion_command

pytestmark = pytest.mark.unit


def _command(
    *,
    symbol: str = "600001",
    price: float = 10.5,
    timestamp: str = "2026-08-26T10:00:00+08:00",
    run_id: str | None,
) -> QuoteIngestionCommand:
    return QuoteIngestionCommand(
        symbol=symbol,
        asset_type="stock",
        price=price,
        quote_timestamp=timestamp,
        volume=1000.0,
        previous_close=10.0,
        previous_close_date="2026-08-25",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="live",
        quote_status="live",
        captured_at="2026-08-26T10:00:01+08:00",
        captured_reason="test",
        fetch_run_id=run_id,
        display_name=f"Asset {symbol}",
        provider_symbol=symbol,
        source="fixture",
        daily_close_price=10.0,
        daily_close_date="2026-08-25",
        daily_close_source="reported_previous_close",
    )


def _create_run(db: AppDatabase, run_id: str) -> None:
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-08-26T10:00:00+08:00",
        trigger="test",
        status="running",
        provider="fixture",
        asset_type="stock",
        symbol_count=1,
    )


def _table_count(path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _event_count(path, event_type: str, entity_id: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*) FROM event_log
                WHERE event_type = ? AND entity_id = ?
                """,
                (event_type, entity_id),
            ).fetchone()[0]
        )


def _insert_legacy_quote_snapshots(
    db: AppDatabase,
    observations: tuple[tuple[float, str], ...],
) -> None:
    with sqlite3.connect(db.path) as conn:
        conn.executemany(
            """
            INSERT INTO quote_snapshots (
                symbol, asset_class, price, volume, timestamp, created_at,
                quote_status, quote_instant_utc
            ) VALUES ('600001', 'stock', ?, NULL, ?, ?, 'live', ?)
            """,
            (
                (
                    price,
                    timestamp,
                    timestamp,
                    quote_instant_storage_key(timestamp),
                )
                for price, timestamp in observations
            ),
        )
        conn.commit()


def _assert_published_snapshot_replays(db: AppDatabase) -> dict:
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "ready"
    current = current_valuation_snapshot(SimpleNamespace(db=db))
    stored = db.get_valuation_snapshot_sync(publication["snapshot_id"])
    assert stored is not None
    assert current["snapshot_id"] == publication["snapshot_id"]
    assert current["quote_set_fingerprint"] == stored["quote_set_fingerprint"]
    assert current["ledger_fingerprint"] == stored["ledger_fingerprint"]
    assert current["quotes"] == json.loads(stored["quotes_json"])
    assert current["metadata"] == json.loads(stored["metadata_json"])
    return current


@pytest.mark.parametrize(
    "changes",
    [
        {"price": 0.0},
        {"price": float("nan")},
        {"volume": -1.0},
        {"turnover": float("inf")},
        {"previous_close": -1.0},
        {"change_percent": float("nan")},
        {"daily_close_price": 0.0},
    ],
)
def test_quote_ingestion_contract_rejects_invalid_financial_values(
    changes: dict[str, float],
) -> None:
    with pytest.raises(ValueError):
        replace(_command(run_id=None), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"quote_timestamp": "not-a-date"},
        {"captured_at": "not-a-date"},
    ],
)
def test_quote_ingestion_contract_rejects_invalid_timestamps(
    changes: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="must be an ISO datetime"):
        replace(_command(run_id=None), **changes)


def test_quote_ingestion_contract_rejects_quote_after_captured_at() -> None:
    with pytest.raises(ValueError, match="authoritative capture time"):
        replace(
            _command(run_id=None),
            quote_timestamp="2026-08-26T10:00:02+08:00",
            captured_at="2026-08-26T10:00:01+08:00",
        )


def test_quote_ingestion_uses_persisted_ingestion_time_when_capture_is_missing(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    authoritative_now = datetime(
        2026,
        8,
        26,
        10,
        0,
        1,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    db._financial_facts._now = lambda tz=None: (
        authoritative_now if tz is None else authoritative_now.astimezone(tz)
    )
    command = replace(
        _command(run_id=None),
        quote_timestamp="2026-08-26T10:00:02+08:00",
        captured_at=None,
    )

    with pytest.raises(ValueError, match="authoritative capture time"):
        db.persist_quote_ingestion_sync(command)

    assert _table_count(db.path, "quote_snapshots") == 0
    assert _table_count(db.path, "valuation_snapshots") == 0


def test_provider_time_only_quote_binds_to_shanghai_capture_date() -> None:
    command = build_quote_ingestion_command(
        symbol="600001",
        asset_type="stock",
        snapshot={"price": 10.5, "timestamp": "10:30:00"},
        quote_source="fixture",
        provider_name="fixture",
        provider_status="live",
        quote_status="live",
        captured_reason="test",
        captured_at="2026-08-26T03:00:00Z",
        fetch_run_id=None,
    )

    assert command.quote_timestamp == "2026-08-26T10:30:00+08:00"
    assert command.captured_at == "2026-08-26T03:00:00Z"


def test_quote_ingestion_marks_legacy_fund_compatibility_identity() -> None:
    command = replace(_command(run_id=None), asset_type="fund")

    assert command.asset_type == "open_end_fund"
    assert command.identity_provenance == "legacy_fund_compatibility"
    assert command.metadata["identity_provenance"] == "legacy_fund_compatibility"
    assert command.valuation_row()["instrument_type"] == "open_end_fund"
    assert command.valuation_row()["asset_class"] == "fund"


def test_staged_quote_batch_is_invisible_until_atomic_publication(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "quote-run-visible-only-after-publish"
    command = _command(run_id=run_id)
    _create_run(db, run_id)

    first = db.persist_quote_ingestion_sync(command)
    replay = db.persist_quote_ingestion_sync(command)

    assert replay["id"] == first["id"]
    assert db.get_latest_quote_sync(command.symbol, command.asset_type) is None
    assert _table_count(db.path, "quote_snapshots") == 0
    assert _table_count(db.path, "valuation_snapshots") == 0

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-08-26T10:00:02+08:00",
        status="success",
        success_count=1,
        failure_count=0,
        metadata={"requested_symbols": [command.symbol]},
    )

    assert finished is not None
    assert finished["status"] == "success"
    metadata = json.loads(finished["metadata_json"])
    assert metadata["valuation_snapshot_status"] == "complete"
    assert metadata["valuation_snapshot_id"].startswith("valuation-")
    latest = db.get_latest_quote_sync(command.symbol, command.asset_type)
    assert latest is not None
    assert latest["fetch_run_id"] == run_id
    assert _table_count(db.path, "quote_snapshots") == 1
    assert _table_count(db.path, "daily_close_snapshots_v2") == 1
    assert _table_count(db.path, "instrument_metadata") == 1
    assert _table_count(db.path, "valuation_snapshots") == 1
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "ready"
    assert publication["snapshot_id"] == metadata["valuation_snapshot_id"]
    assert publication["valuation_snapshot_status"] == "complete"
    assert publication["quote_fetch_run_id"] == run_id
    current = _assert_published_snapshot_replays(db)
    assert latest["asset_type"] == "stock"
    assert latest["quote_timestamp"] == command.quote_timestamp
    assert latest["previous_close"] == 10.0
    assert json.loads(latest["metadata_json"])["previous_close_date"] == "2026-08-25"
    assert current["status"] == "complete"
    assert current["quotes"] == []
    assert current["metadata"]["current_position_count"] == 0
    assert [lane["status"] for lane in current["valuation_lanes"]] == [
        "not_applicable",
        "not_applicable",
    ]


@pytest.mark.parametrize(
    ("status", "stage_quote", "success_count", "failure_count"),
    [
        ("partial_success", True, 1, 1),
        ("failed", False, 0, 1),
    ],
)
def test_incomplete_quote_run_never_publishes_ready_valuation(
    tmp_path,
    status: str,
    stage_quote: bool,
    success_count: int,
    failure_count: int,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = f"quote-run-{status}"
    _create_run(db, run_id)
    if stage_quote:
        db.persist_quote_ingestion_sync(_command(run_id=run_id))

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-08-26T10:00:02+08:00",
        status=status,
        success_count=success_count,
        failure_count=failure_count,
        metadata={"requested_symbols": ["600001", "600002"]},
    )

    assert finished is not None
    assert finished["status"] == status
    metadata = json.loads(finished["metadata_json"])
    assert "valuation_snapshot_id" not in metadata
    assert "valuation_snapshot_status" not in metadata
    assert _table_count(db.path, "quote_snapshots") == 0
    assert _table_count(db.path, "latest_quotes") == 0
    assert _table_count(db.path, "valuation_snapshots") == 0
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication == {
        "status": "failed",
        "quote_fetch_run_id": run_id,
        "quote_fetch_run_status": status,
        "reason": "quote_fetch_run_not_fully_successful",
    }
    with pytest.raises(HTTPException) as blocked:
        current_valuation_snapshot(SimpleNamespace(db=db))
    assert blocked.value.status_code == 503


def test_incomplete_quote_run_preserves_existing_ready_valuation(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_command(run_id=None))
    publication_before = db.get_runtime_control_sync("valuation_snapshot_publication")
    current_before = current_valuation_snapshot(SimpleNamespace(db=db))

    run_id = "quote-run-partial-after-ready"
    _create_run(db, run_id)
    db.persist_quote_ingestion_sync(_command(symbol="600002", run_id=run_id))
    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-08-26T10:00:02+08:00",
        status="partial_success",
        success_count=1,
        failure_count=1,
        metadata={"requested_symbols": ["600001", "600002"]},
    )

    assert finished is not None
    assert finished["status"] == "partial_success"
    metadata = json.loads(finished["metadata_json"])
    assert "valuation_snapshot_id" not in metadata
    assert "valuation_snapshot_status" not in metadata
    assert _table_count(db.path, "quote_ingestion_items") == 1
    assert db.get_latest_quote_sync("600002", asset_type="stock") is None
    assert _table_count(db.path, "quote_snapshots") == 1
    assert _table_count(db.path, "valuation_snapshots") == 1
    assert db.get_runtime_control_sync("valuation_snapshot_publication") == (
        publication_before
    )
    current_after = current_valuation_snapshot(SimpleNamespace(db=db))
    assert current_after["snapshot_id"] == current_before["snapshot_id"]


def test_identical_successful_quote_run_completion_retry_is_idempotent(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "quote-run-success-retry"
    command = _command(run_id=run_id)
    _create_run(db, run_id)
    db.persist_quote_ingestion_sync(command)
    completion = {
        "run_id": run_id,
        "finished_at": "2026-08-26T10:00:02+08:00",
        "status": "success",
        "success_count": 1,
        "failure_count": 0,
        "cache_hit_count": 0,
        "error_message": None,
        "metadata": {"requested_symbols": [command.symbol]},
    }

    first = db.finish_quote_fetch_run(**completion)
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    completed_events = _event_count(db.path, "task_run.completed", run_id)
    retry = db.finish_quote_fetch_run(**completion)

    assert retry == first
    assert retry is not None and retry["status"] == "success"
    assert db.get_runtime_control_sync("valuation_snapshot_publication") == publication
    assert publication is not None and publication["status"] == "ready"
    assert _event_count(db.path, "task_run.completed", run_id) == completed_events == 1
    assert _table_count(db.path, "quote_snapshots") == 1
    assert _table_count(db.path, "valuation_snapshots") == 1

    with pytest.raises(ValueError, match="completion conflict"):
        db.finish_quote_fetch_run(
            **{**completion, "metadata": {"requested_symbols": ["DIFFERENT"]}}
        )
    assert db.get_quote_fetch_run(run_id)["status"] == "success"
    assert db.get_runtime_control_sync("valuation_snapshot_publication") == publication


def test_single_quote_publication_is_replayable_after_commit(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    result = db.persist_quote_ingestion_sync(_command(run_id=None))

    assert result["symbol"] == "600001"
    latest = db.get_latest_quote_sync("600001", "stock")
    assert latest is not None
    assert latest["price"] == 10.5
    current = _assert_published_snapshot_replays(db)
    assert current["quotes"] == []
    assert current["metadata"]["current_position_count"] == 0


def test_same_timestamp_conflicting_financial_facts_fail_closed(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    original = _command(price=10.5, run_id=None)
    db.persist_quote_ingestion_sync(original)
    original_publication = db.get_runtime_control_sync("valuation_snapshot_publication")

    with pytest.raises(ValueError, match="conflict at the same timestamp"):
        db.persist_quote_ingestion_sync(_command(price=10.6, run_id=None))

    latest = db.get_latest_quote_sync(original.symbol, original.asset_type)
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert latest is not None and latest["price"] == original.price
    assert publication == original_publication
    assert _table_count(db.path, "quote_snapshots") == 1
    _assert_published_snapshot_replays(db)


@pytest.mark.parametrize(
    "changes",
    [
        {"price": 10.6},
        {"quote_source": "other-source"},
        {"provider_status": "partial"},
        {"quote_status": "stale"},
        {"stale_reason": "provider_error"},
        {"nav_date": "2026-08-25"},
    ],
)
def test_same_timestamp_authority_conflicts_are_rejected(
    tmp_path,
    changes: dict[str, object],
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    original = _command(run_id=None)
    db.persist_quote_ingestion_sync(original)

    with pytest.raises(ValueError, match="conflict at the same timestamp"):
        db.persist_quote_ingestion_sync(replace(original, **changes))

    latest = db.get_latest_quote_sync(original.symbol, original.asset_type)
    assert latest is not None
    assert latest["price"] == original.price
    assert latest["quote_source"] == original.quote_source
    assert latest["provider_status"] == original.provider_status
    assert latest["quote_status"] == original.quote_status
    assert _table_count(db.path, "quote_snapshots") == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"price": 10.6},
        {"quote_source": "other-source"},
        {"provider_status": "partial"},
        {"quote_status": "stale"},
        {"stale_reason": "provider_error"},
        {"error": "provider timeout"},
    ],
)
def test_canonical_quote_selection_rejects_conflicts_independent_of_input_order(
    changes: dict[str, object],
) -> None:
    original = {
        "id": 1,
        "symbol": "600001",
        "asset_class": "stock",
        "timestamp": "2026-08-26T10:00:00+08:00",
        "price": 10.5,
        "quote_source": "fixture",
        "provider_status": "live",
        "quote_status": "live",
        "stale_reason": None,
        "error": None,
    }
    conflicting = {**original, "id": 2, **changes}

    for rows in ([original, conflicting], [conflicting, original]):
        with pytest.raises(ValueError, match="conflict at the same timestamp"):
            select_authoritative_quote_rows(rows)


def test_canonical_quote_selection_ignores_superseded_legacy_conflict() -> None:
    original = {
        "id": 1,
        "symbol": "600001",
        "asset_class": "stock",
        "timestamp": "2026-06-16",
        "price": 10.5,
        "volume": 1000.0,
    }
    conflicting = {
        **original,
        "id": 2,
        "price": 10.6,
        "volume": 1200.0,
    }
    newest = {
        **original,
        "id": 3,
        "timestamp": "2026-08-27T15:00:00+08:00",
        "price": 11.0,
        "volume": 1500.0,
    }

    for rows in (
        [original, conflicting, newest],
        [newest, conflicting, original],
    ):
        assert select_authoritative_quote_rows(rows) == [newest]


def test_canonical_quote_selection_rejects_latest_conflict_across_timezones() -> None:
    original = {
        "id": 1,
        "symbol": "600001",
        "asset_class": "stock",
        "timestamp": "2026-08-27T15:00:00+08:00",
        "price": 11.0,
    }
    conflicting = {
        **original,
        "id": 2,
        "timestamp": "2026-08-27T07:00:00Z",
        "price": 11.1,
    }

    with pytest.raises(ValueError, match="conflict at the same timestamp"):
        select_authoritative_quote_rows([original, conflicting])


def test_startup_quote_reconciliation_keeps_latest_timezone_conflict_blocking(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _insert_legacy_quote_snapshots(
        db,
        (
            (11.0, "2026-08-27T15:00:00+08:00"),
            (11.1, "2026-08-27T07:00:00Z"),
        ),
    )

    with pytest.raises(ValueError, match="conflict at the newest timestamp"):
        db.init_sync()
    with pytest.raises(RuntimeError, match="checkpoint does not cover audit history"):
        build_current_valuation_snapshot(db, persist=False)


def test_startup_quote_reconciliation_excludes_unheld_superseded_conflict(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _insert_legacy_quote_snapshots(
        db,
        (
            (10.5, "2026-06-16T15:00:00+08:00"),
            (10.6, "2026-06-16T07:00:00Z"),
            (11.0, "2026-08-27T15:00:00+08:00"),
        ),
    )
    db.init_sync()

    snapshot = build_current_valuation_snapshot(db, persist=False)
    latest = db.get_latest_quote_sync("600001", "stock")

    assert latest is not None
    assert latest["price"] == 11.0
    assert snapshot["quotes"] == []
    assert snapshot["metadata"]["current_position_count"] == 0


def test_quote_staging_rejects_conflicting_idempotency_replay(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "quote-run-idempotency-conflict"
    _create_run(db, run_id)
    db.persist_quote_ingestion_sync(_command(run_id=run_id))

    with pytest.raises(ValueError, match="idempotency conflict"):
        db.persist_quote_ingestion_sync(_command(run_id=run_id, price=11.0))


def test_quote_publication_fault_rolls_back_every_authoritative_fact(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    run_id = "quote-run-fault-rollback"
    command = _command(symbol="FAIL", run_id=run_id)
    _create_run(db, run_id)
    db.persist_quote_ingestion_sync(command)
    before = {
        table: _table_count(db.path, table)
        for table in (
            "quote_snapshots",
            "latest_quotes",
            "daily_close_snapshots",
            "instrument_metadata",
            "valuation_snapshots",
        )
    }
    with sqlite3.connect(db.path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_quote_metadata_publication
            BEFORE INSERT ON instrument_metadata
            WHEN NEW.symbol = 'FAIL'
            BEGIN
                SELECT RAISE(ABORT, 'injected quote publication fault');
            END
            """)
        conn.commit()

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-08-26T10:00:02+08:00",
        status="success",
        success_count=1,
        failure_count=0,
    )

    assert finished is not None
    assert finished["status"] == "failed"
    assert db.get_latest_quote_sync(command.symbol, command.asset_type) is None
    assert {table: _table_count(db.path, table) for table in before} == before
    with sqlite3.connect(db.path) as conn:
        quote_events = conn.execute(
            "SELECT COUNT(*) FROM event_log WHERE event_type LIKE 'market.quote.%'"
        ).fetchone()[0]
    assert quote_events == 0
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "failed"
    assert publication["quote_fetch_run_id"] == run_id
    assert _table_count(db.path, "quote_ingestion_items") == 1


def test_older_batch_observation_cannot_regress_latest_projection(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    newer = _command(
        price=12.0,
        timestamp="2026-08-26T10:00:00+08:00",
        run_id=None,
    )
    db.persist_quote_ingestion_sync(newer)
    run_id = "quote-run-older-observation"
    _create_run(db, run_id)
    db.persist_quote_ingestion_sync(
        _command(
            price=11.0,
            timestamp="2026-08-26T09:00:00+08:00",
            run_id=run_id,
        )
    )

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-08-26T11:01:00+08:00",
        status="success",
        success_count=1,
        failure_count=0,
    )

    assert finished is not None and finished["status"] == "success"
    latest = db.get_latest_quote_sync(newer.symbol, newer.asset_type)
    assert latest is not None
    assert latest["price"] == 12.0
    assert latest["quote_timestamp"] == newer.quote_timestamp
