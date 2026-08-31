"""Provider-evidence preview for one broker lifecycle collector batch."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Callable

from account_truth.broker_order_lifecycle import (
    broker_order_lifecycle_account_ref_hash,
    preview_broker_order_lifecycle_export,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_SCHEMA_VERSION,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_STATUSES as _BATCH_STATUSES,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_COLLECTION_MODES as _COLLECTION_MODES,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_CONNECTION_STATUSES as _CONNECTION_STATUSES,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_CURSOR_FIELDS as _CURSOR_FIELDS,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RELEASE_REVIEW_STATUSES as _RELEASE_REVIEW_STATUSES,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_SOURCE_CONTACT_STATUSES as _SOURCE_CONTACT_STATUSES,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_TOP_LEVEL_FIELDS as _TOP_LEVEL_FIELDS,
)
from account_truth.broker_order_lifecycle_collector_contracts import (
    MAX_COLLECTOR_BATCH_BYTES,
)
from account_truth.broker_order_lifecycle_collector_values import (
    aware_collector_utc as _aware_utc,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_contains_sensitive_key as _contains_sensitive_key,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_fingerprint as _fingerprint,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_fingerprint_is_valid as _fingerprint_is_valid,
)
from account_truth.broker_order_lifecycle_collector_values import (
    collector_safety_flags as _safety_flags,
)
from account_truth.broker_order_lifecycle_collector_values import (
    normalize_collector_id as _id,
)
from account_truth.broker_order_lifecycle_collector_values import (
    normalize_collector_nonnegative_int as _nonnegative_int,
)
from account_truth.broker_order_lifecycle_collector_values import (
    normalize_collector_timestamp as _timestamp,
)
from account_truth.broker_order_lifecycle_collector_values import (
    reject_collector_unknown_fields as _reject_unknown_fields,
)
from account_truth.broker_order_lifecycle_collector_values import (
    sanitize_collector_source_name as _sanitized_source_name,
)


def preview_broker_order_lifecycle_collector_batch(
    content: str | bytes,
    *,
    source_name: str = "",
    max_snapshot_age_seconds: int = 120,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Normalize one local collector batch without writing or contacting a broker."""

    observed_at = _aware_utc((clock or (lambda: datetime.now(UTC)))())
    raw, data, record_blockers = _decode_collector_batch(content)
    blockers: list[str] = []
    identity = _normalize_collector_identity(data, record_blockers)
    runtime = _normalize_collector_runtime(
        data,
        identity=identity,
        record_blockers=record_blockers,
        blockers=blockers,
    )
    lifecycle_preview = _preview_lifecycle_evidence(
        data,
        identity=identity,
        runtime=runtime,
        source_name=source_name,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        observed_at=observed_at,
        blockers=blockers,
    )
    account_ref_hash = str(
        lifecycle_preview.get("account_ref_hash") or ""
    ) or broker_order_lifecycle_account_ref_hash(
        identity["account_id"],
        provider=identity["provider"],
    )
    unique_record_blockers = list(dict.fromkeys(record_blockers))
    unique_blockers = list(dict.fromkeys([*record_blockers, *blockers]))
    recordable = bool(
        not unique_record_blockers
        and all(
            (
                identity["run_id"],
                identity["collector_id"],
                identity["deployment_id"],
                identity["collector_version"],
                identity["deployment_fingerprint"],
                identity["release_evidence_ref"],
                identity["adapter_authorization_ref"],
                identity["provider"],
                identity["gateway_id"],
                identity["account_alias"],
                account_ref_hash,
                runtime["captured_at"],
            )
        )
    )
    core = _collector_core(
        identity=identity,
        runtime=runtime,
        account_ref_hash=account_ref_hash,
        lifecycle_preview=lifecycle_preview,
        blockers=unique_blockers,
    )
    batch_fingerprint = _fingerprint(core)
    evidence_core = dict(core)
    evidence_core.pop("run_id")
    return {
        **core,
        "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_PREVIEW_SCHEMA_VERSION,
        "batch_fingerprint": batch_fingerprint,
        "evidence_fingerprint": _fingerprint(evidence_core),
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


def _decode_collector_batch(
    content: str | bytes,
) -> tuple[bytes, dict[str, Any], list[str]]:
    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    blockers: list[str] = []
    text = ""
    if len(raw) > MAX_COLLECTOR_BATCH_BYTES:
        blockers.append("broker_order_lifecycle_collector_batch_too_large")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            blockers.append("broker_order_lifecycle_collector_batch_not_utf8")
    data: dict[str, Any] = {}
    if not blockers:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            blockers.append("broker_order_lifecycle_collector_batch_json_invalid")
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                blockers.append("broker_order_lifecycle_collector_batch_not_object")
    if _contains_sensitive_key(data):
        blockers.append("broker_order_lifecycle_collector_credentials_not_allowed")
    _reject_unknown_fields(data, _TOP_LEVEL_FIELDS, "payload", blockers)
    return raw, data, blockers


def _normalize_collector_identity(
    data: dict[str, Any],
    record_blockers: list[str],
) -> dict[str, str]:
    identity = {
        "schema_version": str(data.get("schema_version") or ""),
        "run_id": _id(data.get("run_id"), "run_id", record_blockers),
        "collector_id": _id(data.get("collector_id"), "collector_id", record_blockers),
        "deployment_id": _id(
            data.get("deployment_id"), "deployment_id", record_blockers
        ),
        "collector_version": _id(
            data.get("collector_version"), "collector_version", record_blockers
        ),
        "deployment_fingerprint": str(data.get("deployment_fingerprint") or "")
        .strip()
        .lower(),
        "release_evidence_ref": _id(
            data.get("release_evidence_ref"),
            "release_evidence_ref",
            record_blockers,
        ),
        "adapter_authorization_ref": _id(
            data.get("adapter_authorization_ref"),
            "adapter_authorization_ref",
            record_blockers,
        ),
        "provider": _id(data.get("provider"), "provider", record_blockers).lower(),
        "gateway_id": _id(data.get("gateway_id"), "gateway_id", record_blockers),
        "account_alias": _id(
            data.get("account_alias"), "account_alias", record_blockers
        ),
        "account_id": str(data.get("account_id") or "").strip(),
        "release_review_status": str(data.get("release_review_status") or "")
        .strip()
        .lower(),
        "collection_mode": str(data.get("collection_mode") or "").strip().lower(),
        "source_contact_status": str(data.get("source_contact_status") or "")
        .strip()
        .lower(),
        "connection_status": str(data.get("connection_status") or "").strip().lower(),
        "batch_status": str(data.get("batch_status") or "").strip().lower(),
    }
    if not identity["account_id"]:
        record_blockers.append("broker_order_lifecycle_collector_account_id_missing")
    if not _fingerprint_is_valid(identity["deployment_fingerprint"]):
        record_blockers.append(
            "broker_order_lifecycle_collector_deployment_fingerprint_invalid"
        )
    for value, allowed, blocker in (
        (
            identity["release_review_status"],
            _RELEASE_REVIEW_STATUSES,
            "broker_order_lifecycle_collector_release_review_status_invalid",
        ),
        (
            identity["collection_mode"],
            _COLLECTION_MODES,
            "broker_order_lifecycle_collector_collection_mode_invalid",
        ),
        (
            identity["source_contact_status"],
            _SOURCE_CONTACT_STATUSES,
            "broker_order_lifecycle_collector_source_contact_status_invalid",
        ),
        (
            identity["connection_status"],
            _CONNECTION_STATUSES,
            "broker_order_lifecycle_collector_connection_status_invalid",
        ),
        (
            identity["batch_status"],
            _BATCH_STATUSES,
            "broker_order_lifecycle_collector_batch_status_invalid",
        ),
    ):
        if value not in allowed:
            record_blockers.append(blocker)
    if (
        identity["schema_version"]
        != BROKER_ORDER_LIFECYCLE_COLLECTOR_BATCH_SCHEMA_VERSION
    ):
        record_blockers.append("broker_order_lifecycle_collector_schema_unsupported")
    return identity


def _normalize_collector_runtime(
    data: dict[str, Any],
    *,
    identity: dict[str, str],
    record_blockers: list[str],
    blockers: list[str],
) -> dict[str, Any]:
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
    runtime: dict[str, Any] = {
        "cursor_previous": _nonnegative_int(
            cursor_data.get("previous"), "cursor_previous", record_blockers
        ),
        "cursor_current": _nonnegative_int(
            cursor_data.get("current"), "cursor_current", record_blockers
        ),
    }
    if (
        runtime["cursor_current"] <= 0
        or runtime["cursor_current"] != runtime["cursor_previous"] + 1
    ):
        record_blockers.append(
            "broker_order_lifecycle_collector_cursor_not_consecutive"
        )
    runtime.update(
        {
            "event_count": _nonnegative_int(
                data.get("event_count"), "event_count", record_blockers
            ),
            "callbacks_received": _nonnegative_int(
                data.get("callbacks_received"), "callbacks_received", record_blockers
            ),
            "duplicate_callbacks_dropped": _nonnegative_int(
                data.get("duplicate_callbacks_dropped"),
                "duplicate_callbacks_dropped",
                record_blockers,
            ),
            "out_of_order_callbacks_dropped": _nonnegative_int(
                data.get("out_of_order_callbacks_dropped"),
                "out_of_order_callbacks_dropped",
                record_blockers,
            ),
        }
    )
    if (
        runtime["duplicate_callbacks_dropped"]
        + runtime["out_of_order_callbacks_dropped"]
        > runtime["callbacks_received"]
    ):
        record_blockers.append(
            "broker_order_lifecycle_collector_callback_counts_invalid"
        )
    _append_source_and_callback_blockers(identity, runtime, blockers)
    runtime["captured_at"] = _timestamp(data.get("captured_at"))
    if not runtime["captured_at"]:
        record_blockers.append("broker_order_lifecycle_collector_captured_at_invalid")
    _append_connection_and_batch_blockers(identity, runtime, blockers)
    return runtime


def _append_source_and_callback_blockers(
    identity: dict[str, str],
    runtime: dict[str, Any],
    blockers: list[str],
) -> None:
    collection_mode = identity["collection_mode"]
    source_contact_status = identity["source_contact_status"]
    if collection_mode in {"callback", "poll"}:
        if source_contact_status != "read_only_contact":
            blockers.append(
                "broker_order_lifecycle_collector_live_source_contact_not_read_only"
            )
        if identity["release_review_status"] != "reviewed":
            blockers.append(
                "broker_order_lifecycle_collector_adapter_release_not_reviewed"
            )
    elif collection_mode in {"replay", "fixture"}:
        if source_contact_status != "not_contacted":
            blockers.append(
                "broker_order_lifecycle_collector_offline_mode_contact_invalid"
            )
        if identity["connection_status"] != "not_applicable":
            blockers.append(
                "broker_order_lifecycle_collector_offline_connection_status_invalid"
            )
    if source_contact_status == "unknown":
        blockers.append("broker_order_lifecycle_collector_source_contact_unknown")
    accepted_callback_count = (
        runtime["callbacks_received"]
        - runtime["duplicate_callbacks_dropped"]
        - runtime["out_of_order_callbacks_dropped"]
    )
    if (
        collection_mode == "callback"
        and runtime["event_count"] != accepted_callback_count
    ):
        blockers.append(
            "broker_order_lifecycle_collector_callback_event_count_mismatch"
        )
    if collection_mode != "callback" and any(
        (
            runtime["callbacks_received"],
            runtime["duplicate_callbacks_dropped"],
            runtime["out_of_order_callbacks_dropped"],
        )
    ):
        blockers.append(
            "broker_order_lifecycle_collector_callback_telemetry_mode_mismatch"
        )


def _append_connection_and_batch_blockers(
    identity: dict[str, str],
    runtime: dict[str, Any],
    blockers: list[str],
) -> None:
    if identity["connection_status"] == "disconnected":
        blockers.append("broker_order_lifecycle_collector_disconnected")
    if (
        identity["collection_mode"] in {"callback", "poll"}
        and identity["connection_status"] != "connected"
    ):
        blockers.append("broker_order_lifecycle_collector_live_source_not_connected")
    if identity["batch_status"] == "partial":
        blockers.append("broker_order_lifecycle_collector_partial_batch")
    if identity["batch_status"] == "complete" and runtime["event_count"] != 1:
        blockers.append(
            "broker_order_lifecycle_collector_complete_batch_event_count_invalid"
        )


def _preview_lifecycle_evidence(
    data: dict[str, Any],
    *,
    identity: dict[str, str],
    runtime: dict[str, Any],
    source_name: str,
    max_snapshot_age_seconds: int,
    observed_at: datetime,
    blockers: list[str],
) -> dict[str, Any]:
    lifecycle_data = data.get("lifecycle")
    if not isinstance(lifecycle_data, dict):
        if identity["batch_status"] == "complete":
            blockers.append("broker_order_lifecycle_collector_lifecycle_missing")
        return {}
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
        ("provider", identity["provider"]),
        ("gateway_id", identity["gateway_id"]),
        ("account_alias", identity["account_alias"]),
        ("captured_at", runtime["captured_at"]),
        ("source_sequence", runtime["cursor_current"]),
    ):
        if lifecycle_preview.get(field) != expected:
            blockers.append(
                f"broker_order_lifecycle_collector_lifecycle_{field}_mismatch"
            )
    expected_account_hash = broker_order_lifecycle_account_ref_hash(
        identity["account_id"],
        provider=identity["provider"],
    )
    if lifecycle_preview.get("account_ref_hash") != expected_account_hash:
        blockers.append("broker_order_lifecycle_collector_lifecycle_account_mismatch")
    blockers.extend(str(item) for item in lifecycle_preview.get("blockers") or [])
    return lifecycle_preview


