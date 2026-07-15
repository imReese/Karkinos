"""Broker-neutral, explicit collector-batch ingestion without broker authority."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_adapter_release import (
    BrokerAdapterReleaseReviewRepository,
)
from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRejected,
    BrokerOrderLifecycleEvidenceRepository,
    broker_order_lifecycle_account_ref_hash,
    preview_broker_order_lifecycle_export,
)

BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_collector_batch.v1"
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_collector_preview.v1"
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION = (
    "karkinos.broker_order_lifecycle_collector_run.v1"
)
BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT = (
    "ingest_broker_order_lifecycle_collector_batch_without_execution_authority"
)
MAX_COLLECTOR_BATCH_BYTES = 4 * 1024 * 1024

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "collector_id",
        "deployment_id",
        "collector_version",
        "deployment_fingerprint",
        "release_evidence_ref",
        "release_review_status",
        "adapter_authorization_ref",
        "provider",
        "gateway_id",
        "account_id",
        "account_alias",
        "collection_mode",
        "source_contact_status",
        "connection_status",
        "batch_status",
        "cursor",
        "captured_at",
        "event_count",
        "callbacks_received",
        "duplicate_callbacks_dropped",
        "out_of_order_callbacks_dropped",
        "lifecycle",
    }
)
_CURSOR_FIELDS = frozenset({"previous", "current"})
_COLLECTION_MODES = frozenset({"callback", "poll", "replay", "fixture"})
_SOURCE_CONTACT_STATUSES = frozenset({"not_contacted", "read_only_contact", "unknown"})
_CONNECTION_STATUSES = frozenset({"connected", "disconnected", "not_applicable"})
_BATCH_STATUSES = frozenset({"complete", "partial"})
_RELEASE_REVIEW_STATUSES = frozenset({"unreviewed", "reviewed"})
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
)


class BrokerOrderLifecycleCollectorRejected(ValueError):
    """Raised when a collector run cannot be safely persisted or resumed."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def preview_broker_order_lifecycle_collector_batch(
    content: str | bytes,
    *,
    source_name: str = "",
    max_snapshot_age_seconds: int = 120,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Normalize one local collector batch without writing or contacting a broker."""

    observed_at = _aware_utc((clock or (lambda: datetime.now(UTC)))())
    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    blockers: list[str] = []
    record_blockers: list[str] = []
    text = ""
    if len(raw) > MAX_COLLECTOR_BATCH_BYTES:
        record_blockers.append("broker_order_lifecycle_collector_batch_too_large")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            record_blockers.append("broker_order_lifecycle_collector_batch_not_utf8")
    data: dict[str, Any] = {}
    if not record_blockers:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            record_blockers.append(
                "broker_order_lifecycle_collector_batch_json_invalid"
            )
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                record_blockers.append(
                    "broker_order_lifecycle_collector_batch_not_object"
                )

    if _contains_sensitive_key(data):
        record_blockers.append(
            "broker_order_lifecycle_collector_credentials_not_allowed"
        )
    _reject_unknown_fields(
        data,
        _TOP_LEVEL_FIELDS,
        "payload",
        record_blockers,
    )

    schema_version = str(data.get("schema_version") or "")
    run_id = _id(data.get("run_id"), "run_id", record_blockers)
    collector_id = _id(data.get("collector_id"), "collector_id", record_blockers)
    deployment_id = _id(
        data.get("deployment_id"),
        "deployment_id",
        record_blockers,
    )
    collector_version = _id(
        data.get("collector_version"),
        "collector_version",
        record_blockers,
    )
    deployment_fingerprint = (
        str(data.get("deployment_fingerprint") or "").strip().lower()
    )
    release_evidence_ref = _id(
        data.get("release_evidence_ref"),
        "release_evidence_ref",
        record_blockers,
    )
    adapter_authorization_ref = _id(
        data.get("adapter_authorization_ref"),
        "adapter_authorization_ref",
        record_blockers,
    )
    provider = _id(data.get("provider"), "provider", record_blockers).lower()
    gateway_id = _id(data.get("gateway_id"), "gateway_id", record_blockers)
    account_alias = _id(
        data.get("account_alias"),
        "account_alias",
        record_blockers,
    )
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        record_blockers.append("broker_order_lifecycle_collector_account_id_missing")
    if not _FINGERPRINT_PATTERN.fullmatch(deployment_fingerprint):
        record_blockers.append(
            "broker_order_lifecycle_collector_deployment_fingerprint_invalid"
        )

    release_review_status = str(data.get("release_review_status") or "").strip().lower()
    collection_mode = str(data.get("collection_mode") or "").strip().lower()
    source_contact_status = str(data.get("source_contact_status") or "").strip().lower()
    connection_status = str(data.get("connection_status") or "").strip().lower()
    batch_status = str(data.get("batch_status") or "").strip().lower()
    for value, allowed, blocker in (
        (
            release_review_status,
            _RELEASE_REVIEW_STATUSES,
            "broker_order_lifecycle_collector_release_review_status_invalid",
        ),
        (
            collection_mode,
            _COLLECTION_MODES,
            "broker_order_lifecycle_collector_collection_mode_invalid",
        ),
        (
            source_contact_status,
            _SOURCE_CONTACT_STATUSES,
            "broker_order_lifecycle_collector_source_contact_status_invalid",
        ),
        (
            connection_status,
            _CONNECTION_STATUSES,
            "broker_order_lifecycle_collector_connection_status_invalid",
        ),
        (
            batch_status,
            _BATCH_STATUSES,
            "broker_order_lifecycle_collector_batch_status_invalid",
        ),
    ):
        if value not in allowed:
            record_blockers.append(blocker)

    if schema_version != BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_SCHEMA_VERSION:
        record_blockers.append("broker_order_lifecycle_collector_schema_unsupported")

    cursor_data = data.get("cursor")
    if not isinstance(cursor_data, dict):
        record_blockers.append("broker_order_lifecycle_collector_cursor_invalid")
        cursor_data = {}
    else:
        _reject_unknown_fields(
            cursor_data,
            _CURSOR_FIELDS,
            "cursor",
            record_blockers,
        )
    cursor_previous = _nonnegative_int(
        cursor_data.get("previous"),
        "cursor_previous",
        record_blockers,
    )
    cursor_current = _nonnegative_int(
        cursor_data.get("current"),
        "cursor_current",
        record_blockers,
    )
    if cursor_current <= 0 or cursor_current != cursor_previous + 1:
        record_blockers.append(
            "broker_order_lifecycle_collector_cursor_not_consecutive"
        )

    event_count = _nonnegative_int(
        data.get("event_count"),
        "event_count",
        record_blockers,
    )
    callbacks_received = _nonnegative_int(
        data.get("callbacks_received"),
        "callbacks_received",
        record_blockers,
    )
    duplicate_callbacks_dropped = _nonnegative_int(
        data.get("duplicate_callbacks_dropped"),
        "duplicate_callbacks_dropped",
        record_blockers,
    )
    out_of_order_callbacks_dropped = _nonnegative_int(
        data.get("out_of_order_callbacks_dropped"),
        "out_of_order_callbacks_dropped",
        record_blockers,
    )
    if duplicate_callbacks_dropped + out_of_order_callbacks_dropped > (
        callbacks_received
    ):
        record_blockers.append(
            "broker_order_lifecycle_collector_callback_counts_invalid"
        )

    accepted_callback_count = (
        callbacks_received
        - duplicate_callbacks_dropped
        - out_of_order_callbacks_dropped
    )
    if collection_mode in {"callback", "poll"}:
        if source_contact_status != "read_only_contact":
            blockers.append(
                "broker_order_lifecycle_collector_live_source_contact_not_read_only"
            )
        if release_review_status != "reviewed":
            blockers.append(
                "broker_order_lifecycle_collector_adapter_release_not_reviewed"
            )
    elif collection_mode in {"replay", "fixture"}:
        if source_contact_status != "not_contacted":
            blockers.append(
                "broker_order_lifecycle_collector_offline_mode_contact_invalid"
            )
        if connection_status != "not_applicable":
            blockers.append(
                "broker_order_lifecycle_collector_offline_connection_status_invalid"
            )
    if source_contact_status == "unknown":
        blockers.append("broker_order_lifecycle_collector_source_contact_unknown")
    if collection_mode == "callback" and event_count != accepted_callback_count:
        blockers.append(
            "broker_order_lifecycle_collector_callback_event_count_mismatch"
        )
    if collection_mode != "callback" and any(
        (
            callbacks_received,
            duplicate_callbacks_dropped,
            out_of_order_callbacks_dropped,
        )
    ):
        blockers.append(
            "broker_order_lifecycle_collector_callback_telemetry_mode_mismatch"
        )

    captured_at = _timestamp(data.get("captured_at"))
    if not captured_at:
        record_blockers.append("broker_order_lifecycle_collector_captured_at_invalid")

    if connection_status == "disconnected":
        blockers.append("broker_order_lifecycle_collector_disconnected")
    if collection_mode in {"callback", "poll"} and connection_status != "connected":
        blockers.append("broker_order_lifecycle_collector_live_source_not_connected")
    if batch_status == "partial":
        blockers.append("broker_order_lifecycle_collector_partial_batch")
    if batch_status == "complete" and event_count != 1:
        blockers.append(
            "broker_order_lifecycle_collector_complete_batch_event_count_invalid"
        )

    lifecycle_data = data.get("lifecycle")
    lifecycle_preview: dict[str, Any] = {}
    if isinstance(lifecycle_data, dict):
        lifecycle_preview = preview_broker_order_lifecycle_export(
            json.dumps(
                lifecycle_data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            source_name=_sanitized_source_name(source_name),
            max_snapshot_age_seconds=max_snapshot_age_seconds,
            clock=lambda: observed_at,
        )
        for field, expected in (
            ("provider", provider),
            ("gateway_id", gateway_id),
            ("account_alias", account_alias),
            ("captured_at", captured_at),
            ("source_sequence", cursor_current),
        ):
            if lifecycle_preview.get(field) != expected:
                blockers.append(
                    f"broker_order_lifecycle_collector_lifecycle_{field}_mismatch"
                )
        expected_account_hash = broker_order_lifecycle_account_ref_hash(
            account_id, provider=provider
        )
        if lifecycle_preview.get("account_ref_hash") != expected_account_hash:
            blockers.append(
                "broker_order_lifecycle_collector_lifecycle_account_mismatch"
            )
        blockers.extend(str(item) for item in lifecycle_preview.get("blockers") or [])
    elif batch_status == "complete":
        blockers.append("broker_order_lifecycle_collector_lifecycle_missing")

    account_ref_hash = str(
        lifecycle_preview.get("account_ref_hash") or ""
    ) or broker_order_lifecycle_account_ref_hash(account_id, provider=provider)
    unique_record_blockers = list(dict.fromkeys(record_blockers))
    unique_blockers = list(dict.fromkeys([*record_blockers, *blockers]))
    recordable = bool(
        not unique_record_blockers
        and all(
            (
                run_id,
                collector_id,
                deployment_id,
                collector_version,
                deployment_fingerprint,
                release_evidence_ref,
                adapter_authorization_ref,
                provider,
                gateway_id,
                account_alias,
                account_ref_hash,
                captured_at,
            )
        )
    )
    core = {
        "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "collector_id": collector_id,
        "deployment_id": deployment_id,
        "collector_version": collector_version,
        "deployment_fingerprint": deployment_fingerprint,
        "release_evidence_ref": release_evidence_ref,
        "release_review_status": release_review_status,
        "adapter_authorization_ref": adapter_authorization_ref,
        "provider": provider,
        "gateway_id": gateway_id,
        "account_alias": account_alias,
        "account_ref_hash": account_ref_hash,
        "collection_mode": collection_mode,
        "source_contact_status": source_contact_status,
        "connection_status": connection_status,
        "batch_status": batch_status,
        "cursor_previous": cursor_previous,
        "cursor_current": cursor_current,
        "captured_at": captured_at,
        "event_count": event_count,
        "callbacks_received": callbacks_received,
        "duplicate_callbacks_dropped": duplicate_callbacks_dropped,
        "out_of_order_callbacks_dropped": out_of_order_callbacks_dropped,
        "lifecycle_evidence_fingerprint": str(
            lifecycle_preview.get("evidence_fingerprint") or ""
        ),
        "blockers": unique_blockers,
    }
    batch_fingerprint = _fingerprint(core)
    evidence_core = dict(core)
    evidence_core.pop("run_id")
    evidence_fingerprint = _fingerprint(evidence_core)
    return {
        **core,
        "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION,
        "batch_fingerprint": batch_fingerprint,
        "evidence_fingerprint": evidence_fingerprint,
        "file_fingerprint": hashlib.sha256(raw).hexdigest(),
        "source_name": _sanitized_source_name(source_name),
        "observed_at": observed_at.isoformat(),
        "max_snapshot_age_seconds": max(
            30,
            min(int(max_snapshot_age_seconds), 3600),
        ),
        "validation_status": "pass" if not unique_blockers else "blocked",
        "recordable": recordable,
        "ready_to_advance_cursor": recordable and not unique_blockers,
        "record_blockers": unique_record_blockers,
        "prepared_lifecycle_preview": lifecycle_preview,
        **_safety_flags(),
    }


class BrokerOrderLifecycleCollectorRepository:
    """Persist collector runs and advance one broker-neutral cursor fail-closed."""

    def __init__(
        self,
        path: str | Path,
        *,
        ensure_schema: bool = True,
    ) -> None:
        self._path = Path(path)
        if ensure_schema:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()
            BrokerOrderLifecycleEvidenceRepository(self._path)

    def ingest(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Prepare and commit one batch; a prepared run is restart-replayable."""

        prepared = self.prepare(
            preview,
            acknowledgement=acknowledgement,
        )
        if prepared["run_status"] != "prepared":
            return prepared
        return self.commit_prepared(str(prepared["run_id"]))

    def prepare(
        self,
        preview: dict[str, Any],
        *,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Persist a sanitized preview before lifecycle evidence is committed."""

        if acknowledgement != (BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT):
            raise BrokerOrderLifecycleCollectorRejected(
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
            raise BrokerOrderLifecycleCollectorRejected(
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
            raise BrokerOrderLifecycleCollectorRejected(
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
                    raise BrokerOrderLifecycleCollectorRejected(
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
            raise BrokerOrderLifecycleCollectorRejected(
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

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS broker_order_lifecycle_collector_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    scope_key TEXT NOT NULL,
                    batch_fingerprint TEXT NOT NULL,
                    evidence_fingerprint TEXT NOT NULL,
                    file_fingerprint TEXT NOT NULL,
                    collector_id TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    collector_version TEXT NOT NULL,
                    deployment_fingerprint TEXT NOT NULL,
                    release_evidence_ref TEXT NOT NULL,
                    release_review_status TEXT NOT NULL,
                    adapter_authorization_ref TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    gateway_id TEXT NOT NULL,
                    account_alias TEXT NOT NULL,
                    account_ref_hash TEXT NOT NULL,
                    collection_mode TEXT NOT NULL,
                    source_contact_status TEXT NOT NULL,
                    connection_status TEXT NOT NULL,
                    batch_status TEXT NOT NULL,
                    cursor_previous INTEGER NOT NULL,
                    cursor_current INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    run_status TEXT NOT NULL CHECK(run_status IN (
                        'prepared', 'recorded', 'duplicate', 'blocked'
                    )),
                    blockers_json TEXT NOT NULL DEFAULT '[]',
                    lifecycle_observation_id TEXT NOT NULL DEFAULT '',
                    prepared_preview_json TEXT NOT NULL DEFAULT '{}',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    source_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_lifecycle_collector_scope_cursor
                ON broker_order_lifecycle_collector_runs(
                    scope_key, cursor_current DESC, id DESC
                );

                CREATE TABLE IF NOT EXISTS broker_order_lifecycle_collector_state (
                    scope_key TEXT PRIMARY KEY,
                    collector_id TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    collector_version TEXT NOT NULL,
                    deployment_fingerprint TEXT NOT NULL,
                    release_evidence_ref TEXT NOT NULL,
                    release_review_status TEXT NOT NULL,
                    adapter_authorization_ref TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    gateway_id TEXT NOT NULL,
                    account_alias TEXT NOT NULL,
                    account_ref_hash TEXT NOT NULL,
                    last_cursor INTEGER NOT NULL,
                    last_run_id TEXT NOT NULL,
                    last_batch_fingerprint TEXT NOT NULL,
                    last_lifecycle_observation_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """)
            conn.commit()


