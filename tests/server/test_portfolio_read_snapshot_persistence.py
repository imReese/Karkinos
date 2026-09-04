from __future__ import annotations

import json
import sqlite3
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.store import DataStore
from server.contracts.content_identity import content_fingerprint
from server.dependencies import AppState
from server.projections.portfolio_read_snapshot import PortfolioReadSnapshotRejected
from server.projections.portfolio_read_snapshot_persistence import (
    LEGACY_UNBOUND_MARKET_IDENTITY,
    _ledger_instrument_keys,
    get_or_build_portfolio_read_snapshot,
)
from server.projections.valuation_snapshot import ledger_identity_from_rows


def _ledger_rows() -> list[dict[str, object]]:
    return [
        {
            "id": 2,
            "entry_type": "trade_buy",
            "symbol": "600001",
            "instrument_type": "stock",
            "quantity": 10.0,
            "price": 10.0,
            "timestamp": "2026-08-02T10:00:00+08:00",
        },
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "amount": 1000.0,
            "timestamp": "2026-08-01T09:00:00+08:00",
        },
    ]


class _ReadOnlyDatabase:
    def __init__(self, path: Path, ledger_rows: list[dict[str, object]]) -> None:
        self.path = path
        self.ledger_rows = ledger_rows
        self.calls: Counter[str] = Counter()
        self.matrix_calls: list[dict[str, object]] = []
        self.matrix_price = 11.0
        self.before_matrix_return = None

    def get_all_ledger_entries_sync(self) -> list[dict[str, object]]:
        self.calls["ledger"] += 1
        return deepcopy(self.ledger_rows)

    def get_historical_price_matrix_sync(self, **kwargs):
        self.calls["matrix"] += 1
        self.matrix_calls.append(deepcopy(kwargs))
        if self.before_matrix_return is not None:
            self.before_matrix_return()
        return {
            "600001": [
                {
                    "symbol": "600001",
                    "trade_date": "2026-08-29",
                    "timestamp": "2026-08-29T15:00:00+08:00",
                    "price": self.matrix_price,
                    "source": "fixture",
                    "asset_class": "stock",
                    "generation_id": None,
                }
            ]
        }


