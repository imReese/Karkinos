"""Atomic staging and publication for quote-ingestion batches."""

from __future__ import annotations

import json
import sqlite3
from datetime import timezone
from typing import Any

from core.types import InstrumentKey
from server.contracts.quote_ingestion import (
    PUBLISHED_QUOTE_RUN_STATUSES,
    DailyCloseEvidenceConflict,
    QuoteIngestionCommand,
    quote_authority_conflict_fields,
    validate_quote_authority_time,
)
from server.persistence.database_normalization import stable_json_fingerprint
from server.persistence.database_serialization import serialize_metadata_json
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_fact_event_payloads import (
    latest_quote_event_payload,
    quote_instant_storage_key,
    quote_observation_rank,
)
from server.persistence.quote_current_materialization import (
    advance_quote_snapshot_checkpoint_on_connection,
)
from server.persistence.valuation_publication_recovery import quote_run_scope


class QuoteIngestionUnitOfWorkMixin:
    """Stage provider results and publish all derived facts in one transaction."""

    def persist_quote_ingestion_sync(
        self,
        command: QuoteIngestionCommand,
    ) -> dict[str, Any]:
        now = self._now(timezone.utc).isoformat()
        validate_quote_authority_time(
            quote_timestamp=command.quote_timestamp,
            authority_timestamp=command.captured_at or now,
        )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            if command.fetch_run_id:
                result = _stage_quote(conn, command, staged_at=now)
            else:
                result = _materialize_quote(conn, command, materialized_at=now)
                self._valuation_transaction_writer(conn)
            conn.commit()
            return result

    def staged_quote_ingestions_sync(
        self,
        run_id: str,
    ) -> list[QuoteIngestionCommand]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            return _load_staged_quotes(conn, run_id)

    def publish_quote_fetch_run_sync(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int,
        failure_count: int,
        cache_hit_count: int,
        error_message: str | None,
        metadata: dict[str, Any] | str | None,
    ) -> dict[str, Any]:
        """Atomically materialize staged facts, valuation, and terminal run state."""

        if status not in PUBLISHED_QUOTE_RUN_STATUSES or failure_count != 0:
            raise ValueError("only publishable quote-run statuses may be materialized")
        now = self._now(timezone.utc).isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            run = _require_running_quote_run(conn, run_id)
            staged = _load_staged_quotes(conn, run_id)
            if len(staged) != success_count or len(staged) != run["symbol_count"]:
                raise RuntimeError(
                    "staged quote count does not match successful quote count"
                )
            expected = quote_run_scope(conn, run_id)
            actual = {
                (key.instrument_type.value, key.symbol)
                for command in staged
                for key in [
                    InstrumentKey.from_values(command.symbol, command.asset_type)
                ]
            }
            if expected is not None and actual != {tuple(key) for key in expected}:
                raise ValueError("quote publication requested scope mismatch")
            close_binding = _daily_close_batch_binding(
                conn, staged, run_id=run_id, scope=expected
            )
            try:
                for command in staged:
                    _materialize_quote(conn, command, materialized_at=now)
            except DailyCloseEvidenceConflict as exc:
                raise DailyCloseEvidenceConflict(close_binding) from exc
            valuation_snapshot = self._valuation_transaction_writer(
                conn,
                quote_fetch_run_id=run_id,
            )
            metadata_value = _metadata_dict(metadata)
            metadata_value.update(
                {
                    "valuation_snapshot_id": valuation_snapshot["snapshot_id"],
                    "valuation_snapshot_status": valuation_snapshot["status"],
                }
            )
            row = _finish_quote_run(
                conn,
                run=run,
                finished_at=finished_at,
                status=status,
                success_count=success_count,
                failure_count=failure_count,
                cache_hit_count=cache_hit_count,
                error_message=error_message,
                metadata=metadata_value,
            )
            conn.commit()
            return row