def _preview_integrity_blockers(preview: dict[str, Any]) -> list[str]:
    core_fields = (
        "schema_version",
        "run_id",
        "collector_id",
        "deployment_id",
        "collector_version",
        "deployment_fingerprint",
        "release_evidence_ref",
        "release_review_status",
        "adapter_authorization_ref",
        "provider",
        "gateway_id",
        "account_alias",
        "account_ref_hash",
        "collection_mode",
        "source_contact_status",
        "connection_status",
        "batch_status",
        "cursor_previous",
        "cursor_current",
        "captured_at",
        "event_count",
        "callbacks_received",
        "duplicate_callbacks_dropped",
        "out_of_order_callbacks_dropped",
        "lifecycle_evidence_fingerprint",
        "blockers",
    )
    core = {field: preview.get(field) for field in core_fields}
    core["schema_version"] = BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION
    blockers: list[str] = []
    if str(preview.get("batch_fingerprint") or "") != _fingerprint(core):
        blockers.append("broker_order_lifecycle_collector_preview_fingerprint_drift")
    evidence_core = dict(core)
    evidence_core.pop("run_id")
    if str(preview.get("evidence_fingerprint") or "") != _fingerprint(evidence_core):
        blockers.append(
            "broker_order_lifecycle_collector_preview_evidence_fingerprint_drift"
        )
    for field, expected in _safety_flags().items():
        if preview.get(field) is not expected:
            blockers.append(
                f"broker_order_lifecycle_collector_preview_safety_drift:{field}"
            )
    return blockers


