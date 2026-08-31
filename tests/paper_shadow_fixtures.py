"""Test-only paper-shadow evidence fixtures; never a production write API."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def insert_paper_shadow_evidence(
    db: Any,
    *,
    run_id: str,
    plan_date: str,
    input_fingerprint: str,
    status: str,
    order_intent_count: int,
    simulated_order_count: int,
    simulated_fill_count: int,
    divergence_status: str,
    next_manual_review_step: str,
    limitations: list[str] | None = None,
    payload: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Insert a historical source row for read-path and corruption tests."""

    now = datetime.now(timezone.utc).isoformat()
    payload_json = payload if isinstance(payload, str) else json.dumps(payload or {})
    with sqlite3.connect(db._path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO paper_shadow_runs (
                run_id, plan_date, input_fingerprint, status,
                order_intent_count, simulated_order_count, simulated_fill_count,
                divergence_status, next_manual_review_step, limitations_json,
                payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                plan_date,
                input_fingerprint,
                status,
                order_intent_count,
                simulated_order_count,
                simulated_fill_count,
                divergence_status,
                next_manual_review_step,
                json.dumps(limitations or []),
                payload_json,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM paper_shadow_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("paper-shadow fixture was not inserted")
    return dict(row)


__all__ = ["insert_paper_shadow_evidence"]
