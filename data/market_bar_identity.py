"""Typed market-bar storage and deterministic legacy migration helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.market_daily_store import _market_daily_records_fingerprint

_CANONICAL_INSTRUMENT_TYPES = tuple(
    item.value for item in InstrumentType if item is not InstrumentType.UNKNOWN
)
_INSTRUMENT_TYPE_CHECK = ", ".join(
    f"'{instrument_type}'" for instrument_type in _CANONICAL_INSTRUMENT_TYPES
)

MARKET_BAR_V2_SCHEMA = (
    f"""
    CREATE TABLE IF NOT EXISTS market_bars_v2 (
        symbol TEXT NOT NULL CHECK(trim(symbol) <> ''),
        instrument_type TEXT NOT NULL
            CHECK(instrument_type IN ({_INSTRUMENT_TYPE_CHECK})),
        frequency TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL NOT NULL CHECK(close > 0),
        volume REAL,
        amount REAL,
        identity_provenance TEXT NOT NULL
            CHECK(trim(identity_provenance) <> ''),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (symbol, instrument_type, frequency, timestamp)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_bars_v2_identity_frequency_ts
    ON market_bars_v2(symbol, instrument_type, frequency, timestamp)
    """,
    f"""
    CREATE TABLE IF NOT EXISTS bar_meta_v2 (
        symbol TEXT NOT NULL CHECK(trim(symbol) <> ''),
        instrument_type TEXT NOT NULL
            CHECK(instrument_type IN ({_INSTRUMENT_TYPE_CHECK})),
        frequency TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        last_updated TEXT,
        row_count INTEGER DEFAULT 0,
        provider_name TEXT,
        data_source TEXT,
        adjustment_mode TEXT,
        fetched_at TEXT,
        dataset_id TEXT,
        diagnostics_json TEXT,
        duplicate_timestamp_count INTEGER DEFAULT 0,
        missing_ohlcv_count INTEGER DEFAULT 0,
        is_monotonic INTEGER DEFAULT 1,
        identity_provenance TEXT NOT NULL
            CHECK(trim(identity_provenance) <> ''),
        PRIMARY KEY (symbol, instrument_type, frequency)
    )
    """,
)


def ensure_market_bar_v2_schema(conn: sqlite3.Connection) -> None:
    """Create the typed target without altering either legacy source table."""

    for statement in MARKET_BAR_V2_SCHEMA:
        conn.execute(statement)


def migrate_legacy_market_bars_to_v2(
    database_path: str | Path,
    *,
    identity_evidence: Mapping[str, object] | None = None,
    dry_run: bool = True,
    _failure_hook: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Plan or apply an evidence-bound migration into the typed v2 tables.

    A verified full-market ingestion receipt proves only ``stock`` rows for its
    exact date.  Caller evidence may prove another exact identity.  Generic
    legacy ``fund`` evidence is accepted solely as an open-end-fund
    compatibility identity; it can never authorize an ETF row.  Conflicting or
    unresolved rows remain in the untouched legacy tables and are reported as
    blockers.
    """

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"{path.resolve().as_uri()}?mode=ro" if dry_run else str(path)
    connection = sqlite3.connect(uri, uri=dry_run, timeout=2.0)
    connection.row_factory = sqlite3.Row
    try:
        if dry_run:
            connection.execute("PRAGMA query_only = ON")
            return _migration_report(
                connection,
                identity_evidence=identity_evidence or {},
                apply=False,
                failure_hook=None,
            )

        connection.execute("BEGIN IMMEDIATE")
        try:
            report = _migration_report(
                connection,
                identity_evidence=identity_evidence or {},
                apply=True,
                failure_hook=_failure_hook,
            )
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                raise RuntimeError("typed market-bar migration quick_check failed")
            connection.commit()
            return {**report, "quick_check": "ok"}
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()


def _migration_report(
    conn: sqlite3.Connection,
    *,
    identity_evidence: Mapping[str, object],
    apply: bool,
    failure_hook: Callable[[str], None] | None,
) -> dict[str, Any]:
    _require_legacy_schema(conn)
    source_fingerprint_before = _legacy_source_fingerprint(conn)
    explicit = _normalize_identity_evidence(identity_evidence)
    receipt_evidence, invalid_receipts = _verified_receipt_evidence(conn)
    decisions, blockers, plan_fingerprint = _plan_bar_rows(
        conn,
        explicit=explicit,
        receipt_evidence=receipt_evidence,
    )

    migrated_bar_rows = 0
    migrated_meta_rows = 0
    if apply:
        ensure_market_bar_v2_schema(conn)
        migrated_bar_rows = _write_planned_bar_rows(conn, decisions)
        if failure_hook is not None:
            failure_hook("after_market_bars")
        migrated_meta_rows = _write_bar_meta_rows(conn, decisions)
        if failure_hook is not None:
            failure_hook("after_bar_meta")

    source_fingerprint_after = _legacy_source_fingerprint(conn)
    if source_fingerprint_after != source_fingerprint_before:
        raise RuntimeError("legacy market-bar source changed during migration")
    return {
        "schema_version": "karkinos.market_bar_identity_migration.v2",
        "dry_run": not apply,
        "source_fingerprint": source_fingerprint_before,
        "source_preserved": True,
        "plan_fingerprint": plan_fingerprint,
        "planned_bar_rows": len(decisions),
        "migrated_bar_rows": migrated_bar_rows,
        "migrated_meta_rows": migrated_meta_rows,
        "blocker_count": len(blockers) + len(invalid_receipts),
        "blockers": [*invalid_receipts, *blockers][:100],
        "target_fingerprint": _typed_target_fingerprint(conn),
        "quick_check": str(conn.execute("PRAGMA quick_check").fetchone()[0]),
    }


def _require_legacy_schema(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = {"market_bars", "bar_meta"} - tables
    if missing:
        raise RuntimeError(
            "legacy market-bar migration source is missing: "
            + ",".join(sorted(missing))
        )


def _normalize_identity_evidence(
    evidence: Mapping[str, object],
) -> dict[str, tuple[tuple[InstrumentType, str], ...]]:
    result: dict[str, tuple[tuple[InstrumentType, str], ...]] = {}
    for raw_symbol, raw_values in evidence.items():
        symbol = str(raw_symbol).strip()
        if not symbol:
            raise ValueError("identity evidence contains an empty symbol")
        if isinstance(raw_values, (str, InstrumentType)):
            values: Sequence[object] = (raw_values,)
        elif isinstance(raw_values, Iterable):
            values = tuple(raw_values)
        else:
            values = (raw_values,)
        normalized: set[tuple[InstrumentType, str]] = set()
        for raw_value in values:
            text = (
                raw_value.value
                if isinstance(raw_value, InstrumentType)
                else str(raw_value or "").strip().lower().replace("-", "_")
            )
            instrument_type = InstrumentType.from_persisted(text)
            provenance = (
                "legacy_fund_compatibility"
                if text == "fund"
                else "explicit_identity_evidence"
            )
            normalized.add((instrument_type, provenance))
        result[symbol] = tuple(
            sorted(normalized, key=lambda item: (item[0].value, item[1]))
        )
    return result


def _verified_receipt_evidence(
    conn: sqlite3.Connection,
) -> tuple[dict[tuple[str, str], tuple[InstrumentType, str]], list[dict[str, Any]]]:
    if not _table_exists(conn, "market_daily_ingestion_receipts"):
        return {}, []
    evidence: dict[tuple[str, str], tuple[InstrumentType, str]] = {}
    invalid: list[dict[str, Any]] = []
    rows = conn.execute("""
        SELECT trade_date, provider_name, receipt_json
        FROM market_daily_ingestion_receipts
        ORDER BY trade_date, provider_name
        """).fetchall()
    for row in rows:
        trade_date = str(row["trade_date"])
        provider_name = str(row["provider_name"])
        try:
            receipt = json.loads(str(row["receipt_json"]))
        except (json.JSONDecodeError, TypeError):
            receipt = None
        if not isinstance(receipt, dict) or not _receipt_is_valid(conn, receipt):
            invalid.append(
                {
                    "reason": "invalid_market_daily_ingestion_receipt",
                    "trade_date": trade_date,
                    "provider_name": provider_name,
                }
            )
            continue
        symbols = receipt.get("symbols")
        assert isinstance(symbols, list)
        for symbol in symbols:
            key = (str(symbol), trade_date)
            existing = evidence.get(key)
            candidate = (
                InstrumentType.STOCK,
                "verified_market_daily_ingestion_receipt",
            )
            if existing is not None and existing != candidate:
                invalid.append(
                    {
                        "reason": "market_daily_receipt_identity_conflict",
                        "symbol": key[0],
                        "trade_date": trade_date,
                    }
                )
                evidence.pop(key, None)
                continue
            evidence[key] = candidate
    return evidence, invalid


def _receipt_is_valid(conn: sqlite3.Connection, receipt: Mapping[str, object]) -> bool:
    schema_version = str(receipt.get("schema_version") or "")
    if schema_version != "karkinos.market_daily_ingestion_receipt.v1":
        return False
    symbols = receipt.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        return False
    trade_date = str(receipt.get("trade_date") or "")
    rows = conn.execute(
        """
        SELECT symbol, timestamp, open, high, low, close, volume, amount
        FROM market_bars
        WHERE frequency = '1d' AND substr(timestamp, 1, 10) = ?
        ORDER BY symbol
        """,
        (trade_date,),
    ).fetchall()
    wanted = {str(symbol) for symbol in symbols}
    records = [tuple(row) for row in rows if str(row[0]) in wanted]
    if len(records) != len(wanted):
        return False
    expected_dataset = _market_daily_records_fingerprint(
        trade_date=trade_date,
        provider_name=str(receipt.get("provider_name") or ""),
        records=records,
    )
    if receipt.get("dataset_fingerprint") != expected_dataset:
        return False
    core = dict(receipt)
    stored_fingerprint = core.pop("receipt_fingerprint", None)
    expected_fingerprint = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                core,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    return stored_fingerprint == expected_fingerprint


def _plan_bar_rows(
    conn: sqlite3.Connection,
    *,
    explicit: Mapping[str, tuple[tuple[InstrumentType, str], ...]],
    receipt_evidence: Mapping[tuple[str, str], tuple[InstrumentType, str]],
) -> tuple[list[tuple[Any, ...]], list[dict[str, Any]], str]:
    decisions: list[tuple[Any, ...]] = []
    blockers: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    rows = conn.execute("""
        SELECT symbol, frequency, timestamp, open, high, low, close,
               volume, amount, created_at, updated_at
        FROM market_bars
        ORDER BY symbol, frequency, timestamp
        """)
    for row in rows:
        symbol = str(row["symbol"])
        trade_date = str(row["timestamp"])[:10]
        candidates = set(explicit.get(symbol, ()))
        receipt_candidate = receipt_evidence.get((symbol, trade_date))
        if receipt_candidate is not None:
            candidates.add(receipt_candidate)
        types = {item[0] for item in candidates}
        if len(types) != 1:
            reason = "identity_unresolved" if not types else "identity_ambiguous"
            blocker = {
                "reason": reason,
                "symbol": symbol,
                "frequency": str(row["frequency"]),
                "timestamp": str(row["timestamp"]),
                "candidate_types": sorted(item.value for item in types),
            }
            blockers.append(blocker)
            _digest_json(digest, {"blocked": blocker})
            continue
        instrument_type = next(iter(types))
        provenances = sorted(
            provenance
            for candidate_type, provenance in candidates
            if candidate_type is instrument_type
        )
        provenance = "+".join(provenances)
        key = InstrumentKey(symbol, instrument_type)
        decision = (
            key.symbol,
            key.instrument_type.value,
            str(row["frequency"]),
            str(row["timestamp"]),
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["volume"],
            row["amount"],
            provenance,
            str(row["created_at"]),
            str(row["updated_at"]),
        )
        decisions.append(decision)
        _digest_json(digest, {"migrate": decision})
    return decisions, blockers, f"sha256:{digest.hexdigest()}"


def _write_planned_bar_rows(
    conn: sqlite3.Connection,
    decisions: Sequence[tuple[Any, ...]],
) -> int:
    inserted = 0
    for decision in decisions:
        key = decision[:4]
        existing = conn.execute(
            """
            SELECT open, high, low, close, volume, amount
            FROM market_bars_v2
            WHERE symbol = ? AND instrument_type = ?
              AND frequency = ? AND timestamp = ?
            """,
            key,
        ).fetchone()
        if existing is not None:
            if tuple(existing) != tuple(decision[4:10]):
                raise RuntimeError(
                    "typed market-bar target conflicts with legacy evidence: "
                    f"{key[0]}/{key[1]}/{key[2]}/{key[3]}"
                )
            continue
        conn.execute(
            """
            INSERT INTO market_bars_v2 (
                symbol, instrument_type, frequency, timestamp,
                open, high, low, close, volume, amount,
                identity_provenance, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            decision,
        )
        inserted += 1
    return inserted


def _write_bar_meta_rows(
    conn: sqlite3.Connection,
    decisions: Sequence[tuple[Any, ...]],
) -> int:
    identities: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for decision in decisions:
        identities.setdefault((str(decision[0]), str(decision[2])), set()).add(
            (str(decision[1]), str(decision[10]))
        )
    inserted = 0
    for row in conn.execute("SELECT * FROM bar_meta ORDER BY symbol, frequency"):
        candidates = identities.get((str(row["symbol"]), str(row["frequency"])), set())
        types = {candidate[0] for candidate in candidates}
        if len(types) != 1:
            continue
        instrument_type = next(iter(types))
        provenance = "+".join(
            sorted(value for kind, value in candidates if kind == instrument_type)
        )
        existing = conn.execute(
            """
            SELECT * FROM bar_meta_v2
            WHERE symbol = ? AND instrument_type = ? AND frequency = ?
            """,
            (row["symbol"], instrument_type, row["frequency"]),
        ).fetchone()
        values = (
            row["symbol"],
            instrument_type,
            row["frequency"],
            row["start_date"],
            row["end_date"],
            row["last_updated"],
            row["row_count"],
            row["provider_name"],
            row["data_source"],
            row["adjustment_mode"],
            row["fetched_at"],
            row["dataset_id"],
            row["diagnostics_json"],
            row["duplicate_timestamp_count"],
            row["missing_ohlcv_count"],
            row["is_monotonic"],
            provenance,
        )
        if existing is not None:
            comparable = tuple(existing)[0:16]
            expected = values[0:16]
            if comparable != expected:
                raise RuntimeError(
                    "typed bar-meta target conflicts with legacy evidence: "
                    f"{row['symbol']}/{instrument_type}/{row['frequency']}"
                )
            continue
        conn.execute(
            """
            INSERT INTO bar_meta_v2 (
                symbol, instrument_type, frequency, start_date, end_date,
                last_updated, row_count, provider_name, data_source,
                adjustment_mode, fetched_at, dataset_id, diagnostics_json,
                duplicate_timestamp_count, missing_ohlcv_count, is_monotonic,
                identity_provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        inserted += 1
    return inserted


def _legacy_source_fingerprint(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table, order_by in (
        ("market_bars", "symbol, frequency, timestamp"),
        ("bar_meta", "symbol, frequency"),
        ("market_daily_ingestion_receipts", "trade_date, provider_name"),
    ):
        if not _table_exists(conn, table):
            _digest_json(digest, {"table": table, "state": "absent"})
            continue
        columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
        _digest_json(digest, {"table": table, "columns": columns})
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}"):
            _digest_json(digest, list(row))
    return f"sha256:{digest.hexdigest()}"


def _typed_target_fingerprint(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table, order_by in (
        (
            "market_bars_v2",
            "symbol, instrument_type, frequency, timestamp",
        ),
        ("bar_meta_v2", "symbol, instrument_type, frequency"),
    ):
        if not _table_exists(conn, table):
            _digest_json(digest, {"table": table, "state": "absent"})
            continue
        _digest_json(digest, {"table": table})
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}"):
            _digest_json(digest, list(row))
    return f"sha256:{digest.hexdigest()}"


def _digest_json(digest: Any, value: object) -> None:
    digest.update(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )
    digest.update(b"\n")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        is not None
    )


__all__ = [
    "MARKET_BAR_V2_SCHEMA",
    "ensure_market_bar_v2_schema",
    "migrate_legacy_market_bars_to_v2",
]
