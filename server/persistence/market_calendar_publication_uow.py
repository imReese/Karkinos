"""Atomic publication of verified market-calendar evidence and its audit run."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from server.contracts.market_calendar import MarketCalendarAutomationPublication
from server.persistence.automation_runs import upsert_automation_run_in_transaction
from server.persistence.connection import SQLiteRepository
from server.persistence.market_calendar import (
    bind_market_calendar_verification,
    upsert_market_calendar_snapshot_in_transaction,
)


class MarketCalendarPublicationUnitOfWork(SQLiteRepository):
    """Commit one calendar publication aggregate with no partial visibility."""

    def publish_sync(
        self,
        command: MarketCalendarAutomationPublication,
    ) -> dict[str, Any]:
        now = self._now().isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM automation_runs WHERE run_id = ? LIMIT 1",
                (str(command.run["run_id"]),),
            ).fetchone()
            if existing is not None:
                _require_exact_run_replay(dict(existing), command.run)
                conn.commit()
                return {"run": dict(existing), "snapshot": None, "replayed": True}

            snapshot_row = None
            if command.snapshot is not None:
                assert command.verification is not None
                payload = bind_market_calendar_verification(
                    dict(command.snapshot),
                    command.verification,
                    verified_at=now,
                )
                snapshot_row = upsert_market_calendar_snapshot_in_transaction(
                    conn,
                    payload,
                    now=now,
                    preserve_same_evidence_review=False,
                )
            run = upsert_automation_run_in_transaction(
                conn,
                command.run,
                now=now,
            )
            conn.commit()
            return {"run": run, "snapshot": snapshot_row, "replayed": False}


def _require_exact_run_replay(
    existing: dict[str, Any],
    requested: dict[str, Any],
) -> None:
    expected_payload = json.dumps(
        dict(requested.get("payload") or {}),
        ensure_ascii=False,
        sort_keys=True,
    )
    fields = (
        (existing.get("run_id"), requested.get("run_id")),
        (existing.get("run_type"), requested.get("run_type")),
        (existing.get("run_date"), requested.get("run_date")),
        (existing.get("status"), requested.get("status")),
        (existing.get("execution_mode"), requested.get("execution_mode")),
        (existing.get("started_at"), requested.get("started_at")),
        (existing.get("finished_at"), requested.get("finished_at")),
        (existing.get("source_ref"), requested.get("source_ref")),
        (existing.get("payload_json"), expected_payload),
    )
    if any(str(actual or "") != str(expected or "") for actual, expected in fields):
        raise ValueError("market calendar automation run idempotency conflict")


__all__ = ["MarketCalendarPublicationUnitOfWork"]
