"""Valuation snapshot persistence capability."""

from __future__ import annotations

import sqlite3
from datetime import timezone
from typing import Any

from server.persistence.database_support import serialize_metadata_json
from server.persistence.financial_facts_valuation_composition import (
    build_and_persist_current_valuation_snapshot,
)


class ValuationFactsRepositoryMixin:
    def save_valuation_snapshot_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable, content-addressed valuation snapshot."""
        now = self._now(timezone.utc).isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT OR IGNORE INTO valuation_snapshots (
                    snapshot_id, as_of, trade_date, valuation_policy,
                    ledger_cutoff_id, ledger_fingerprint, quote_set_fingerprint,
                    status, quotes_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["snapshot_id"],
                    payload["as_of"],
                    payload["trade_date"],
                    payload["valuation_policy"],
                    int(payload.get("ledger_cutoff_id") or 0),
                    payload["ledger_fingerprint"],
                    payload["quote_set_fingerprint"],
                    payload["status"],
                    serialize_metadata_json(payload.get("quotes") or []),
                    serialize_metadata_json(payload.get("metadata") or {}),
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
                (payload["snapshot_id"],),
            ).fetchone()
            if row is None:
                raise RuntimeError("valuation snapshot persistence failed")
            return dict(row)

    def publish_current_valuation_snapshot_sync(self) -> dict[str, Any]:
        """Build and persist the immutable snapshot for committed facts."""
        snapshot = build_and_persist_current_valuation_snapshot(self)
        self._runtime_controls.set_value(
            "valuation_snapshot_publication",
            {
                "status": "ready",
                "snapshot_id": snapshot["snapshot_id"],
                "as_of": snapshot["as_of"],
            },
        )
        return snapshot

    def get_valuation_snapshot_sync(self, snapshot_id: str) -> dict[str, Any] | None:
        """Read one immutable valuation snapshot by content id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            return dict(row) if row else None


__all__ = ["ValuationFactsRepositoryMixin"]
