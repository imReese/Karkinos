from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.persistence.financial_facts_valuation import (
    VALUATION_PUBLICATION_ATTEMPT_CONTROL_KEY,
    VALUATION_PUBLICATION_CONTROL_KEY,
)
from server.projections.portfolio_quotes import current_valuation_snapshot

pytestmark = pytest.mark.unit


def _command(
    *,
    symbol: str,
    run_id: str | None,
    price: float = 10.5,
) -> QuoteIngestionCommand:
    return QuoteIngestionCommand(
        symbol=symbol,
        asset_type="stock",
        price=price,
        quote_timestamp="2026-09-04T10:00:00+08:00",
        volume=1000.0,
        previous_close=10.0,
        previous_close_date="2026-09-03",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="live",
        quote_status="live",
        captured_at="2026-09-04T10:00:01+08:00",
        captured_reason="test",
        fetch_run_id=run_id,
        display_name=f"Asset {symbol}",
        provider_symbol=symbol,
        source="fixture",
        daily_close_price=10.0,
        daily_close_date="2026-09-03",
        daily_close_source="reported_previous_close",
    )


def _create_run(db: AppDatabase, run_id: str) -> None:
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at="2026-09-04T10:00:00+08:00",
        trigger="test",
        status="running",
        provider="fixture",
        asset_type="stock",
        symbol_count=1,
        metadata={"requested_symbols": ["FAIL"]},
    )


def test_successful_valuation_publication_records_latest_attempt(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.persist_quote_ingestion_sync(_command(symbol="600001", run_id=None))

    publication = db.get_runtime_control_sync(VALUATION_PUBLICATION_CONTROL_KEY)
    attempt = db.get_runtime_control_sync(VALUATION_PUBLICATION_ATTEMPT_CONTROL_KEY)
    assert publication is not None and publication["status"] == "ready"
    assert attempt is not None and attempt["status"] == "success"
    assert attempt["snapshot_id"] == publication["snapshot_id"]
    assert attempt["as_of"] == publication["as_of"]


def test_failed_quote_publication_preserves_readable_last_good(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_command(symbol="600001", run_id=None))
    publication_before = db.get_runtime_control_sync(VALUATION_PUBLICATION_CONTROL_KEY)
    current_before = current_valuation_snapshot(SimpleNamespace(db=db))
    assert publication_before is not None and publication_before["status"] == "ready"

    run_id = "quote-run-fault-after-ready"
    _create_run(db, run_id)
    db.persist_quote_ingestion_sync(_command(symbol="FAIL", run_id=run_id, price=11.0))
    with sqlite3.connect(db.path) as conn:
        conn.execute("""
            CREATE TRIGGER fail_quote_metadata_publication_after_ready
            BEFORE INSERT ON instrument_metadata
            WHEN NEW.symbol = 'FAIL'
            BEGIN
                SELECT RAISE(ABORT, 'injected quote publication fault');
            END
            """)
        conn.commit()

    finished = db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at="2026-09-04T10:01:00+08:00",
        status="success",
        success_count=1,
        failure_count=0,
    )

    assert finished is not None and finished["status"] == "failed"
    assert db.get_latest_quote_sync("FAIL", "stock") is None
    assert db.get_runtime_control_sync(VALUATION_PUBLICATION_CONTROL_KEY) == (
        publication_before
    )
    attempt = db.get_runtime_control_sync(VALUATION_PUBLICATION_ATTEMPT_CONTROL_KEY)
    assert attempt == {
        "status": "failed",
        "reason": "quote_batch_publication_failed",
        "error_type": "IntegrityError",
        "quote_fetch_run_id": run_id,
        "quote_fetch_run_status": "failed",
    }
    current_after = current_valuation_snapshot(SimpleNamespace(db=db))
    assert current_after["snapshot_id"] == current_before["snapshot_id"]