def _collector_core(
    *,
    identity: dict[str, str],
    runtime: dict[str, Any],
    account_ref_hash: str,
    lifecycle_preview: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_RUN_SCHEMA_VERSION,
        "run_id": identity["run_id"],
        "collector_id": identity["collector_id"],
        "deployment_id": identity["deployment_id"],
        "collector_version": identity["collector_version"],
        "deployment_fingerprint": identity["deployment_fingerprint"],
        "release_evidence_ref": identity["release_evidence_ref"],
        "release_review_status": identity["release_review_status"],
        "adapter_authorization_ref": identity["adapter_authorization_ref"],
        "provider": identity["provider"],
        "gateway_id": identity["gateway_id"],
        "account_alias": identity["account_alias"],
        "account_ref_hash": account_ref_hash,
        "collection_mode": identity["collection_mode"],
        "source_contact_status": identity["source_contact_status"],
        "connection_status": identity["connection_status"],
        "batch_status": identity["batch_status"],
        "cursor_previous": runtime["cursor_previous"],
        "cursor_current": runtime["cursor_current"],
        "captured_at": runtime["captured_at"],
        "event_count": runtime["event_count"],
        "callbacks_received": runtime["callbacks_received"],
        "duplicate_callbacks_dropped": runtime["duplicate_callbacks_dropped"],
        "out_of_order_callbacks_dropped": runtime["out_of_order_callbacks_dropped"],
        "lifecycle_evidence_fingerprint": str(
            lifecycle_preview.get("evidence_fingerprint") or ""
        ),
        "blockers": blockers,
    }