def _stage_quote(
    conn: sqlite3.Connection,
    command: QuoteIngestionCommand,
    *,
    staged_at: str,
) -> dict[str, Any]:
    run_id = str(command.fetch_run_id or "")
    _require_running_quote_run(conn, run_id)
    payload = command.to_dict()
    payload_json = serialize_metadata_json(payload) or "{}"
    fingerprint = stable_json_fingerprint(payload)
    existing = conn.execute(
        """
        SELECT * FROM quote_ingestion_items
        WHERE run_id = ? AND symbol = ? AND asset_type = ?
        LIMIT 1
        """,
        (run_id, command.symbol, command.asset_type),
    ).fetchone()
    if existing is not None:
        if str(existing["payload_fingerprint"]) != fingerprint:
            raise ValueError("quote ingestion idempotency conflict")
        return dict(existing)
    cursor = conn.execute(
        """
        INSERT INTO quote_ingestion_items (
            run_id, symbol, asset_type, payload_json,
            payload_fingerprint, staged_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            command.symbol,
            command.asset_type,
            payload_json,
            fingerprint,
            staged_at,
        ),
    )
    row = conn.execute(
        "SELECT * FROM quote_ingestion_items WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RuntimeError("quote ingestion staging failed")
    return dict(row)


def _require_running_quote_run(
    conn: sqlite3.Connection,
    run_id: str,
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM quote_fetch_runs WHERE run_id = ? LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError("quote fetch run not found")
    if str(row["status"]) != "running" or row["finished_at"] is not None:
        raise RuntimeError("quote fetch run is not open for ingestion")
    return row


def _load_staged_quotes(
    conn: sqlite3.Connection,
    run_id: str,
) -> list[QuoteIngestionCommand]:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM quote_ingestion_items
        WHERE run_id = ?
        ORDER BY symbol ASC, asset_type ASC, id ASC
        """,
        (run_id,),
    ).fetchall()
    return [
        QuoteIngestionCommand.from_dict(json.loads(row["payload_json"])) for row in rows
    ]


def _materialize_quote(
    conn: sqlite3.Connection,
    command: QuoteIngestionCommand,
    *,
    materialized_at: str,
) -> dict[str, Any]:
    existing_snapshot = None
    inserted_snapshot_id: int | None = None
    if command.fetch_run_id:
        existing_snapshot = conn.execute(
            """
            SELECT * FROM quote_snapshots
            WHERE fetch_run_id = ? AND symbol = ? AND instrument_type = ?
            LIMIT 1
            """,
            (command.fetch_run_id, command.symbol, command.asset_type),
        ).fetchone()
    if existing_snapshot is None:
        cursor = conn.execute(
            """
            INSERT INTO quote_snapshots (
                symbol, asset_class, price, volume, timestamp, created_at,
                quote_source, provider_name, quote_status, stale_reason,
                provider_status, captured_reason, nav_date, fetch_run_id,
                quote_instant_utc, instrument_type, identity_provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                command.symbol,
                command.asset_type,
                command.price,
                command.volume,
                command.quote_timestamp,
                materialized_at,
                command.quote_source,
                command.provider_name,
                command.quote_status,
                command.stale_reason,
                command.provider_status,
                command.captured_reason,
                command.nav_date,
                command.fetch_run_id,
                quote_instant_storage_key(command.quote_timestamp),
                command.asset_type,
                command.identity_provenance,
            ),
        )
        snapshot_id = int(cursor.lastrowid or 0)
        inserted_snapshot_id = snapshot_id
        insert_event_sync(
            conn,
            event_type="market.quote.snapshot.recorded",
            timestamp=command.quote_timestamp,
            entity_type="instrument",
            entity_id=command.symbol,
            source="quote_snapshots",
            source_ref=str(snapshot_id),
            payload={**command.valuation_row(), "snapshot_id": snapshot_id},
        )

    metadata = {
        **command.metadata,
        "source": command.source,
        "display_name": command.display_name,
        "previous_close_date": command.previous_close_date,
    }
    identity_aliases = _quote_identity_aliases(command.asset_type)
    placeholders = ", ".join("?" for _ in identity_aliases)
    existing_latest = conn.execute(
        f"""
        SELECT * FROM latest_quotes
        WHERE symbol = ? AND asset_type IN ({placeholders})
        ORDER BY quote_timestamp DESC, updated_at DESC, id DESC
        LIMIT 1
        """,
        (command.symbol, *identity_aliases),
    ).fetchone()
    candidate_rank = quote_observation_rank(
        {"quote_timestamp": command.quote_timestamp}
    )[0]
    existing_rank = (
        quote_observation_rank(dict(existing_latest))[0]
        if existing_latest is not None
        else None
    )
    if existing_rank is not None and existing_rank == candidate_rank:
        conflict_fields = quote_authority_conflict_fields(
            dict(existing_latest),
            command.to_dict(),
        )
        if conflict_fields:
            raise ValueError(
                "quote authority facts conflict at the same timestamp: "
                + ",".join(conflict_fields)
            )
    if existing_rank is not None and existing_rank > candidate_rank:
        if inserted_snapshot_id is not None:
            advance_quote_snapshot_checkpoint_on_connection(
                conn,
                snapshot_id=inserted_snapshot_id,
                current_changed=False,
                updated_at=materialized_at,
            )
        _materialize_daily_close(conn, command, materialized_at=materialized_at)
        return dict(existing_latest)

    conn.execute(
        """
        INSERT INTO latest_quotes (
            symbol, asset_type, price, previous_close, change,
            change_percent, volume, turnover, quote_timestamp,
            quote_source, provider_name, provider_status, quote_status,
            stale_reason, captured_at, captured_reason, nav_date,
            fetch_run_id, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, asset_type) DO UPDATE SET
            price = excluded.price,
            previous_close = excluded.previous_close,
            change = excluded.change,
            change_percent = excluded.change_percent,
            volume = excluded.volume,
            turnover = excluded.turnover,
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
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            command.symbol,
            command.asset_type,
            command.price,
            command.previous_close,
            command.change,
            command.change_percent,
            command.volume,
            command.turnover,
            command.quote_timestamp,
            command.quote_source,
            command.provider_name,
            command.provider_status,
            command.quote_status,
            command.stale_reason,
            command.captured_at or materialized_at,
            command.captured_reason,
            command.nav_date,
            command.fetch_run_id,
            serialize_metadata_json(metadata),
            materialized_at,
            materialized_at,
        ),
    )
    latest = conn.execute(
        "SELECT * FROM latest_quotes WHERE symbol = ? AND asset_type = ?",
        (command.symbol, command.asset_type),
    ).fetchone()
    if latest is None:
        raise RuntimeError("latest quote materialization failed")
    insert_event_sync(
        conn,
        event_type="market.quote.refreshed",
        timestamp=command.quote_timestamp,
        entity_type="instrument",
        entity_id=command.symbol,
        source="latest_quotes",
        source_ref=str(latest["id"]),
        payload=latest_quote_event_payload(latest),
    )
    if inserted_snapshot_id is not None:
        advance_quote_snapshot_checkpoint_on_connection(
            conn,
            snapshot_id=inserted_snapshot_id,
            current_changed=command.asset_type.strip().lower() != "index",
            updated_at=materialized_at,
        )
    _materialize_daily_close(conn, command, materialized_at=materialized_at)
    _materialize_instrument_metadata(conn, command, materialized_at=materialized_at)
    return dict(latest)


