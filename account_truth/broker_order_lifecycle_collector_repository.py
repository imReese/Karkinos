"""Read repository for persisted lifecycle collector runs and cursor state."""

from __future__ import annotations

import sqlite3
from typing import Any

from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_fingerprint as _fingerprint,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_json_list as _json_list,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_json_object as _json_object,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_safety_flags as _safety_flags,
)


class BrokerOrderLifecycleCollectorReadRepositoryMixin:
    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read persisted collector runs only; never create an absent database."""

        if not self._path.exists() or not self._table_exists(
            "broker_order_lifecycle_collector_runs"
        ):
            return []
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    ORDER BY id DESC LIMIT ?
                    """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [self._run_response(row, reused=False) for row in rows]

    def get_state(
        self,
        *,
        provider: str,
        gateway_id: str,
        account_alias: str,
    ) -> dict[str, Any]:
        """Read one persisted cursor state without provider contact."""

        if not self._path.exists() or not self._table_exists(
            "broker_order_lifecycle_collector_state"
        ):
            return {"status": "not_configured", **_safety_flags()}
        scope_key = _fingerprint(
            {
                "provider": str(provider or ""),
                "gateway_id": str(gateway_id or ""),
                "account_alias": str(account_alias or ""),
            }
        )
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_state
                    WHERE scope_key = ? LIMIT 1
                    """,
                (scope_key,),
            ).fetchone()
        if row is None:
            return {"status": "not_found", **_safety_flags()}
        return {
            "status": "found",
            "scope_key": str(row["scope_key"]),
            "collector_id": str(row["collector_id"]),
            "deployment_id": str(row["deployment_id"]),
            "collector_version": str(row["collector_version"]),
            "deployment_fingerprint": str(row["deployment_fingerprint"]),
            "release_evidence_ref": str(row["release_evidence_ref"]),
            "release_review_status": str(row["release_review_status"]),
            "adapter_authorization_ref": str(row["adapter_authorization_ref"]),
            "provider": str(row["provider"]),
            "gateway_id": str(row["gateway_id"]),
            "account_alias": str(row["account_alias"]),
            "account_ref_hash": str(row["account_ref_hash"]),
            "last_cursor": int(row["last_cursor"]),
            "last_run_id": str(row["last_run_id"]),
            "last_batch_fingerprint": str(row["last_batch_fingerprint"]),
            "last_lifecycle_observation_id": str(row["last_lifecycle_observation_id"]),
            "updated_at": str(row["updated_at"]),
            **_safety_flags(),
        }

    def _run_response(
        self,
        row: sqlite3.Row,
        *,
        reused: bool,
    ) -> dict[str, Any]:
        payload = _json_object(row["payload_json"])
        return {
            "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
            "run_id": str(row["run_id"]),
            "scope_key": str(row["scope_key"]),
            "collector_id": str(row["collector_id"]),
            "deployment_id": str(row["deployment_id"]),
            "collector_version": str(row["collector_version"]),
            "deployment_fingerprint": str(row["deployment_fingerprint"]),
            "release_evidence_ref": str(row["release_evidence_ref"]),
            "release_review_status": str(row["release_review_status"]),
            "adapter_authorization_ref": str(row["adapter_authorization_ref"]),
            "provider": str(row["provider"]),
            "gateway_id": str(row["gateway_id"]),
            "account_alias": str(row["account_alias"]),
            "account_ref_hash": str(row["account_ref_hash"]),
            "collection_mode": str(row["collection_mode"]),
            "source_contact_status": str(row["source_contact_status"]),
            "connection_status": str(row["connection_status"]),
            "batch_status": str(row["batch_status"]),
            "cursor_previous": int(row["cursor_previous"]),
            "cursor_current": int(row["cursor_current"]),
            "captured_at": str(row["captured_at"]),
            "observed_at": str(row["observed_at"]),
            "event_count": int(row["event_count"]),
            "run_status": str(row["run_status"]),
            "validation_status": (
                "pass"
                if str(row["run_status"]) in {"recorded", "duplicate"}
                else str(row["run_status"])
            ),
            "blockers": _json_list(row["blockers_json"]),
            "lifecycle_observation_id": str(row["lifecycle_observation_id"]),
            "batch_fingerprint": str(row["batch_fingerprint"]),
            "evidence_fingerprint": str(row["evidence_fingerprint"]),
            "file_fingerprint": str(row["file_fingerprint"]),
            "source_name": str(row["source_name"]),
            "callbacks_received": int(payload.get("callbacks_received") or 0),
            "duplicate_callbacks_dropped": int(
                payload.get("duplicate_callbacks_dropped") or 0
            ),
            "out_of_order_callbacks_dropped": int(
                payload.get("out_of_order_callbacks_dropped") or 0
            ),
            "persisted": True,
            "reused": reused,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            **_safety_flags(),
        }

    def _table_exists(self, table: str) -> bool:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            return row is not None
