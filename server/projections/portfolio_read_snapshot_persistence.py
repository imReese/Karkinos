"""Read-only persistence adapter for immutable portfolio read snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import RLock
from typing import Any, cast

from core.types import InstrumentKey
from server.dependencies import AppState, get_portfolio_read_request_state
from server.persistence.database_identity import require_database_path
from server.projections.portfolio_read_market_rows import (
    flatten_price_matrix as _flatten_price_matrix,
)
from server.projections.portfolio_read_market_rows import (
    read_intraday_quote_rows as _read_intraday_quote_rows,
)
from server.projections.portfolio_read_market_rows import (
    read_only_connection as _read_only_connection,
)
from server.projections.portfolio_read_snapshot import (
    PortfolioReadPortResult,
    PortfolioReadSnapshot,
    PortfolioReadSnapshotIdentity,
    PortfolioReadSnapshotPorts,
    PortfolioReadSnapshotRejected,
    PortfolioReadSnapshotService,
)
from server.projections.valuation_snapshot import (
    ledger_identity_from_rows,
    valuation_snapshot_from_row,
)

LEGACY_UNBOUND_MARKET_IDENTITY = "legacy-unbound-market-evidence"
_MATRIX_SYMBOL_BATCH_SIZE = 400
_SERVICE_INIT_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class _ResolvedReadIdentity:
    identity: PortfolioReadSnapshotIdentity
    valuation: dict[str, Any]
    identity_query_count: int
    identity_rows_read: int
    market_revision_fingerprint: str


@dataclass(frozen=True, slots=True)
class _PersistedMarketRevision:
    fingerprint: str
    evidence_complete: bool
    query_count: int
    rows_read: int


def get_or_build_portfolio_read_snapshot(state: AppState) -> PortfolioReadSnapshot:
    """Build or reuse one snapshot from persisted facts without writing or fetching."""

    if not isinstance(state, AppState):
        raise TypeError("state must be AppState")
    request_state = get_portfolio_read_request_state()
    if request_state is not None:
        with request_state.lock:
            pinned = request_state.snapshot
            if pinned is not None:
                if not isinstance(pinned, PortfolioReadSnapshot):
                    raise PortfolioReadSnapshotRejected(
                        "request portfolio read snapshot has an invalid type"
                    )
                return pinned
            snapshot = _get_or_build_portfolio_read_snapshot(state)
            request_state.snapshot = snapshot
            return snapshot
    return _get_or_build_portfolio_read_snapshot(state)


def portfolio_read_snapshot_for_state(state: object) -> PortfolioReadSnapshot | None:
    """Resolve the canonical snapshot for production state, preserving test adapters."""

    if not isinstance(state, AppState):
        return None
    return get_or_build_portfolio_read_snapshot(state)


def _get_or_build_portfolio_read_snapshot(state: AppState) -> PortfolioReadSnapshot:
    """Resolve the current identity and build outside request-local pinning."""

    database = state.require_database()
    database_path = require_database_path(
        database,
        PortfolioReadSnapshotRejected("application database path is unavailable"),
    )
    resolved = _resolve_read_identity(database_path)
    service = _snapshot_service(state)

    def read_published_valuation(
        identity: PortfolioReadSnapshotIdentity,
    ) -> PortfolioReadPortResult[Mapping[str, Any]]:
        return PortfolioReadPortResult(
            identity=identity,
            value=resolved.valuation,
            query_count=resolved.identity_query_count,
            rows_read=resolved.identity_rows_read,
        )

    def read_ledger_rows(
        identity: PortfolioReadSnapshotIdentity,
    ) -> PortfolioReadPortResult[Sequence[Mapping[str, Any]]]:
        try:
            raw_rows = database.get_all_ledger_entries_sync()
        except Exception as exc:
            raise PortfolioReadSnapshotRejected(
                "persisted ledger rows are unavailable"
            ) from exc
        rows = _mapping_rows(raw_rows, "persisted ledger rows")
        ledger_identity = ledger_identity_from_rows([dict(row) for row in rows])
        if int(ledger_identity["ledger_cutoff_id"]) != identity.ledger_cutoff_id:
            raise PortfolioReadSnapshotRejected(
                "persisted ledger cutoff does not match valuation identity"
            )
        if str(ledger_identity["ledger_fingerprint"]) != identity.ledger_fingerprint:
            raise PortfolioReadSnapshotRejected(
                "persisted ledger fingerprint does not match valuation identity"
            )
        canonical_rows = cast(list[dict[str, Any]], ledger_identity["rows"])
        return PortfolioReadPortResult(
            identity=identity,
            value=canonical_rows,
            query_count=1,
            rows_read=len(canonical_rows),
        )

    def read_price_matrix(
        identity: PortfolioReadSnapshotIdentity,
        ledger_rows: tuple[Mapping[str, Any], ...],
    ) -> PortfolioReadPortResult[Sequence[Mapping[str, Any]]]:
        instrument_keys = _ledger_instrument_keys(ledger_rows)
        start_date, end_date = _matrix_date_window(
            ledger_rows,
            valuation=resolved.valuation,
        )
        if instrument_keys:
            try:
                matrix = database.get_historical_price_matrix_sync(
                    instrument_keys=instrument_keys,
                    start_date=start_date,
                    end_date=end_date,
                    symbol_batch_size=_MATRIX_SYMBOL_BATCH_SIZE,
                )
            except Exception as exc:
                raise PortfolioReadSnapshotRejected(
                    "persisted price matrix is unavailable"
                ) from exc
        else:
            matrix = {}
        flattened = _flatten_price_matrix(
            matrix,
            requested_instrument_keys=instrument_keys,
        )
        matrix_query_count = (
            (len(instrument_keys) + _MATRIX_SYMBOL_BATCH_SIZE - 1)
            // _MATRIX_SYMBOL_BATCH_SIZE
            if instrument_keys
            else 0
        )
        return PortfolioReadPortResult(
            identity=identity,
            value=flattened,
            query_count=matrix_query_count,
            rows_read=len(flattened),
        )

    def read_intraday_quote_rows(
        identity: PortfolioReadSnapshotIdentity,
        ledger_rows: tuple[Mapping[str, Any], ...],
    ) -> PortfolioReadPortResult[Sequence[Mapping[str, Any]]]:
        instrument_keys = _ledger_instrument_keys(ledger_rows)
        trade_date = _iso_date(
            resolved.valuation.get("trade_date"),
            "valuation trade date",
        )
        rows, intraday_query_count = _read_intraday_quote_rows(
            database_path,
            instrument_keys=instrument_keys,
            trade_date=trade_date,
        )
        verified_revision = _read_persisted_market_revision(database_path)
        if verified_revision.fingerprint != resolved.market_revision_fingerprint:
            raise PortfolioReadSnapshotRejected(
                "persisted market facts changed while building the read snapshot"
            )
        return PortfolioReadPortResult(
            identity=identity,
            value=rows,
            query_count=intraday_query_count + verified_revision.query_count,
            rows_read=len(rows) + verified_revision.rows_read,
        )

    return service.get_or_build(
        resolved.identity,
        PortfolioReadSnapshotPorts(
            read_published_valuation=read_published_valuation,
            read_ledger_rows=read_ledger_rows,
            read_price_matrix=read_price_matrix,
            read_intraday_quote_rows=read_intraday_quote_rows,
        ),
    )


def _snapshot_service(state: AppState) -> PortfolioReadSnapshotService:
    with _SERVICE_INIT_LOCK:
        service = state.portfolio_read_snapshot_service
        if service is None:
            service = PortfolioReadSnapshotService()
            state.portfolio_read_snapshot_service = service
        return service


def _resolve_read_identity(database_path: Path) -> _ResolvedReadIdentity:
    valuation, valuation_rows = _read_published_valuation(database_path)
    market_revision = _read_persisted_market_revision(database_path)
    market = _valuation_bound_market_identity(
        valuation,
        market_revision=market_revision,
    )
    try:
        identity = PortfolioReadSnapshotIdentity(
            valuation_snapshot_id=_required_text(
                valuation.get("snapshot_id"), "valuation snapshot id"
            ),
            ledger_cutoff_id=_required_non_negative_int(
                valuation.get("ledger_cutoff_id"), "valuation ledger cutoff"
            ),
            ledger_fingerprint=_required_text(
                valuation.get("ledger_fingerprint"), "valuation ledger fingerprint"
            ),
            market_generation_id=market["generation_id"],
            market_receipt_fingerprint=market["receipt_fingerprint"],
            market_content_fingerprint=market["content_fingerprint"],
            policy_version=_required_text(
                valuation.get("valuation_policy"), "valuation policy"
            ),
            market_evidence_status=market["evidence_status"],
        )
    except (TypeError, ValueError) as exc:
        raise PortfolioReadSnapshotRejected(
            "published portfolio read identity is invalid"
        ) from exc
    return _ResolvedReadIdentity(
        identity=identity,
        valuation=valuation,
        identity_query_count=1 + market_revision.query_count,
        identity_rows_read=valuation_rows + market_revision.rows_read,
        market_revision_fingerprint=market_revision.fingerprint,
    )


def _read_published_valuation(database_path: Path) -> tuple[dict[str, Any], int]:
    sql = """
        SELECT
            controls.value_json AS publication_json,
            controls.updated_at AS publication_updated_at,
            snapshots.*
        FROM runtime_controls AS controls
        JOIN valuation_snapshots AS snapshots
          ON snapshots.snapshot_id = json_extract(controls.value_json, '$.snapshot_id')
        WHERE controls.key = 'valuation_snapshot_publication'
        LIMIT 1
    """
    try:
        with _read_only_connection(database_path) as connection:
            row = connection.execute(sql).fetchone()
    except (sqlite3.Error, OSError) as exc:
        raise PortfolioReadSnapshotRejected(
            "published valuation identity is unavailable"
        ) from exc
    if row is None:
        raise PortfolioReadSnapshotRejected(
            "published valuation identity is unavailable"
        )
    try:
        publication = json.loads(str(row["publication_json"]))
    except (json.JSONDecodeError, TypeError) as exc:
        raise PortfolioReadSnapshotRejected(
            "valuation publication metadata is invalid"
        ) from exc
    if not isinstance(publication, dict) or publication.get("status") != "ready":
        raise PortfolioReadSnapshotRejected("valuation publication is not ready")
    snapshot_id = _required_text(
        publication.get("snapshot_id"), "published snapshot id"
    )
    if snapshot_id != str(row["snapshot_id"]):
        raise PortfolioReadSnapshotRejected("valuation publication identity drifted")
    try:
        valuation = valuation_snapshot_from_row(dict(row))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PortfolioReadSnapshotRejected(
            "published valuation snapshot is invalid"
        ) from exc
    quotes = valuation.get("quotes")
    if not isinstance(quotes, list):
        raise PortfolioReadSnapshotRejected("published valuation quotes are invalid")
    return valuation, 1 + len(quotes)


def _read_persisted_market_revision(
    database_path: Path,
) -> _PersistedMarketRevision:
    """Fingerprint the persisted sources consumed by the historical matrix."""

    query_count = 0
    rows_read = 0
    app_revision: dict[str, Any]
    try:
        with _read_only_connection(database_path) as connection:
            app_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            quote_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(quote_snapshots)")
            }
            query_count += 1
            quote_row = connection.execute("""
                SELECT
                    COUNT(*) AS row_count,
                    COALESCE(MAX(id), 0) AS append_only_head
                FROM quote_snapshots
                """).fetchone()
            query_count += 1
            if "daily_close_snapshots_v2" in app_tables:
                close_rows = connection.execute("""
                    SELECT
                        id, symbol, instrument_type, trade_date,
                        close_price, source, captured_at, identity_provenance
                    FROM daily_close_snapshots_v2
                    ORDER BY id
                    """).fetchall()
            else:
                close_rows = connection.execute("""
                    SELECT
                        id, symbol, asset_class, trade_date,
                        close_price, source, captured_at
                    FROM daily_close_snapshots
                    ORDER BY id
                    """).fetchall()
        if quote_row is None:
            raise PortfolioReadSnapshotRejected(
                "persisted market revision is unavailable"
            )
        app_revision = {
            "quote_snapshots": dict(quote_row),
            "daily_closes": [dict(row) for row in close_rows],
        }
        rows_read += 1 + len(close_rows)
        app_evidence_complete = (
            "daily_close_snapshots_v2" in app_tables
            and {"instrument_type", "identity_provenance"} <= quote_columns
        )
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise PortfolioReadSnapshotRejected(
                "persisted market revision is unavailable"
            ) from exc
        app_revision = {"storage": "legacy_unversioned"}
        app_evidence_complete = False
    except (sqlite3.Error, OSError) as exc:
        raise PortfolioReadSnapshotRejected(
            "persisted market revision is unavailable"
        ) from exc

    meta_path = database_path.parent / "meta.db"
    bar_revision: dict[str, Any] = {"storage": "absent"}
    if meta_path.is_file():
        try:
            with _read_only_connection(meta_path) as connection:
                query_count += 1
                meta_tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                has_typed_bars = {
                    "bar_meta_v2",
                    "market_bars_v2",
                } <= meta_tables
                dataset_table = "bar_meta_v2" if has_typed_bars else "bar_meta"
                dataset_identity = (
                    "instrument_type, identity_provenance," if has_typed_bars else ""
                )
                dataset_rows = connection.execute(f"""
                    SELECT
                        symbol, {dataset_identity} frequency, dataset_id, row_count,
                        start_date, end_date, last_updated
                    FROM {dataset_table}
                    ORDER BY symbol, {('instrument_type,' if has_typed_bars else '')}
                             frequency
                    """).fetchall()
                query_count += 1
                try:
                    receipt_rows = connection.execute("""
                        SELECT
                            trade_date, provider_name, row_count,
                            dataset_fingerprint, receipt_json, created_at
                        FROM market_daily_ingestion_receipts
                        ORDER BY trade_date, provider_name
                        """).fetchall()
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise
                    receipt_rows = []
                query_count += 1
                try:
                    bar_table = "market_bars_v2" if has_typed_bars else "market_bars"
                    write_head_row = connection.execute(f"""
                        SELECT
                            COUNT(*) AS row_count,
                            COALESCE(MAX(updated_at), '') AS write_head
                        FROM {bar_table}
                        """).fetchone()
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise
                    write_head_row = None
            bar_revision = {
                "storage": "bar_meta_v2" if has_typed_bars else "bar_meta",
                "datasets": [dict(row) for row in dataset_rows],
                "daily_ingestion_receipts": [dict(row) for row in receipt_rows],
                "market_bars_write_head": (
                    {"storage": "absent"}
                    if write_head_row is None
                    else dict(write_head_row)
                ),
            }
            rows_read += (
                len(dataset_rows) + len(receipt_rows) + int(write_head_row is not None)
            )
            app_evidence_complete = app_evidence_complete and has_typed_bars
        except sqlite3.OperationalError as exc:
            if (
                "no such table" not in str(exc).lower()
                and "no such column" not in str(exc).lower()
            ):
                raise PortfolioReadSnapshotRejected(
                    "persisted market-bar revision is unavailable"
                ) from exc
            try:
                with _read_only_connection(meta_path) as connection:
                    query_count += 1
                    rows = connection.execute("""
                        SELECT * FROM market_bars
                        ORDER BY symbol, frequency, timestamp
                        """).fetchall()
                bar_revision = {
                    "storage": "legacy_market_bars",
                    "rows": [dict(row) for row in rows],
                }
                rows_read += len(rows)
            except sqlite3.OperationalError as legacy_exc:
                if "no such table" not in str(legacy_exc).lower():
                    raise PortfolioReadSnapshotRejected(
                        "persisted market-bar revision is unavailable"
                    ) from legacy_exc
                bar_revision = {"storage": "empty_meta_database"}
        except (sqlite3.Error, OSError) as exc:
            raise PortfolioReadSnapshotRejected(
                "persisted market-bar revision is unavailable"
            ) from exc

    fingerprint = _json_fingerprint(
        {
            "schema_version": "karkinos.persisted_market_revision.v1",
            "app_database": app_revision,
            "bar_database": bar_revision,
        }
    )
    return _PersistedMarketRevision(
        fingerprint=fingerprint,
        evidence_complete=app_evidence_complete,
        query_count=query_count,
        rows_read=rows_read,
    )


def _legacy_market_identity() -> dict[str, str]:
    return {
        "generation_id": LEGACY_UNBOUND_MARKET_IDENTITY,
        "receipt_fingerprint": LEGACY_UNBOUND_MARKET_IDENTITY,
        "content_fingerprint": LEGACY_UNBOUND_MARKET_IDENTITY,
        "evidence_status": "legacy_incomplete",
    }


def _valuation_bound_market_identity(
    valuation: Mapping[str, Any],
    *,
    market_revision: _PersistedMarketRevision,
) -> dict[str, str]:
    """Bind current quotes and historical sources into one canonical identity.

    The valuation publication freezes the current quote set.  The persisted
    market revision covers the daily-close, quote-history, and bar datasets
    consumed by the historical matrix.  This is the production identity; no
    parallel generation repository or provider contact is involved.
    """

    metadata = valuation.get("metadata")
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("persisted_facts_only") is not True
        or not market_revision.evidence_complete
    ):
        return _legacy_market_identity()
    snapshot_id = _required_text(
        valuation.get("snapshot_id"), "valuation-bound market snapshot id"
    )
    quote_set_fingerprint = _required_text(
        valuation.get("quote_set_fingerprint"),
        "valuation-bound quote set fingerprint",
    )
    receipt_core = {
        "schema_version": "karkinos.valuation_bound_market_receipt.v1",
        "valuation_snapshot_id": snapshot_id,
        "quote_set_fingerprint": quote_set_fingerprint,
        "persisted_market_revision": market_revision.fingerprint,
        "ingestion_run_ids": sorted(
            str(value)
            for value in metadata.get("ingestion_run_ids", ())
            if str(value).strip()
        ),
    }
    content_core = {
        "schema_version": "karkinos.valuation_bound_market_generation.v1",
        "valuation_snapshot_id": snapshot_id,
        "trade_date": valuation.get("trade_date"),
        "as_of": valuation.get("as_of"),
        "quote_set_fingerprint": quote_set_fingerprint,
        "receipt": receipt_core,
    }
    return {
        "generation_id": f"persisted-market:{market_revision.fingerprint}",
        "receipt_fingerprint": _json_fingerprint(receipt_core),
        "content_fingerprint": _json_fingerprint(content_core),
        "evidence_status": (
            "complete"
            if str(valuation.get("status") or "").strip().lower() == "complete"
            else "legacy_incomplete"
        ),
    }


def _json_fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _mapping_rows(value: object, label: str) -> list[Mapping[str, Any]]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise PortfolioReadSnapshotRejected(f"{label} must be a sequence")
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise PortfolioReadSnapshotRejected(f"{label}[{index}] must be a mapping")
        rows.append(cast(Mapping[str, Any], row))
    return rows


def _matrix_date_window(
    ledger_rows: tuple[Mapping[str, Any], ...],
    *,
    valuation: Mapping[str, Any],
) -> tuple[str, str]:
    end_date = _iso_date(valuation.get("trade_date"), "valuation trade date")
    ledger_dates = [
        _iso_date(row.get("timestamp"), "ledger timestamp")
        for row in ledger_rows
        if row.get("timestamp") is not None
    ]
    start_date = min(ledger_dates, default=end_date)
    if start_date > end_date:
        raise PortfolioReadSnapshotRejected(
            "ledger timestamp is later than valuation trade date"
        )
    return start_date, end_date


def _ledger_instrument_keys(
    ledger_rows: tuple[Mapping[str, Any], ...],
) -> list[InstrumentKey]:
    keys: set[InstrumentKey] = set()
    for row in ledger_rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        raw_type = (
            row.get("instrument_type")
            or row.get("asset_type")
            or row.get("asset_class")
        )
        try:
            keys.add(InstrumentKey.from_values(symbol, raw_type))
        except (TypeError, ValueError) as exc:
            raise PortfolioReadSnapshotRejected(
                "ledger instrument identity is unavailable while building price "
                f"matrix: {symbol}"
            ) from exc
    return sorted(keys, key=lambda item: item.storage_tuple())


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioReadSnapshotRejected(f"{label} is missing")
    return value.strip()


def _required_non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise PortfolioReadSnapshotRejected(f"{label} is invalid")
    try:
        parsed = int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise PortfolioReadSnapshotRejected(f"{label} is invalid") from exc
    if parsed < 0:
        raise PortfolioReadSnapshotRejected(f"{label} is invalid")
    return parsed


def _iso_date(value: object, label: str) -> str:
    text = _required_text(value, label)
    candidate = text[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError as exc:
        raise PortfolioReadSnapshotRejected(f"{label} is invalid") from exc


__all__ = [
    "LEGACY_UNBOUND_MARKET_IDENTITY",
    "get_or_build_portfolio_read_snapshot",
    "portfolio_read_snapshot_for_state",
]
