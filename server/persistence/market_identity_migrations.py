"""Typed app-database market facts and evidence-bound legacy close migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.types import InstrumentKey, InstrumentType
from data.market_data import is_fund_estimate_quote_source
from server.persistence.market_identity_schema import (
    build_market_identity_schema_migration,
)


def migrate_legacy_daily_closes_to_v2(
    app_database_path: str | Path,
    *,
    meta_database_path: str | Path | None = None,
    dry_run: bool = True,
    _failure_hook: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Copy only independently corroborated legacy close rows into v2."""

    app_path = Path(app_database_path)
    if not app_path.is_file():
        raise FileNotFoundError(app_path)
    meta_path = (
        app_path.parent / "meta.db"
        if meta_database_path is None
        else Path(meta_database_path)
    )
    uri = f"{app_path.resolve().as_uri()}?mode=ro" if dry_run else str(app_path)
    conn = sqlite3.connect(uri, uri=dry_run, timeout=2.0)
    conn.row_factory = sqlite3.Row
    try:
        if dry_run:
            conn.execute("PRAGMA query_only = ON")
            return _daily_close_migration_report(
                conn,
                meta_path=meta_path,
                apply=False,
                failure_hook=None,
            )
        from server.persistence.migrations import run_immediate_schema_transaction

        def apply() -> dict[str, Any]:
            report = _daily_close_migration_report(
                conn,
                meta_path=meta_path,
                apply=True,
                failure_hook=_failure_hook,
            )
            check = conn.execute("PRAGMA quick_check").fetchone()
            if check is None or str(check[0]).lower() != "ok":
                raise RuntimeError("typed daily-close migration quick_check failed")
            return {**report, "quick_check": "ok"}

        return run_immediate_schema_transaction(conn, apply)
    finally:
        conn.close()


def migrate_legacy_daily_closes_on_connection(
    conn: sqlite3.Connection,
    *,
    meta_database_path: str | Path,
) -> dict[str, Any]:
    """Run the idempotent copy inside the caller's schema transaction."""
    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return _daily_close_migration_report(
            conn,
            meta_path=Path(meta_database_path),
            apply=True,
            failure_hook=None,
        )
    finally:
        conn.row_factory = previous_row_factory