def _materialize_daily_close(
    conn: sqlite3.Connection,
    command: QuoteIngestionCommand,
    *,
    materialized_at: str,
) -> None:
    if command.daily_close_price is None or command.daily_close_date is None:
        return
    existing = _existing_daily_close(conn, command)
    if existing is not None:
        if _daily_close_conflicts(existing, command):
            raise DailyCloseEvidenceConflict()
        return
    conn.execute(
        """
        INSERT INTO daily_close_snapshots_v2
            (symbol, instrument_type, trade_date, close_price, source,
             captured_at, identity_provenance)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, instrument_type, trade_date) DO UPDATE SET
            close_price = excluded.close_price,
            source = excluded.source,
            captured_at = excluded.captured_at,
            identity_provenance = excluded.identity_provenance
        """,
        (
            command.symbol,
            command.asset_type,
            command.daily_close_date,
            command.daily_close_price,
            command.daily_close_source or "reported_previous_close",
            materialized_at,
            command.identity_provenance,
        ),
    )


def _existing_daily_close(conn: sqlite3.Connection, command: QuoteIngestionCommand):
    return conn.execute(
        """
        SELECT *
        FROM daily_close_snapshots_v2
        WHERE symbol = ? AND instrument_type = ? AND trade_date = ?
        LIMIT 1
        """,
        (command.symbol, command.asset_type, command.daily_close_date),
    ).fetchone()


def _daily_close_conflicts(existing, command: QuoteIngestionCommand) -> bool:
    return (
        float(existing["close_price"]) != float(command.daily_close_price)
        or not _same_instrument_identity(
            str(existing["instrument_type"]),
            command.asset_type,
        )
        or str(existing["source"])
        != (command.daily_close_source or "reported_previous_close")
    )


