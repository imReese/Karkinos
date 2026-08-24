"""SQLite repository for automation policies, claims, and run records."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from server.persistence.connection import DateTimeNow, SQLiteRepository
from server.persistence.database_support import (
    account_truth_review_identity_from_connection,
    action_task_event_payload,
    apply_manual_confirmation_readiness,
    controlled_broker_submit_rejection,
    controlled_lifecycle_invalidated_clearance_rows,
    controlled_session_authority_rejection,
    controlled_session_budget_rejection,
    controlled_session_gate_snapshot_rejection,
    controlled_session_pause_rejection,
    controlled_session_rate_admission_rejection,
    controlled_submission_clearance_rejection,
    controlled_submission_ledger_correction_rejection,
    controlled_submission_ledger_posting_rejection,
    decimal_values_equal,
    event_log_response,
    event_matches_signal_journal_entry,
    fill_event_payload,
    json_dict,
    json_list,
    latest_quote_event_payload,
    latest_signal_journal_event,
    manual_order_event_payload,
    metadata_payload_value,
    normalize_timestamp,
    order_event_payload,
    paper_shadow_run_review_next_step,
    quote_observation_rank,
    risk_decision_journal_response,
    serialize_metadata_json,
    stable_json_fingerprint,
    validate_paper_shadow_run_review_transition,
    verify_controlled_ledger_entry,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)

logger = logging.getLogger(__name__)


class AutomationRunRepository(SQLiteRepository):
    """Own automation policies, claims, and run records."""

    def get_automation_policy_sync(self, policy_id: str) -> dict[str, Any] | None:
        """Read one persisted automation policy by ID."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM automation_policies
                WHERE policy_id = ?
                LIMIT 1
                """,
                (policy_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload_json"])
            return {
                **payload,
                "policy_id": row["policy_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
            }

    def upsert_automation_policy_sync(
        self,
        *,
        policy_id: str,
        payload: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        """Persist an automation policy snapshot."""
        now = self._now().isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM automation_policies
                WHERE policy_id = ?
                LIMIT 1
                """,
                (policy_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO automation_policies (
                    policy_id, payload_json, created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (policy_id, payload_json, created_at, now, updated_by),
            )
            conn.commit()
        saved = self.get_automation_policy_sync(policy_id)
        if saved is None:
            raise RuntimeError("automation policy was not saved")
        return saved

    def upsert_automation_run_sync(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist or update an automation run audit record."""
        now = self._now().isoformat()
        payload = dict(run.get("payload") or {})
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        run_id = str(run["run_id"])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM automation_runs
                WHERE run_id = ?
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO automation_runs (
                    run_id, run_type, run_date, status, execution_mode,
                    started_at, finished_at, source_ref, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_type = excluded.run_type,
                    run_date = excluded.run_date,
                    status = excluded.status,
                    execution_mode = excluded.execution_mode,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    source_ref = excluded.source_ref,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    str(run["run_type"]),
                    str(run["run_date"]),
                    str(run["status"]),
                    str(run["execution_mode"]),
                    str(run.get("started_at") or now),
                    run.get("finished_at"),
                    run.get("source_ref"),
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def get_automation_run_sync(self, run_id: str) -> dict[str, Any] | None:
        """Read one automation run audit record."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def claim_daily_candidate_background_attempt_sync(
        self,
        *,
        run_date: str,
        claimed_at: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically claim one fail-closed background attempt per market date."""
        return self.claim_automation_run_once_sync(
            run_id=f"automation:daily-candidate-background-attempt:{run_date}",
            run_type="daily_candidate_background_attempt",
            run_date=run_date,
            claimed_at=claimed_at,
            execution_mode="paper_shadow",
            payload=payload,
        )

    def claim_automation_run_once_sync(
        self,
        *,
        run_id: str,
        run_type: str,
        run_date: str,
        claimed_at: str,
        execution_mode: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically claim one exact automation run identity."""

        normalized = {
            "run_id": str(run_id).strip(),
            "run_type": str(run_type).strip(),
            "run_date": str(run_date).strip(),
            "claimed_at": str(claimed_at).strip(),
            "execution_mode": str(execution_mode).strip(),
        }
        if not all(normalized.values()):
            raise ValueError("automation run claim identity is incomplete")
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        now = self._now().isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO automation_runs (
                    run_id, run_type, run_date, status, execution_mode,
                    started_at, finished_at, source_ref, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized["run_id"],
                    normalized["run_type"],
                    normalized["run_date"],
                    "claimed",
                    normalized["execution_mode"],
                    normalized["claimed_at"],
                    None,
                    None,
                    payload_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM automation_runs WHERE run_id = ?",
                (normalized["run_id"],),
            ).fetchone()
            conn.commit()
            if row is None:
                raise RuntimeError("automation run was not claimed")
            if (
                str(row["run_type"]) != normalized["run_type"]
                or str(row["run_date"]) != normalized["run_date"]
                or str(row["execution_mode"]) != normalized["execution_mode"]
            ):
                raise RuntimeError("automation run claim identity conflict")
            return {"claimed": cursor.rowcount == 1, "run": dict(row)}

    def list_automation_runs_sync(
        self,
        *,
        run_type: str | None = None,
        run_date: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent automation run audit records."""
        conditions: list[str] = []
        params: list[Any] = []
        if run_type is not None:
            conditions.append("run_type = ?")
            params.append(run_type)
        if run_date is not None:
            conditions.append("run_date = ?")
            params.append(run_date)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([int(limit), int(offset)])
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM automation_runs
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_all_automation_runs_for_type_sync(
        self,
        *,
        run_type: str,
    ) -> list[dict[str, Any]]:
        """Read a complete run-type history from one database snapshot.

        This is intentionally separate from the bounded operational listing:
        evidence-window consumers must not silently turn an old, valid trial
        into a truncated one when the installation passes a UI page limit.
        """
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM automation_runs
                WHERE run_type = ?
                ORDER BY run_date ASC, updated_at ASC, created_at ASC
                """,
                (run_type,),
            ).fetchall()
            return [dict(row) for row in rows]
