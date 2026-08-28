"""Checkpointed reconciliation for the current persisted quote materialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from server.contracts.quote_ingestion import (
    quote_authority_conflict_fields,
    quote_timestamp_instant,
)
from server.persistence.financial_fact_event_payloads import quote_instant_storage_key

_STATE_TABLE = "quote_current_materialization_state"


@dataclass(frozen=True, slots=True)
class QuoteCurrentMaterializationState:
    """Checkpoint and account-valuation revision of the current quote view."""

    snapshot_cutoff_id: int
    revision: int
    updated_at: str


def assert_quote_current_materialization_on_connection(
    conn: sqlite3.Connection,
) -> QuoteCurrentMaterializationState:
    """Return the state only when every audit snapshot has been materialized."""

    state = _read_state(conn)
    if state is None:
        raise RuntimeError("quote current materialization state is missing")
    maximum_snapshot_id = _maximum_snapshot_id(conn)
    if state.snapshot_cutoff_id != maximum_snapshot_id:
        raise RuntimeError(
            "quote current materialization checkpoint does not cover audit history"
        )
    return state


def current_quote_revision_on_connection(conn: sqlite3.Connection) -> int:
    """Return the complete account-valuation quote revision, or fail closed."""

    return assert_quote_current_materialization_on_connection(conn).revision


def increment_quote_current_revision_on_connection(
    conn: sqlite3.Connection,
    *,
    updated_at: str,
) -> QuoteCurrentMaterializationState:
    """Record one latest-only account-valuation quote change.

    The caller must already have established that the authoritative current row
    changed and that its asset class participates in account valuation. Index-only
    market context must not increment this revision.
    """

    _require_updated_at(updated_at)
    state = assert_quote_current_materialization_on_connection(conn)
    conn.execute(
        f"""
        UPDATE {_STATE_TABLE}
        SET revision = revision + 1, updated_at = ?
        WHERE singleton_id = 1
        """,
        (updated_at,),
    )
    return _require_updated_state(conn, expected_revision=state.revision + 1)


def advance_quote_snapshot_checkpoint_on_connection(
    conn: sqlite3.Connection,
    *,
    snapshot_id: int,
    current_changed: bool,
    updated_at: str,
) -> QuoteCurrentMaterializationState:
    """Advance through exactly one newly materialized audit snapshot.

    ``current_changed`` means that the authoritative current quote changed for an
    asset class used by account valuation. An index-only change advances the audit
    cutoff without invalidating an account valuation publication.
    """

    _require_updated_at(updated_at)
    state = _read_state(conn)
    if state is None:
        raise RuntimeError("quote current materialization state is missing")
    target = int(snapshot_id)
    if target <= state.snapshot_cutoff_id:
        raise RuntimeError("quote snapshot checkpoint must advance monotonically")
    maximum_snapshot_id = _maximum_snapshot_id(conn)
    if target != maximum_snapshot_id:
        raise RuntimeError("quote snapshot checkpoint must advance to audit head")
    skipped = conn.execute(
        """
        SELECT id
        FROM quote_snapshots
        WHERE id > ? AND id < ?
        ORDER BY id
        LIMIT 1
        """,
        (state.snapshot_cutoff_id, target),
    ).fetchone()
    if skipped is not None:
        raise RuntimeError(
            "quote snapshot checkpoint cannot skip unreconciled audit history"
        )
    exists = conn.execute(
        "SELECT 1 FROM quote_snapshots WHERE id = ?",
        (target,),
    ).fetchone()
    if exists is None:
        raise RuntimeError("quote snapshot checkpoint target is missing")
    revision = state.revision + int(bool(current_changed))
    conn.execute(
        f"""
        UPDATE {_STATE_TABLE}
        SET snapshot_cutoff_id = ?, revision = ?, updated_at = ?
        WHERE singleton_id = 1
        """,
        (target, revision, updated_at),
    )
    return _require_updated_state(
        conn,
        expected_cutoff_id=target,
        expected_revision=revision,
    )


def reconcile_quote_current_materialization_on_connection(
    conn: sqlite3.Connection,
    *,
    updated_at: str,
) -> QuoteCurrentMaterializationState:
    """Apply only audit rows after the checkpoint to ``latest_quotes``.

    For each instrument, only its newest pending instant can affect current state.
    Conflicts at superseded instants are ignored; conflicting authority facts at
    the final newest instant fail closed before any checkpoint is advanced.
    """

    _require_updated_at(updated_at)
    prior = _read_state(conn)
    cutoff_id = prior.snapshot_cutoff_id if prior is not None else 0
    revision = prior.revision if prior is not None else 0
    maximum_snapshot_id = _maximum_snapshot_id(conn)
    if cutoff_id > maximum_snapshot_id:
        raise RuntimeError("quote current materialization checkpoint is invalid")

    pending = _fetchall_dicts(
        conn,
        """
        SELECT
            id, symbol, asset_class, price, volume, timestamp, created_at,
            quote_source, provider_name, quote_status, stale_reason,
            provider_status, captured_reason, nav_date, fetch_run_id,
            quote_instant_utc
        FROM quote_snapshots
        WHERE id > ?
        ORDER BY id
        """,
        (cutoff_id,),
    )
    if not pending:
        if prior is None:
            _insert_state(
                conn,
                snapshot_cutoff_id=0,
                revision=0,
                updated_at=updated_at,
            )
        return assert_quote_current_materialization_on_connection(conn)

    frontiers = _pending_frontiers(pending)
    changes: list[dict[str, Any]] = []
    account_current_changed = False
    for identity in sorted(frontiers):
        newest_pending = frontiers[identity]
        current = _fetchone_dict(
            conn,
            """
            SELECT *
            FROM latest_quotes
            WHERE symbol = ? AND asset_type = ?
            LIMIT 1
            """,
            identity,
        )
        pending_instant = _observation_instant(newest_pending[0])
        current_instant = _observation_instant(current) if current is not None else None
        if current_instant is not None and current_instant > pending_instant:
            continue

        conflict_candidates: list[Mapping[str, Any]] = list(newest_pending)
        if current is not None and current_instant == pending_instant:
            conflict_candidates.append(current)
        _assert_no_authority_conflict(identity, pending_instant, conflict_candidates)

        if current is not None and current_instant == pending_instant:
            continue
        selected = max(newest_pending, key=lambda row: int(row["id"]))
        changes.append(selected)
        if identity[1].strip().lower() != "index":
            account_current_changed = True

    for snapshot in changes:
        _upsert_latest_from_snapshot(conn, snapshot, updated_at=updated_at)

    new_revision = revision + int(account_current_changed)
    if prior is None:
        _insert_state(
            conn,
            snapshot_cutoff_id=maximum_snapshot_id,
            revision=new_revision,
            updated_at=updated_at,
        )
    else:
        conn.execute(
            f"""
            UPDATE {_STATE_TABLE}
            SET snapshot_cutoff_id = ?, revision = ?, updated_at = ?
            WHERE singleton_id = 1
            """,
            (maximum_snapshot_id, new_revision, updated_at),
        )
    return _require_updated_state(
        conn,
        expected_cutoff_id=maximum_snapshot_id,
        expected_revision=new_revision,
    )


def _pending_frontiers(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        expected_key = quote_instant_storage_key(row["timestamp"])
        if row.get("quote_instant_utc") != expected_key:
            raise RuntimeError("quote snapshot canonical instant is invalid")
        identity = (str(row["symbol"]), str(row["asset_class"]))
        grouped.setdefault(identity, []).append(row)

    frontiers: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for identity, observations in grouped.items():
        newest_instant = max(_observation_instant(row) for row in observations)
        frontiers[identity] = [
            row for row in observations if _observation_instant(row) == newest_instant
        ]
    return frontiers


def _assert_no_authority_conflict(
    identity: tuple[str, str],
    instant: Any,
    candidates: list[Mapping[str, Any]],
) -> None:
    baseline = candidates[0]
    conflicts: set[str] = set()
    for candidate in candidates[1:]:
        conflicts.update(quote_authority_conflict_fields(baseline, candidate))
    if conflicts:
        raise ValueError(
            "quote authority facts conflict at the newest timestamp "
            f"for {identity[0]}/{identity[1]} at {instant.isoformat()}: "
            + ",".join(sorted(conflicts))
        )


def _upsert_latest_from_snapshot(
    conn: sqlite3.Connection,
    snapshot: Mapping[str, Any],
    *,
    updated_at: str,
) -> None:
    quote_status = snapshot.get("quote_status") or "live"
    conn.execute(
        """
        INSERT INTO latest_quotes (
            symbol, asset_type, price, previous_close, change,
            change_percent, volume, turnover, quote_timestamp,
            quote_source, provider_name, provider_status, quote_status,
            stale_reason, captured_at, captured_reason, nav_date,
            fetch_run_id, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, NULL, NULL, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  NULL, ?, ?)
        ON CONFLICT(symbol, asset_type) DO UPDATE SET
            price = excluded.price,
            previous_close = NULL,
            change = NULL,
            change_percent = NULL,
            volume = excluded.volume,
            turnover = NULL,
            quote_timestamp = excluded.quote_timestamp,
            quote_source = excluded.quote_source,
            provider_name = excluded.provider_name,
            provider_status = excluded.provider_status,
            quote_status = excluded.quote_status,
            stale_reason = excluded.stale_reason,
            captured_at = excluded.captured_at,
            captured_reason = excluded.captured_reason,
            nav_date = excluded.nav_date,
            fetch_run_id = excluded.fetch_run_id,
            metadata_json = NULL,
            updated_at = excluded.updated_at
        """,
        (
            snapshot["symbol"],
            snapshot["asset_class"],
            snapshot["price"],
            snapshot.get("volume"),
            snapshot["timestamp"],
            snapshot.get("quote_source"),
            snapshot.get("provider_name"),
            snapshot.get("provider_status"),
            quote_status,
            snapshot.get("stale_reason"),
            snapshot["created_at"],
            snapshot.get("captured_reason"),
            snapshot.get("nav_date"),
            snapshot.get("fetch_run_id"),
            snapshot["created_at"],
            updated_at,
        ),
    )


def _observation_instant(row: Mapping[str, Any]) -> Any:
    raw = row.get("timestamp") or row.get("quote_timestamp")
    instant = quote_timestamp_instant(raw)
    if not str(raw or "").strip() or instant.year <= 1:
        raise RuntimeError("quote current materialization timestamp is invalid")
    return instant


def _read_state(
    conn: sqlite3.Connection,
) -> QuoteCurrentMaterializationState | None:
    row = conn.execute(f"""
        SELECT snapshot_cutoff_id, revision, updated_at
        FROM {_STATE_TABLE}
        WHERE singleton_id = 1
        LIMIT 1
        """).fetchone()
    if row is None:
        return None
    cutoff_id = int(row[0])
    revision = int(row[1])
    updated_at = str(row[2])
    if cutoff_id < 0 or revision < 0 or not updated_at.strip():
        raise RuntimeError("quote current materialization state is invalid")
    return QuoteCurrentMaterializationState(cutoff_id, revision, updated_at)


def _insert_state(
    conn: sqlite3.Connection,
    *,
    snapshot_cutoff_id: int,
    revision: int,
    updated_at: str,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {_STATE_TABLE} (
            singleton_id, snapshot_cutoff_id, revision, updated_at
        ) VALUES (1, ?, ?, ?)
        """,
        (snapshot_cutoff_id, revision, updated_at),
    )