def _daily_close_batch_binding(conn, staged, *, run_id, scope) -> dict[str, Any]:
    required_facts = []
    manifest = []
    for command in staged:
        fingerprint = stable_json_fingerprint(command.to_dict())
        manifest.append(
            {
                "symbol": command.symbol,
                "instrument_type": command.asset_type,
                "payload_fingerprint": fingerprint,
            }
        )
        if command.daily_close_date is None:
            continue
        existing = _existing_daily_close(conn, command)
        required_facts.append(
            {
                "fact_kind": "daily_close",
                "symbol": command.symbol,
                "instrument_type": command.asset_type,
                "session": command.daily_close_date,
                "candidate": {
                    "close_price": command.daily_close_price,
                    "source": command.daily_close_source or "reported_previous_close",
                    "payload_fingerprint": fingerprint,
                },
                "existing": dict(existing) if existing is not None else None,
                "conflicting": existing is not None
                and _daily_close_conflicts(existing, command),
            }
        )
    return {
        "schema_version": "karkinos.daily_close_conflict.v1",
        "run_id": run_id,
        "requested_scope": scope,
        "staged_items": manifest,
        "required_facts": required_facts,
    }


def _quote_identity_aliases(instrument_type: str) -> tuple[str, ...]:
    if instrument_type == "open_end_fund":
        return ("open_end_fund", "fund")
    return (instrument_type,)


def _same_instrument_identity(left: str, right: str) -> bool:
    return bool(
        set(_quote_identity_aliases(left)) & set(_quote_identity_aliases(right))
    )


def _materialize_instrument_metadata(
    conn: sqlite3.Connection,
    command: QuoteIngestionCommand,
    *,
    materialized_at: str,
) -> None:
    display_name = str(command.display_name or "").strip()
    if not display_name:
        return
    conn.execute(
        """
        INSERT INTO instrument_metadata (
            symbol, asset_type, display_name, provider_symbol, exchange,
            market, provider_name, source, fetched_at, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, asset_type) DO UPDATE SET
            display_name = excluded.display_name,
            provider_symbol = excluded.provider_symbol,
            exchange = excluded.exchange,
            market = excluded.market,
            provider_name = excluded.provider_name,
            source = excluded.source,
            fetched_at = excluded.fetched_at,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            command.symbol,
            command.asset_type,
            display_name,
            command.provider_symbol or command.symbol,
            command.exchange,
            command.market,
            command.provider_name,
            "quote",
            command.quote_timestamp,
            serialize_metadata_json(
                {
                    "source": command.source,
                    "quote_source": command.quote_source,
                    "identity_provenance": command.identity_provenance,
                }
            ),
            materialized_at,
            materialized_at,
        ),
    )


def _finish_quote_run(
    conn: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    finished_at: str,
    status: str,
    success_count: int,
    failure_count: int,
    cache_hit_count: int,
    error_message: str | None,
    metadata: dict[str, Any] | str | None,
) -> dict[str, Any]:
    metadata_json = serialize_metadata_json(metadata)
    conn.execute(
        """
        UPDATE quote_fetch_runs
        SET finished_at = ?, status = ?, success_count = ?, failure_count = ?,
            cache_hit_count = ?, error_message = ?, metadata_json = ?
        WHERE run_id = ?
        """,
        (
            finished_at,
            status,
            success_count,
            failure_count,
            cache_hit_count,
            error_message,
            metadata_json,
            run["run_id"],
        ),
    )
    row = conn.execute(
        "SELECT * FROM quote_fetch_runs WHERE run_id = ?", (run["run_id"],)
    ).fetchone()
    if row is None:
        raise RuntimeError("quote fetch run completion failed")
    insert_event_sync(
        conn,
        event_type="task_run.completed",
        timestamp=finished_at,
        entity_type="task_run",
        entity_id=str(run["run_id"]),
        source="quote_fetch_runs",
        source_ref=str(run["run_id"]),
        payload={
            "run_id": row["run_id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "trigger": row["trigger"],
            "provider": row["provider"],
            "asset_type": row["asset_type"],
            "symbol_count": row["symbol_count"],
            "success_count": row["success_count"],
            "failure_count": row["failure_count"],
            "cache_hit_count": row["cache_hit_count"],
            "status": row["status"],
            "error_message": row["error_message"],
            "metadata": _metadata_dict(metadata),
        },
    )
    return dict(row)


def _metadata_dict(value: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


__all__ = ["PUBLISHED_QUOTE_RUN_STATUSES", "QuoteIngestionUnitOfWorkMixin"]
