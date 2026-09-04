"""Explicit composition seam for the valuation projection."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from server.persistence.financial_fact_event_payloads import quote_instant_storage_key
from server.persistence.financial_facts_quotes import (
    list_quote_selection_candidates_on_connection,
)


class _TransactionValuationFacts:
    """Read app-database facts through the transaction that will publish them."""

    def __init__(self, repository: Any, conn: sqlite3.Connection) -> None:
        self._repository = repository
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repository, name)

    def list_quote_selection_candidates_sync(self) -> list[dict[str, Any]]:
        return list_quote_selection_candidates_on_connection(self._conn)

    def get_latest_daily_close_before_sync(
        self,
        symbol: str,
        trade_date: str,
        instrument_type: str | None = None,
    ) -> dict[str, Any] | None:
        identity_filter = ""
        params: tuple[object, ...] = (symbol, trade_date)
        if instrument_type is not None:
            normalized = str(instrument_type).strip().lower().replace("-", "_")
            if normalized == "fund":
                normalized = "open_end_fund"
            identity_filter = "AND instrument_type = ?"
            params = (symbol, trade_date, normalized)
        rows = self._conn.execute(
            f"""
            SELECT symbol, instrument_type, trade_date, close_price, source,
                   captured_at, identity_provenance
            FROM daily_close_snapshots_v2
            WHERE symbol = ? AND trade_date < ? {identity_filter}
            ORDER BY trade_date DESC, id DESC
            LIMIT 2
            """,
            params,
        ).fetchall()
        if not rows:
            return None
        newest_date = str(rows[0]["trade_date"])
        newest = [row for row in rows if str(row["trade_date"]) == newest_date]
        if (
            instrument_type is None
            and len({str(row["instrument_type"]) for row in newest}) != 1
        ):
            return None
        result = dict(newest[0])
        result["asset_class"] = (
            "fund"
            if result["instrument_type"] == "open_end_fund"
            else result["instrument_type"]
        )
        return result

    def get_latest_quote_before_date_sync(
        self,
        symbol: str,
        trade_date: str,
        *,
        instrument_type: str,
    ) -> dict[str, Any] | None:
        normalized = str(instrument_type).strip().lower().replace("-", "_")
        if normalized == "fund":
            normalized = "open_end_fund"
        instant_upper_bound = quote_instant_storage_key(f"{trade_date}T00:00:00+08:00")
        row = self._conn.execute(
            """
            SELECT
                symbol, asset_class, instrument_type, identity_provenance,
                price, volume, timestamp,
                quote_source, provider_name, quote_status, stale_reason,
                provider_status, captured_reason, nav_date
            FROM quote_snapshots
            WHERE symbol = ? AND instrument_type = ?
              AND quote_instant_utc < ?
            ORDER BY quote_instant_utc DESC, id DESC
            LIMIT 1
            """,
            (symbol, normalized, instant_upper_bound),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_ledger_entries_sync(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM ledger_entries
            ORDER BY timestamp DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]


def _build_current_valuation_snapshot(
    repository: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Load the projection lazily at the application-persistence composition seam."""

    from server.projections.valuation_snapshot import (
        build_current_valuation_snapshot,
    )

    return build_current_valuation_snapshot(repository, **kwargs)


def build_and_persist_current_valuation_snapshot(
    repository: Any,
) -> dict[str, Any]:
    """Compatibility entry point routed through the atomic publisher."""

    publisher = getattr(repository, "publish_current_valuation_snapshot_sync", None)
    if not callable(publisher):
        raise RuntimeError("atomic valuation snapshot publication is unavailable")
    return publisher()


def build_and_publish_transaction_valuation(
    repository: Any,
    conn: sqlite3.Connection,
    *,
    candidate_ledger_rows: list[dict[str, Any]] | None = None,
    quote_fetch_run_id: str | None = None,
    valuation_policy: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Publish the valuation derived from candidate facts in the caller transaction."""

    from server.persistence.financial_facts_valuation import (
        insert_valuation_snapshot_on_connection,
        publish_valuation_control_on_connection,
    )

    frozen_now = now or repository._now(timezone.utc)
    projection_options: dict[str, Any] = {
        "persist": False,
        "candidate_ledger_rows": candidate_ledger_rows,
        "now": frozen_now,
    }
    if valuation_policy is not None:
        projection_options["valuation_policy"] = valuation_policy
    snapshot = _build_current_valuation_snapshot(
        _TransactionValuationFacts(repository, conn),
        **projection_options,
    )
    persisted_at = frozen_now.astimezone(timezone.utc).isoformat()
    insert_valuation_snapshot_on_connection(conn, snapshot, created_at=persisted_at)
    publish_valuation_control_on_connection(
        conn,
        snapshot,
        updated_at=persisted_at,
        quote_fetch_run_id=quote_fetch_run_id,
    )
    return snapshot


__all__ = [
    "build_and_persist_current_valuation_snapshot",
    "build_and_publish_transaction_valuation",
]
