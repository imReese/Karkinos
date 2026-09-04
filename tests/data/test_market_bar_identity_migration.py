from __future__ import annotations

import hashlib
import json
import sqlite3

from data.market_bar_identity import migrate_legacy_market_bars_to_v2
from data.store import DataStore


def _insert_legacy_bar(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    timestamp: str,
    close: float,
) -> None:
    conn.execute(
        """
        INSERT INTO market_bars (
            symbol, frequency, timestamp, open, high, low, close,
            volume, amount, created_at, updated_at
        ) VALUES (?, '1d', ?, ?, ?, ?, ?, 100, NULL, 'created', 'updated')
        """,
        (symbol, timestamp, close, close, close, close),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO bar_meta (
            symbol, frequency, start_date, end_date, last_updated, row_count
        ) VALUES (?, '1d', ?, ?, 'updated', 1)
        """,
        (symbol, timestamp, timestamp),
    )


def test_legacy_market_bar_migration_is_typed_idempotent_and_source_preserving(
    tmp_path,
) -> None:
    store = DataStore(tmp_path)
    with sqlite3.connect(store._meta_path) as conn:
        _insert_legacy_bar(
            conn,
            symbol="600001",
            timestamp="2026-09-03T15:00:00+08:00",
            close=10.5,
        )
        _insert_legacy_bar(
            conn,
            symbol="019999",
            timestamp="2026-09-03T15:00:00+08:00",
            close=1.25,
        )
        _insert_legacy_bar(
            conn,
            symbol="AMBIG",
            timestamp="2026-09-03T15:00:00+08:00",
            close=2.0,
        )

    evidence = {
        "600001": "stock",
        "019999": "fund",
        "AMBIG": ["fund", "etf"],
    }
    dry_run = migrate_legacy_market_bars_to_v2(
        store._meta_path,
        identity_evidence=evidence,
        dry_run=True,
    )
    repeated_dry_run = migrate_legacy_market_bars_to_v2(
        store._meta_path,
        identity_evidence=evidence,
        dry_run=True,
    )

    assert dry_run["plan_fingerprint"] == repeated_dry_run["plan_fingerprint"]
    assert dry_run["planned_bar_rows"] == 2
    assert dry_run["blocker_count"] == 1
    with sqlite3.connect(store._meta_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM market_bars_v2").fetchone()[0] == 0

    applied = migrate_legacy_market_bars_to_v2(
        store._meta_path,
        identity_evidence=evidence,
        dry_run=False,
    )
    replay = migrate_legacy_market_bars_to_v2(
        store._meta_path,
        identity_evidence=evidence,
        dry_run=False,
    )

    assert applied["quick_check"] == "ok"
    assert applied["source_fingerprint"] == dry_run["source_fingerprint"]
    assert applied["migrated_bar_rows"] == 2
    assert replay["migrated_bar_rows"] == 0
    assert replay["target_fingerprint"] == applied["target_fingerprint"]
    with sqlite3.connect(store._meta_path) as conn:
        rows = conn.execute("""
            SELECT symbol, instrument_type, identity_provenance
            FROM market_bars_v2
            ORDER BY symbol
            """).fetchall()
        assert rows == [
            ("019999", "open_end_fund", "legacy_fund_compatibility"),
            ("600001", "stock", "explicit_identity_evidence"),
        ]
        assert conn.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0] == 3


def test_legacy_market_bar_migration_rolls_back_typed_target_on_failure(
    tmp_path,
) -> None:
    store = DataStore(tmp_path)
    with sqlite3.connect(store._meta_path) as conn:
        _insert_legacy_bar(
            conn,
            symbol="600001",
            timestamp="2026-09-03T15:00:00+08:00",
            close=10.5,
        )

    def fail_after_bars(stage: str) -> None:
        if stage == "after_market_bars":
            raise RuntimeError("injected migration failure")

    try:
        migrate_legacy_market_bars_to_v2(
            store._meta_path,
            identity_evidence={"600001": "stock"},
            dry_run=False,
            _failure_hook=fail_after_bars,
        )
    except RuntimeError as exc:
        assert str(exc) == "injected migration failure"
    else:
        raise AssertionError("migration failure was not injected")

    with sqlite3.connect(store._meta_path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM market_bars_v2").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM bar_meta_v2").fetchone()[0] == 0


def test_verified_legacy_daily_receipt_proves_only_stock_identity(tmp_path) -> None:
    store = DataStore(tmp_path)
    record = (
        "600001",
        "2026-09-03T15:00:00+08:00",
        10.0,
        11.0,
        9.0,
        10.5,
        100.0,
        None,
    )
    with sqlite3.connect(store._meta_path) as conn:
        _insert_legacy_bar(
            conn,
            symbol=record[0],
            timestamp=record[1],
            close=record[5],
        )
        conn.execute(
            """
            UPDATE market_bars
            SET open = ?, high = ?, low = ?, volume = ?, amount = ?
            WHERE symbol = ? AND timestamp = ?
            """,
            (
                record[2],
                record[3],
                record[4],
                record[6],
                record[7],
                record[0],
                record[1],
            ),
        )
        dataset_payload = {
            "schema_version": "karkinos.market_daily_dataset.v1",
            "trade_date": "2026-09-03",
            "provider_name": "fixture",
            "records": [list(record)],
        }
        dataset_fingerprint = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    dataset_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        core = {
            "schema_version": "karkinos.market_daily_ingestion_receipt.v1",
            "trade_date": "2026-09-03",
            "provider_name": "fixture",
            "row_count": 1,
            "symbols": ["600001"],
            "dataset_fingerprint": dataset_fingerprint,
            "storage_authority": "sqlite_market_bars",
            "parquet_mirror_required_for_decision": False,
            "provider_contact_performed_during_ingestion": True,
            "read_endpoints_contact_providers": False,
            "authorizes_strategy_promotion": False,
            "authorizes_order_creation": False,
            "changes_capital_authority": False,
        }
        receipt = {
            **core,
            "receipt_fingerprint": "sha256:"
            + hashlib.sha256(
                json.dumps(
                    core,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        }
        conn.execute(
            """
            INSERT INTO market_daily_ingestion_receipts VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-09-03",
                "fixture",
                1,
                dataset_fingerprint,
                json.dumps(receipt),
                "2026-09-03T15:01:00+08:00",
            ),
        )

    result = migrate_legacy_market_bars_to_v2(
        store._meta_path,
        dry_run=False,
    )
    assert result["planned_bar_rows"] == 1
    with sqlite3.connect(store._meta_path) as conn:
        assert (
            conn.execute(
                "SELECT instrument_type FROM market_bars_v2 WHERE symbol = '600001'"
            ).fetchone()[0]
            == "stock"
        )
