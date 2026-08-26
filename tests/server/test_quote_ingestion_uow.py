from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest

from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.projections.portfolio_quotes import current_valuation_snapshot
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
        captured_at="2026-08-26T00:30:00Z",
        fetch_run_id=None,
    )

    assert command.quote_timestamp == "2026-08-26T10:30:00+08:00"
    assert command.captured_at == "2026-08-26T00:30:00Z"


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
    assert _table_count(db.path, "daily_close_snapshots") == 1
    assert _table_count(db.path, "instrument_metadata") == 1
    assert _table_count(db.path, "valuation_snapshots") == 1
    publication = db.get_runtime_control_sync("valuation_snapshot_publication")
    assert publication is not None
    assert publication["status"] == "ready"
    assert publication["snapshot_id"] == metadata["valuation_snapshot_id"]
    assert publication["valuation_snapshot_status"] == "complete"
    assert publication["quote_fetch_run_id"] == run_id
    current = _assert_published_snapshot_replays(db)
    assert current["quotes"][0]["asset_type"] == "stock"
    assert current["quotes"][0]["quote_timestamp"] == command.quote_timestamp
    assert current["quotes"][0]["valuation_baseline_status"] == "complete"
    assert current["quotes"][0]["previous_close_date"] == "2026-08-25"


def test_single_quote_publication_is_replayable_after_commit(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    result = db.persist_quote_ingestion_sync(_command(run_id=None))

    assert result["symbol"] == "600001"
    current = _assert_published_snapshot_replays(db)
    assert current["quotes"][0]["price"] == 10.5
    assert current["quotes"][0]["valuation_baseline_status"] == "complete"


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
        timestamp="2026-08-26T11:00:00+08:00",
        run_id=None,
    )
    db.persist_quote_ingestion_sync(newer)
    run_id = "quote-run-older-observation"
    _create_run(db, run_id)
    db.persist_quote_ingestion_sync(
        _command(
            price=11.0,
            timestamp="2026-08-26T10:00:00+08:00",
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