def _create_published_valuation(
    path: Path,
    ledger_rows: list[dict[str, object]],
    *,
    persisted_facts_only: bool,
) -> str:
    identity = ledger_identity_from_rows(deepcopy(ledger_rows))
    quotes = [{"symbol": "600001", "price": 11.0}]
    quote_set_fingerprint = content_fingerprint(quotes)
    metadata = {
        "quote_count": 1,
        "current_position_count": 1,
        "valuation_scope_policy": "current_nonzero_positions.v1",
        "valuation_freshness_policy": "expected_session_and_live_ttl.v1",
        "valuation_expected_date": "2026-08-30",
        "current_position_scope_fingerprint": content_fingerprint({"600001": "stock"}),
        "ledger_entry_count": len(ledger_rows),
        "persisted_facts_only": persisted_facts_only,
        "runtime_cache_used": False,
        "provider_fetch_used": False,
        "ingestion_run_ids": [],
    }
    identity_payload = {
        "valuation_policy": "karkinos.persisted_valuation.v5",
        "as_of": "2026-08-30T15:00:00+08:00",
        "trade_date": "2026-08-30",
        "status": "complete",
        "ledger_cutoff_id": identity["ledger_cutoff_id"],
        "ledger_fingerprint": identity["ledger_fingerprint"],
        "quote_set_fingerprint": quote_set_fingerprint,
        "metadata": metadata,
    }
    snapshot_id = f"valuation-{content_fingerprint(identity_payload)}"
    publication = {
        "status": "ready",
        "snapshot_id": snapshot_id,
        "valuation_snapshot_status": "complete",
        "as_of": "2026-08-30T15:00:00+08:00",
    }
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE runtime_controls (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)
        connection.execute("""
            CREATE TABLE valuation_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                as_of TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                valuation_policy TEXT NOT NULL,
                ledger_cutoff_id INTEGER NOT NULL,
                ledger_fingerprint TEXT NOT NULL,
                quote_set_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                quotes_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        connection.execute("""
            CREATE TABLE quote_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                price REAL NOT NULL,
                volume REAL,
                timestamp TEXT NOT NULL,
                quote_source TEXT,
                provider_name TEXT,
                quote_status TEXT,
                stale_reason TEXT,
                provider_status TEXT,
                captured_reason TEXT,
                nav_date TEXT,
                fetch_run_id TEXT,
                created_at TEXT NOT NULL,
                quote_instant_utc TEXT NOT NULL,
                instrument_type TEXT,
                identity_provenance TEXT
            )
            """)
        connection.execute("""
            CREATE TABLE daily_close_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                close_price REAL NOT NULL,
                source TEXT NOT NULL,
                captured_at TEXT NOT NULL
            )
            """)
        connection.execute("""
            CREATE TABLE daily_close_snapshots_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                instrument_type TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                close_price REAL NOT NULL,
                source TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                identity_provenance TEXT NOT NULL,
                UNIQUE(symbol, instrument_type, trade_date)
            )
            """)
        connection.execute(
            "INSERT INTO runtime_controls VALUES (?, ?, ?)",
            (
                "valuation_snapshot_publication",
                json.dumps(publication),
                "2026-08-30T15:00:01+08:00",
            ),
        )
        connection.execute(
            "INSERT INTO valuation_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                "2026-08-30T15:00:00+08:00",
                "2026-08-30",
                "karkinos.persisted_valuation.v5",
                identity["ledger_cutoff_id"],
                identity["ledger_fingerprint"],
                quote_set_fingerprint,
                "complete",
                json.dumps(quotes),
                json.dumps(metadata),
                "2026-08-30T15:00:01+08:00",
            ),
        )
    return snapshot_id


def _state(tmp_path: Path, *, persisted_facts_only: bool = True):
    ledger_rows = _ledger_rows()
    app_path = tmp_path / "app.db"
    snapshot_id = _create_published_valuation(
        app_path,
        ledger_rows,
        persisted_facts_only=persisted_facts_only,
    )
    database = _ReadOnlyDatabase(app_path, ledger_rows)
    database.valuation_snapshot_id = snapshot_id
    state = AppState()
    state.db = database  # type: ignore[assignment]
    return state, database


def _write_bar_revision(path: Path, *, dataset_id: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS bar_meta_v2 (
                symbol TEXT NOT NULL,
                instrument_type TEXT NOT NULL,
                identity_provenance TEXT NOT NULL,
                frequency TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                start_date TEXT,
                end_date TEXT,
                last_updated TEXT NOT NULL,
                PRIMARY KEY (symbol, instrument_type, frequency)
            )
            """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS market_bars_v2 (
                symbol TEXT NOT NULL,
                instrument_type TEXT NOT NULL,
                frequency TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, instrument_type, frequency, timestamp)
            )
            """)
        connection.execute(
            """
            INSERT INTO bar_meta_v2 VALUES (
                '600001', 'stock', 'fixture', '1d', ?, 1,
                '2026-08-29', '2026-08-29', ?
            )
            ON CONFLICT(symbol, instrument_type, frequency) DO UPDATE SET
                dataset_id = excluded.dataset_id,
                last_updated = excluded.last_updated
            """,
            (dataset_id, dataset_id),
        )


def test_cold_build_reads_ledger_and_price_matrix_once_with_exact_identity(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)

    snapshot = get_or_build_portfolio_read_snapshot(state)

    assert database.calls == Counter({"ledger": 1, "matrix": 1})
    assert database.matrix_calls == [
        {
            "instrument_keys": [InstrumentKey("600001", InstrumentType.STOCK)],
            "start_date": "2026-08-01",
            "end_date": "2026-08-30",
            "symbol_batch_size": 400,
        }
    ]
    assert snapshot.identity.valuation_snapshot_id == database.valuation_snapshot_id
    assert snapshot.identity.market_generation_id.startswith("persisted-market:sha256:")
    assert snapshot.identity.market_receipt_fingerprint.startswith("sha256:")
    assert snapshot.identity.market_content_fingerprint.startswith("sha256:")
    assert snapshot.market_evidence_complete is True
    assert snapshot.build_metrics.query_count == 8
    assert snapshot.build_metrics.rows_read == 7
    assert state.portfolio_read_snapshot_service is not None
    assert snapshot.provider_contact_performed is False
    assert snapshot.write_performed is False
    assert snapshot.authorizes_execution is False


def test_ledger_instrument_keys_keep_same_symbol_namespaces_separate() -> None:
    rows = (
        {"symbol": "000777", "instrument_type": "stock"},
        {"symbol": "000777", "instrument_type": "etf"},
        {"symbol": "000777", "asset_class": "fund"},
    )

    assert _ledger_instrument_keys(rows) == [
        InstrumentKey("000777", InstrumentType.ETF),
        InstrumentKey("000777", InstrumentType.OPEN_END_FUND),
        InstrumentKey("000777", InstrumentType.STOCK),
    ]


def test_ledger_instrument_keys_reject_missing_identity_without_quote_fallback() -> (
    None
):
    with pytest.raises(
        PortfolioReadSnapshotRejected,
        match="ledger instrument identity is unavailable",
    ):
        _ledger_instrument_keys(({"symbol": "600001"},))


def test_warm_hit_skips_ledger_and_matrix_payload_reads(tmp_path: Path) -> None:
    state, database = _state(tmp_path)
    first = get_or_build_portfolio_read_snapshot(state)
    before = state.portfolio_read_snapshot_service.metrics()

    second = get_or_build_portfolio_read_snapshot(state)
    after = state.portfolio_read_snapshot_service.metrics()

    assert second is first
    assert database.calls == Counter({"ledger": 1, "matrix": 1})
    assert after.cache_hits == before.cache_hits + 1
    assert after.query_count == before.query_count
    assert after.rows_read == before.rows_read


def test_ledger_drift_is_blocked_before_matrix_read_and_not_cached(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    database.ledger_rows[0]["quantity"] = 11.0

    with pytest.raises(PortfolioReadSnapshotRejected, match="ledger.*fingerprint"):
        get_or_build_portfolio_read_snapshot(state)

    assert database.calls == Counter({"ledger": 1})
    assert state.portfolio_read_snapshot_service.metrics().cache_entries == 0
    assert state.portfolio_read_snapshot_service.metrics().build_failures == 1


def test_legacy_fixture_without_persisted_metadata_stays_explicitly_incomplete(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path, persisted_facts_only=False)

    snapshot = get_or_build_portfolio_read_snapshot(state)

    assert snapshot.identity.market_generation_id == LEGACY_UNBOUND_MARKET_IDENTITY
    assert snapshot.identity.market_receipt_fingerprint == (
        LEGACY_UNBOUND_MARKET_IDENTITY
    )
    assert snapshot.identity.market_content_fingerprint == (
        LEGACY_UNBOUND_MARKET_IDENTITY
    )
    assert snapshot.market_evidence_complete is False
    assert snapshot.build_metrics.query_count == 8
    assert database.matrix_calls[0]["symbol_batch_size"] == 400


def test_historical_bar_revision_invalidates_same_valuation_snapshot(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    _write_bar_revision(tmp_path / "meta.db", dataset_id="dataset-a")

    first = get_or_build_portfolio_read_snapshot(state)
    database.matrix_price = 12.0
    _write_bar_revision(tmp_path / "meta.db", dataset_id="dataset-b")
    second = get_or_build_portfolio_read_snapshot(state)

    assert first.identity.valuation_snapshot_id == second.identity.valuation_snapshot_id
    assert first.identity.market_generation_id != second.identity.market_generation_id
    assert first.price_matrix_rows[0]["price"] == 11.0
    assert second.price_matrix_rows[0]["price"] == 12.0
    assert database.calls == Counter({"ledger": 2, "matrix": 2})
    assert state.portfolio_read_snapshot_service.metrics().cache_invalidations == 1


def test_market_bar_write_head_invalidates_before_metadata_publication(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    DataStore(tmp_path)
    meta_path = tmp_path / "meta.db"
    with sqlite3.connect(meta_path) as connection:
        connection.execute("""
            INSERT INTO market_bars_v2 (
                symbol, instrument_type, frequency, timestamp,
                open, high, low, close, volume, amount,
                identity_provenance, created_at, updated_at
            ) VALUES (
                '600001', 'stock', '1d', '2026-08-29T15:00:00+08:00',
                10.0, 11.0, 9.0, 11.0, 100.0, NULL, 'write-a', 'write-a'
                , 'write-a'
            )
            """)

    first = get_or_build_portfolio_read_snapshot(state)
    database.matrix_price = 12.0
    with sqlite3.connect(meta_path) as connection:
        connection.execute("""
            UPDATE market_bars_v2
            SET close = 12.0, updated_at = 'write-b'
            WHERE symbol = '600001' AND instrument_type = 'stock'
              AND frequency = '1d'
            """)
    second = get_or_build_portfolio_read_snapshot(state)

    assert first.identity.market_generation_id != second.identity.market_generation_id
    assert first.price_matrix_rows[0]["price"] == 11.0
    assert second.price_matrix_rows[0]["price"] == 12.0


def test_daily_market_ingestion_receipt_invalidates_same_valuation_snapshot(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    store = DataStore(tmp_path)
    first_bars = pd.DataFrame(
        [
            {
                "symbol": "600001",
                "timestamp": "2026-08-29T15:00:00+08:00",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
            }
        ]
    )
    store.ingest_market_daily_batch(
        trade_date="2026-08-29",
        provider_name="fixture",
        bars=first_bars,
    )
    first = get_or_build_portfolio_read_snapshot(state)

    second_bars = first_bars.copy()
    second_bars["timestamp"] = "2026-08-30T15:00:00+08:00"
    second_bars["close"] = 12.0
    database.matrix_price = 12.0
    store.ingest_market_daily_batch(
        trade_date="2026-08-30",
        provider_name="fixture",
        bars=second_bars,
    )
    second = get_or_build_portfolio_read_snapshot(state)

    assert first.identity.market_generation_id != second.identity.market_generation_id
    assert first.price_matrix_rows[0]["price"] == 11.0
    assert second.price_matrix_rows[0]["price"] == 12.0
    assert database.calls == Counter({"ledger": 2, "matrix": 2})


def test_market_revision_change_during_matrix_read_is_rejected(
    tmp_path: Path,
) -> None:
    state, database = _state(tmp_path)
    meta_path = tmp_path / "meta.db"
    _write_bar_revision(meta_path, dataset_id="dataset-a")
    database.before_matrix_return = lambda: _write_bar_revision(
        meta_path,
        dataset_id="dataset-b",
    )

    with pytest.raises(PortfolioReadSnapshotRejected, match="market facts changed"):
        get_or_build_portfolio_read_snapshot(state)

    assert database.calls == Counter({"ledger": 1, "matrix": 1})
    assert state.portfolio_read_snapshot_service.metrics().cache_entries == 0
    assert state.portfolio_read_snapshot_service.metrics().build_failures == 1