def _rejection(preview: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
        "status": "rejected",
        "run_id": str(preview.get("run_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        **_safety_flags(),
    }


def _scope_key(value: dict[str, Any]) -> str:
    return _fingerprint(
        {
            "provider": str(value.get("provider") or ""),
            "gateway_id": str(value.get("gateway_id") or ""),
            "account_alias": str(value.get("account_alias") or ""),
        }
    )


def _collector_release_binding(value: sqlite3.Row) -> dict[str, Any]:
    return {
        field: value[field]
        for field in (
            "release_evidence_ref",
            "collector_id",
            "deployment_id",
            "collector_version",
            "deployment_fingerprint",
            "provider",
            "gateway_id",
            "account_alias",
            "adapter_authorization_ref",
            "collection_mode",
        )
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "explicit_ingestion_required": True,
        "provider_contacted": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_fills": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "does_not_release_submission_interlock": True,
        "authorizes_execution": False,
        "default_registered": False,
    }


def _id(value: Any, field: str, blockers: list[str]) -> str:
    normalized = str(value or "").strip()
    if not _ID_PATTERN.fullmatch(normalized):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
    return normalized


def _nonnegative_int(value: Any, field: str, blockers: list[str]) -> int:
    if isinstance(value, bool):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
        return 0
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
        return 0
    if normalized < 0 or str(value).strip() != str(normalized):
        blockers.append(f"broker_order_lifecycle_collector_{field}_invalid")
    return max(0, normalized)


def _timestamp(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    return parsed.astimezone(UTC).isoformat()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
            or _contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _reject_unknown_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    prefix: str,
    blockers: list[str],
) -> None:
    for key in sorted(set(value) - allowed):
        blockers.append(
            f"broker_order_lifecycle_collector_{prefix}_field_unsupported:{key}"
        )


def _sanitized_source_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or "/" in name or "\\" in name:
        return "broker order lifecycle collector batch"
    return name[:128]


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