def _maximum_snapshot_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM quote_snapshots").fetchone()
    return int(row[0]) if row is not None else 0


def _require_updated_state(
    conn: sqlite3.Connection,
    *,
    expected_cutoff_id: int | None = None,
    expected_revision: int | None = None,
) -> QuoteCurrentMaterializationState:
    state = assert_quote_current_materialization_on_connection(conn)
    if (
        expected_cutoff_id is not None
        and state.snapshot_cutoff_id != expected_cutoff_id
    ):
        raise RuntimeError("quote current materialization cutoff update failed")
    if expected_revision is not None and state.revision != expected_revision:
        raise RuntimeError("quote current materialization revision update failed")
    return state


def _require_updated_at(updated_at: str) -> None:
    if not str(updated_at).strip():
        raise ValueError("quote current materialization updated_at is required")


def _fetchone_dict(
    conn: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...],
) -> dict[str, Any] | None:
    cursor = conn.execute(query, parameters)
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_dict(cursor, row)


def _fetchall_dicts(
    conn: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...],
) -> list[dict[str, Any]]:
    cursor = conn.execute(query, parameters)
    return [_row_dict(cursor, row) for row in cursor.fetchall()]


def _row_dict(cursor: sqlite3.Cursor, row: Any) -> dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return {
        str(column[0]): value
        for column, value in zip(cursor.description or (), row, strict=True)
    }


__all__ = [
    "QuoteCurrentMaterializationState",
    "advance_quote_snapshot_checkpoint_on_connection",
    "assert_quote_current_materialization_on_connection",
    "current_quote_revision_on_connection",
    "increment_quote_current_revision_on_connection",
    "reconcile_quote_current_materialization_on_connection",
]
