"""Atomic prepare and commit unit of work for lifecycle collector batches."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from account_truth.broker_adapter_release import (
    BrokerAdapterReleaseReviewRepository,
)
from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRejected,
    BrokerOrderLifecycleEvidenceRepository,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
)
from account_truth.broker_order_lifecycle_collector_projection import (
    broker_order_lifecycle_collector_release_binding as _collector_release_binding,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_json as _json,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_json_object as _json_object,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_preview_integrity_blockers as _preview_integrity_blockers,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_rejection_evidence as _rejection,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_safety_flags as _safety_flags,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_scope_key as _scope_key,
)


class BrokerOrderLifecycleCollectorUnitOfWorkMixin:
    def prepare(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Persist a sanitized preview before lifecycle evidence is committed."""

        if acknowledgement != (BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT):
            raise self._collector_rejection(
                "collector acknowledgement mismatch",
                evidence=_rejection(
                    preview,
                    ["broker_order_lifecycle_collector_acknowledgement_mismatch"],
                ),
            )
        if str(
            preview.get("schema_version") or ""
        ) != BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION or not bool(
            preview.get("recordable")
        ):
            raise self._collector_rejection(
                "collector preview is not safely recordable",
                evidence=_rejection(
                    preview,
                    [
                        "broker_order_lifecycle_collector_preview_not_recordable",
                        *[str(item) for item in preview.get("record_blockers") or []],
                    ],
                ),
            )
        integrity_blockers = _preview_integrity_blockers(preview)
        if integrity_blockers:
            raise self._collector_rejection(
                "collector preview integrity invalid",
                evidence=_rejection(preview, integrity_blockers),
            )

        release_review = BrokerAdapterReleaseReviewRepository(
            self._path,
            ensure_schema=False,
        ).verify_collector_binding(preview)

        now = datetime.now(UTC).isoformat()
        run_id = str(preview["run_id"])
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    WHERE run_id = ? LIMIT 1
                    """,
                (run_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["batch_fingerprint"]) != str(
                    preview["batch_fingerprint"]
                ):
                    conn.rollback()
                    raise self._collector_rejection(
                        "collector run id was reused with different evidence",
                        evidence=_rejection(
                            preview,
                            ["broker_order_lifecycle_collector_run_id_conflict"],
                        ),
                    )
                conn.commit()
                return self._run_response(existing, reused=True)

            blockers = [
                *[str(item) for item in preview.get("blockers") or []],
                *[str(item) for item in release_review.get("blockers") or []],
            ]
            scope_key = _scope_key(preview)
            state = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_state
                    WHERE scope_key = ? LIMIT 1
                    """,
                (scope_key,),
            ).fetchone()
            expected_previous = self._expected_previous_cursor(
                conn,
                preview,
                state=state,
            )
            if state is not None:
                if str(state["account_ref_hash"]) != str(preview["account_ref_hash"]):
                    blockers.append(
                        "broker_order_lifecycle_collector_account_identity_changed"
                    )
                for field in (
                    "collector_id",
                    "deployment_id",
                    "collector_version",
                    "deployment_fingerprint",
                    "release_evidence_ref",
                    "adapter_authorization_ref",
                ):
                    if str(state[field]) != str(preview[field]):
                        blockers.append(
                            f"broker_order_lifecycle_collector_{field}_changed"
                        )

            prior_cursor = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    WHERE scope_key = ? AND cursor_current = ?
                      AND run_status IN ('recorded', 'duplicate')
                    ORDER BY id DESC LIMIT 1
                    """,
                (scope_key, int(preview["cursor_current"])),
            ).fetchone()
            run_status = "prepared"
            lifecycle_observation_id = ""
            if prior_cursor is not None:
                if str(prior_cursor["evidence_fingerprint"]) == str(
                    preview["evidence_fingerprint"]
                ):
                    run_status = "duplicate"
                    lifecycle_observation_id = str(
                        prior_cursor["lifecycle_observation_id"]
                    )
                else:
                    blockers.append(
                        "broker_order_lifecycle_collector_cursor_evidence_conflict"
                    )
            elif int(preview["cursor_previous"]) < expected_previous:
                blockers.append("broker_order_lifecycle_collector_cursor_out_of_order")
            elif int(preview["cursor_previous"]) > expected_previous:
                blockers.append("broker_order_lifecycle_collector_cursor_gap")

            claimed = conn.execute(
                """
                    SELECT run_id FROM broker_order_lifecycle_collector_runs
                    WHERE scope_key = ? AND cursor_current = ?
                      AND run_status = 'prepared'
                    LIMIT 1
                    """,
                (scope_key, int(preview["cursor_current"])),
            ).fetchone()
            if claimed is not None:
                blockers.append(
                    "broker_order_lifecycle_collector_cursor_already_prepared"
                )
            blockers = list(dict.fromkeys(blockers))
            if blockers:
                run_status = "blocked"

            prepared_preview = (
                preview.get("prepared_lifecycle_preview") or {}
                if run_status == "prepared"
                else {}
            )
            payload = {
                "schema_version": (BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION),
                "validation_status": (
                    "pass" if run_status in {"prepared", "recorded"} else run_status
                ),
                "blockers": blockers,
                "expected_previous_cursor": expected_previous,
                "callbacks_received": int(preview["callbacks_received"]),
                "duplicate_callbacks_dropped": int(
                    preview["duplicate_callbacks_dropped"]
                ),
                "out_of_order_callbacks_dropped": int(
                    preview["out_of_order_callbacks_dropped"]
                ),
                **_safety_flags(),
            }
            conn.execute(
                """
                    INSERT INTO broker_order_lifecycle_collector_runs (
                        run_id, scope_key, batch_fingerprint, evidence_fingerprint,
                        file_fingerprint, collector_id, deployment_id,
                        collector_version, deployment_fingerprint,
                        release_evidence_ref, release_review_status,
                        adapter_authorization_ref, provider, gateway_id,
                        account_alias, account_ref_hash, collection_mode,
                        source_contact_status, connection_status, batch_status,
                        cursor_previous, cursor_current, captured_at, observed_at,
                        event_count, run_status, blockers_json,
                        lifecycle_observation_id, prepared_preview_json,
                        payload_json, source_name, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                (
                    run_id,
                    scope_key,
                    str(preview["batch_fingerprint"]),
                    str(preview["evidence_fingerprint"]),
                    str(preview["file_fingerprint"]),
                    str(preview["collector_id"]),
                    str(preview["deployment_id"]),
                    str(preview["collector_version"]),
                    str(preview["deployment_fingerprint"]),
                    str(preview["release_evidence_ref"]),
                    str(preview["release_review_status"]),
                    str(preview["adapter_authorization_ref"]),
                    str(preview["provider"]),
                    str(preview["gateway_id"]),
                    str(preview["account_alias"]),
                    str(preview["account_ref_hash"]),
                    str(preview["collection_mode"]),
                    str(preview["source_contact_status"]),
                    str(preview["connection_status"]),
                    str(preview["batch_status"]),
                    int(preview["cursor_previous"]),
                    int(preview["cursor_current"]),
                    str(preview["captured_at"]),
                    str(preview["observed_at"]),
                    int(preview["event_count"]),
                    run_status,
                    _json(blockers),
                    lifecycle_observation_id,
                    _json(prepared_preview),
                    _json(payload),
                    str(preview["source_name"]),
                    now,
                    now,
                ),
            )
            saved = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    WHERE run_id = ? LIMIT 1
                    """,
                (run_id,),
            ).fetchone()
            conn.commit()
            if saved is None:
                raise RuntimeError("collector run was not persisted")
            return self._run_response(saved, reused=False)

    def commit_prepared(self, run_id: str) -> dict[str, Any]:
        """Replay a prepared preview and atomically advance its collector cursor."""

        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    WHERE run_id = ? LIMIT 1
                    """,
                (str(run_id or ""),),
            ).fetchone()
        if row is None:
            raise self._collector_rejection(
                "prepared collector run not found",
                evidence=_rejection(
                    {"run_id": str(run_id or "")},
                    ["broker_order_lifecycle_collector_prepared_run_not_found"],
                ),
            )
        if str(row["run_status"]) != "prepared":
            return self._run_response(row, reused=True)

        release_review = BrokerAdapterReleaseReviewRepository(
            self._path,
            ensure_schema=False,
        ).verify_collector_binding(_collector_release_binding(row))
        if release_review.get("blockers"):
            return self._finalize_blocked(
                str(row["run_id"]),
                [
                    "broker_order_lifecycle_collector_adapter_release_review_blocked",
                    *[str(item) for item in release_review.get("blockers") or []],
                ],
            )

        lifecycle_preview = _json_object(row["prepared_preview_json"])
        try:
            lifecycle = BrokerOrderLifecycleEvidenceRepository(self._path).record(
                lifecycle_preview,
                acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
            )
        except BrokerOrderLifecycleEvidenceRejected as exc:
            return self._finalize_blocked(
                str(row["run_id"]),
                [
                    "broker_order_lifecycle_collector_lifecycle_record_rejected",
                    *[str(item) for item in exc.evidence.get("blockers") or []],
                ],
            )
        if str(lifecycle.get("validation_status") or "") != "pass":
            return self._finalize_blocked(
                str(row["run_id"]),
                [
                    "broker_order_lifecycle_collector_lifecycle_evidence_blocked",
                    *[str(item) for item in lifecycle.get("blockers") or []],
                ],
                lifecycle_observation_id=str(lifecycle.get("observation_id") or ""),
            )

        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    WHERE run_id = ? LIMIT 1
                    """,
                (str(row["run_id"]),),
            ).fetchone()
            if current is None:
                conn.rollback()
                raise RuntimeError("prepared collector run disappeared")
            if str(current["run_status"]) != "prepared":
                conn.commit()
                return self._run_response(current, reused=True)
            state = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_state
                    WHERE scope_key = ? LIMIT 1
                    """,
                (str(current["scope_key"]),),
            ).fetchone()
            expected_previous = self._expected_previous_cursor_from_run(
                conn,
                current,
                state=state,
            )
            if int(current["cursor_previous"]) != expected_previous:
                conn.rollback()
                return self._finalize_blocked(
                    str(current["run_id"]),
                    ["broker_order_lifecycle_collector_cursor_changed_during_commit"],
                    lifecycle_observation_id=str(lifecycle.get("observation_id") or ""),
                )
            conn.execute(
                """
                    INSERT INTO broker_order_lifecycle_collector_state (
                        scope_key, collector_id, deployment_id, collector_version,
                        deployment_fingerprint, release_evidence_ref,
                        release_review_status, adapter_authorization_ref, provider,
                        gateway_id, account_alias, account_ref_hash, last_cursor,
                        last_run_id, last_batch_fingerprint,
                        last_lifecycle_observation_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scope_key) DO UPDATE SET
                        collector_id = excluded.collector_id,
                        deployment_id = excluded.deployment_id,
                        collector_version = excluded.collector_version,
                        deployment_fingerprint = excluded.deployment_fingerprint,
                        release_evidence_ref = excluded.release_evidence_ref,
                        release_review_status = excluded.release_review_status,
                        adapter_authorization_ref = excluded.adapter_authorization_ref,
                        provider = excluded.provider,
                        gateway_id = excluded.gateway_id,
                        account_alias = excluded.account_alias,
                        account_ref_hash = excluded.account_ref_hash,
                        last_cursor = excluded.last_cursor,
                        last_run_id = excluded.last_run_id,
                        last_batch_fingerprint = excluded.last_batch_fingerprint,
                        last_lifecycle_observation_id =
                            excluded.last_lifecycle_observation_id,
                        updated_at = excluded.updated_at
                    """,
                (
                    str(current["scope_key"]),
                    str(current["collector_id"]),
                    str(current["deployment_id"]),
                    str(current["collector_version"]),
                    str(current["deployment_fingerprint"]),
                    str(current["release_evidence_ref"]),
                    str(current["release_review_status"]),
                    str(current["adapter_authorization_ref"]),
                    str(current["provider"]),
                    str(current["gateway_id"]),
                    str(current["account_alias"]),
                    str(current["account_ref_hash"]),
                    int(current["cursor_current"]),
                    str(current["run_id"]),
                    str(current["batch_fingerprint"]),
                    str(lifecycle.get("observation_id") or ""),
                    now,
                ),
            )
            conn.execute(
                """
                    UPDATE broker_order_lifecycle_collector_runs
                    SET run_status = 'recorded', blockers_json = '[]',
                        lifecycle_observation_id = ?, prepared_preview_json = '{}',
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                (
                    str(lifecycle.get("observation_id") or ""),
                    now,
                    str(current["run_id"]),
                ),
            )
            saved = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    WHERE run_id = ? LIMIT 1
                    """,
                (str(current["run_id"]),),
            ).fetchone()
            conn.commit()
            if saved is None:
                raise RuntimeError("collector run finalization failed")
            return self._run_response(saved, reused=bool(lifecycle.get("reused")))

    def _expected_previous_cursor(
        self,
        conn: sqlite3.Connection,
        preview: dict[str, Any],
        *,
        state: sqlite3.Row | None,
    ) -> int:
        if state is not None:
            return int(state["last_cursor"])
        return self._latest_lifecycle_sequence(
            conn,
            provider=str(preview["provider"]),
            gateway_id=str(preview["gateway_id"]),
            account_alias=str(preview["account_alias"]),
        )

    def _expected_previous_cursor_from_run(
        self,
        conn: sqlite3.Connection,
        run: sqlite3.Row,
        *,
        state: sqlite3.Row | None,
    ) -> int:
        if state is not None:
            return int(state["last_cursor"])
        latest = self._latest_lifecycle_sequence(
            conn,
            provider=str(run["provider"]),
            gateway_id=str(run["gateway_id"]),
            account_alias=str(run["account_alias"]),
        )
        if latest == int(run["cursor_current"]):
            return int(run["cursor_previous"])
        return latest

    @staticmethod
    def _latest_lifecycle_sequence(
        conn: sqlite3.Connection,
        *,
        provider: str,
        gateway_id: str,
        account_alias: str,
    ) -> int:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "broker_order_lifecycle_observations" not in tables:
            return 0
        row = conn.execute(
            """
                SELECT MAX(source_sequence)
                FROM broker_order_lifecycle_observations
                WHERE provider = ? AND gateway_id = ? AND account_alias = ?
                  AND validation_status = 'pass'
                """,
            (provider, gateway_id, account_alias),
        ).fetchone()
        return int(row[0] or 0)

    def _finalize_blocked(
        self,
        run_id: str,
        blockers: list[str],
        *,
        lifecycle_observation_id: str = "",
    ) -> dict[str, Any]:
        unique_blockers = list(dict.fromkeys(blockers))
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                    UPDATE broker_order_lifecycle_collector_runs
                    SET run_status = 'blocked', blockers_json = ?,
                        lifecycle_observation_id = ?, prepared_preview_json = '{}',
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                (
                    _json(unique_blockers),
                    lifecycle_observation_id,
                    now,
                    run_id,
                ),
            )
            row = conn.execute(
                """
                    SELECT * FROM broker_order_lifecycle_collector_runs
                    WHERE run_id = ? LIMIT 1
                    """,
                (run_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("blocked collector run finalization failed")
        return self._run_response(row, reused=False)