def _daily_close_migration_report(
    conn: sqlite3.Connection,
    *,
    meta_path: Path,
    apply: bool,
    failure_hook: Callable[[str], None] | None,
) -> dict[str, Any]:
    if not _table_exists(conn, "daily_close_snapshots"):
        raise RuntimeError("legacy daily-close migration source is missing")
    source_fingerprint = _legacy_daily_source_fingerprint(conn)
    decisions: list[tuple[Any, ...]] = []
    blockers: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    rows = conn.execute("""
        SELECT id, symbol, asset_class, trade_date, close_price, source, captured_at
        FROM daily_close_snapshots
        ORDER BY id
        """).fetchall()
    requested_evidence: set[tuple[str, str, str]] = set()
    for row in rows:
        try:
            key, _ = _legacy_identity(row["symbol"], row["asset_class"])
        except (TypeError, ValueError):
            continue
        requested_evidence.add(
            (key.symbol, key.instrument_type.value, str(row["trade_date"]))
        )
    evidence = _independent_close_evidence(
        conn,
        meta_path,
        requested=requested_evidence,
    )
    for row in rows:
        try:
            key, provenance = _legacy_identity(
                row["symbol"],
                row["asset_class"],
            )
        except (TypeError, ValueError) as exc:
            blocker = {
                "id": int(row["id"]),
                "symbol": str(row["symbol"]),
                "reason": "identity_unresolved",
                "detail": str(exc),
            }
            blockers.append(blocker)
            _digest_json(digest, {"blocked": blocker})
            continue
        evidence_key = (key.symbol, key.instrument_type.value, str(row["trade_date"]))
        prices = evidence.get(evidence_key, set())
        close = _decimal(row["close_price"])
        if prices != {close}:
            blocker = {
                "id": int(row["id"]),
                "symbol": key.symbol,
                "instrument_type": key.instrument_type.value,
                "trade_date": str(row["trade_date"]),
                "source": str(row["source"]),
                "reason": (
                    "independent_close_conflict"
                    if prices
                    else "independent_close_evidence_missing"
                ),
                "evidence_prices": sorted(str(price) for price in prices),
            }
            blockers.append(blocker)
            _digest_json(digest, {"blocked": blocker})
            continue
        decision = (
            key.symbol,
            key.instrument_type.value,
            str(row["trade_date"]),
            float(close),
            str(row["source"]),
            str(row["captured_at"]),
            provenance,
        )
        decisions.append(decision)
        _digest_json(digest, {"migrate": decision})

    migrated = 0
    if apply:
        if not _table_exists(conn, "daily_close_snapshots_v2"):
            raise RuntimeError("typed daily-close target schema is missing")
        for decision in decisions:
            existing = conn.execute(
                """
                SELECT close_price, source, captured_at
                FROM daily_close_snapshots_v2
                WHERE symbol = ? AND instrument_type = ? AND trade_date = ?
                """,
                decision[:3],
            ).fetchone()
            if existing is not None:
                if (
                    _decimal(existing["close_price"]) != _decimal(decision[3])
                    or str(existing["source"]) != decision[4]
                    or str(existing["captured_at"]) != decision[5]
                ):
                    raise RuntimeError(
                        "typed daily-close target conflicts with legacy evidence: "
                        + "/".join(decision[:3])
                    )
                continue
            conn.execute(
                """
                INSERT INTO daily_close_snapshots_v2 (
                    symbol, instrument_type, trade_date, close_price,
                    source, captured_at, identity_provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                decision,
            )
            migrated += 1
        if failure_hook is not None:
            failure_hook("after_daily_closes")

    after = _legacy_daily_source_fingerprint(conn)
    if after != source_fingerprint:
        raise RuntimeError("legacy daily-close source changed during migration")
    return {
        "schema_version": "karkinos.daily_close_identity_migration.v2",
        "dry_run": not apply,
        "source_fingerprint": source_fingerprint,
        "source_preserved": True,
        "plan_fingerprint": f"sha256:{digest.hexdigest()}",
        "planned_rows": len(decisions),
        "migrated_rows": migrated,
        "blocker_count": len(blockers),
        "blockers": blockers[:100],
        "target_fingerprint": _table_fingerprint(
            conn,
            "daily_close_snapshots_v2",
            "symbol, instrument_type, trade_date",
        ),
        "quick_check": str(conn.execute("PRAGMA quick_check").fetchone()[0]),
    }


def _independent_close_evidence(
    conn: sqlite3.Connection,
    meta_path: Path,
    *,
    requested: set[tuple[str, str, str]],
) -> dict[tuple[str, str, str], set[Decimal]]:
    evidence: dict[tuple[str, str, str], set[Decimal]] = {}
    if not requested:
        return evidence

    requested_symbols = sorted({symbol for symbol, _, _ in requested})
    quote_columns = _table_columns(conn, "quote_snapshots")
    if quote_columns:
        instrument_expression = (
            "COALESCE(instrument_type, asset_class)"
            if "instrument_type" in quote_columns
            else "asset_class"
        )
        for symbol in requested_symbols:
            rows = conn.execute(
                f"""
                SELECT symbol, {instrument_expression} AS raw_type,
                       price, timestamp, quote_source, quote_status, nav_date
                FROM quote_snapshots
                WHERE symbol = ?
                ORDER BY id
                """,
                (symbol,),
            ).fetchall()
            for row in rows:
                try:
                    key, _ = _legacy_identity(row["symbol"], row["raw_type"])
                    # A realtime stock/ETF quote does not prove an official
                    # closing price.  In particular it can repeat PRE_CLOSE on
                    # the current request date, which is the legacy defect this
                    # migration must not bless.  Only a dated, confirmed
                    # open-end-fund NAV is close evidence in quote_snapshots.
                    if key.instrument_type is not InstrumentType.OPEN_END_FUND:
                        continue
                    quote_status = str(row["quote_status"] or "").strip().lower()
                    quote_source = str(row["quote_source"] or "")
                    if quote_status != "confirmed" or is_fund_estimate_quote_source(
                        quote_source
                    ):
                        continue
                    evidence_date = str(row["nav_date"] or "")
                    evidence_key = (
                        key.symbol,
                        key.instrument_type.value,
                        evidence_date,
                    )
                    if evidence_key not in requested:
                        continue
                    evidence.setdefault(evidence_key, set()).add(_decimal(row["price"]))
                except (InvalidOperation, TypeError, ValueError):
                    continue

    if meta_path.is_file():
        uri = f"{meta_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1.0) as meta:
            meta.row_factory = sqlite3.Row
            if _table_exists(meta, "market_bars_v2"):
                for symbol, instrument_type, trade_date in sorted(requested):
                    for row in meta.execute(
                        """
                        SELECT close
                        FROM market_bars_v2
                        WHERE symbol = ? AND instrument_type = ?
                          AND frequency = '1d'
                          AND substr(timestamp, 1, 10) = ?
                          AND close > 0
                        ORDER BY timestamp
                        """,
                        (symbol, instrument_type, trade_date),
                    ):
                        evidence.setdefault(
                            (symbol, instrument_type, trade_date),
                            set(),
                        ).add(_decimal(row["close"]))
    return evidence


def _legacy_identity(
    symbol: object,
    raw_type: object,
) -> tuple[InstrumentKey, str]:
    normalized = str(raw_type or "").strip().lower().replace("-", "_")
    key = InstrumentKey.from_values(symbol, normalized)
    provenance = (
        "legacy_fund_compatibility"
        if normalized == "fund"
        else "legacy_asset_class_compatibility"
    )
    return key, provenance


def _legacy_daily_source_fingerprint(
    conn: sqlite3.Connection,
) -> str:
    digest = hashlib.sha256()
    _digest_json(digest, {"table": "daily_close_snapshots"})
    for row in conn.execute("SELECT * FROM daily_close_snapshots ORDER BY id"):
        _digest_json(digest, list(row))
    return f"sha256:{digest.hexdigest()}"


def _table_fingerprint(
    conn: sqlite3.Connection,
    table: str,
    order_by: str,
) -> str:
    digest = hashlib.sha256()
    if not _table_exists(conn, table):
        _digest_json(digest, {"table": table, "state": "absent"})
        return f"sha256:{digest.hexdigest()}"
    _digest_json(digest, {"table": table})
    for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}"):
        _digest_json(digest, list(row))
    return f"sha256:{digest.hexdigest()}"


def _decimal(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("close price is invalid")
    return parsed


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


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


__all__ = [
    "build_market_identity_schema_migration",
    "migrate_legacy_daily_closes_on_connection",
    "migrate_legacy_daily_closes_to_v2",
]
