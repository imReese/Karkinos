"""Provider-free preview construction for broker order-lifecycle exports."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Callable

from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION,
)
from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_TOP_LEVEL_FIELDS as _TOP_LEVEL_FIELDS,
)
from account_truth.broker_order_lifecycle_contracts import (
    DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
)
from account_truth.broker_order_lifecycle_contracts import (
    broker_order_lifecycle_safety_flags as _safety_flags,
)
from account_truth.broker_order_lifecycle_values import (
    aware_broker_order_utc as _aware_utc,
)
from account_truth.broker_order_lifecycle_values import (
    broker_order_contains_sensitive_key as _contains_sensitive_key,
)
from account_truth.broker_order_lifecycle_values import (
    broker_order_lifecycle_account_ref_hash_value as _account_ref_hash,
)
from account_truth.broker_order_lifecycle_values import (
    broker_order_lifecycle_fingerprint as _fingerprint,
)
from account_truth.broker_order_lifecycle_values import (
    broker_order_lifecycle_id_is_valid as _id_is_valid,
)
from account_truth.broker_order_lifecycle_values import (
    decode_broker_order_content as _decode_content,
)
from account_truth.broker_order_lifecycle_values import (
    normalize_broker_fill as _normalize_fill,
)
from account_truth.broker_order_lifecycle_values import (
    normalize_broker_order as _normalize_order,
)
from account_truth.broker_order_lifecycle_values import (
    normalize_broker_order_source_sequence as _source_sequence,
)
from account_truth.broker_order_lifecycle_values import (
    normalize_broker_order_timestamp as _timestamp,
)
from account_truth.broker_order_lifecycle_values import (
    reject_broker_order_unknown_fields as _reject_unknown_fields,
)
from account_truth.broker_order_lifecycle_values import (
    sanitize_broker_order_source_name as _sanitized_source_name,
)
from account_truth.broker_order_lifecycle_values import (
    validate_broker_order_and_fills as _validate_order_and_fills,
)


def preview_broker_order_lifecycle_export(
    content: str | bytes,
    *,
    source_name: str = "",
    max_snapshot_age_seconds: int = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Normalize one exact-order broker export without persisting any fact."""

    observed_at = _aware_utc((clock or (lambda: datetime.now(UTC)))())
    max_age = max(30, min(int(max_snapshot_age_seconds), 3600))
    raw, text, decode_blockers = _decode_content(content)
    blockers = list(decode_blockers)
    file_fingerprint = hashlib.sha256(raw).hexdigest()
    data: dict[str, Any] = {}
    if not blockers:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            blockers.append("broker_order_lifecycle_json_invalid")
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                blockers.append("broker_order_lifecycle_payload_not_object")

    if _contains_sensitive_key(data):
        blockers.append("broker_order_lifecycle_credentials_not_allowed")
    _reject_unknown_fields(data, _TOP_LEVEL_FIELDS, "payload", blockers)

    schema_version = str(data.get("schema_version") or "")
    provider = str(data.get("provider") or "").strip().lower()
    snapshot_kind = str(data.get("snapshot_kind") or "").strip().lower()
    gateway_id = str(data.get("gateway_id") or "").strip()
    account_alias = str(data.get("account_alias") or "").strip()
    account_id = str(data.get("account_id") or "").strip()
    captured_at = _timestamp(
        data.get("captured_at"),
        blocker="broker_order_lifecycle_captured_at_invalid",
        blockers=blockers,
    )
    source_sequence = _source_sequence(data.get("source_sequence"), blockers)

    if schema_version != BROKER_ORDER_LIFECYCLE_EXPORT_SCHEMA_VERSION:
        blockers.append("broker_order_lifecycle_schema_unsupported")
    if not _id_is_valid(provider):
        blockers.append("broker_order_lifecycle_provider_invalid")
    if snapshot_kind != "exact_order_lifecycle":
        blockers.append("broker_order_lifecycle_snapshot_kind_invalid")
    if not _id_is_valid(gateway_id):
        blockers.append("broker_order_lifecycle_gateway_id_invalid")
    if not _id_is_valid(account_alias):
        blockers.append("broker_order_lifecycle_account_alias_invalid")
    if not account_id:
        blockers.append("broker_order_lifecycle_account_id_missing")

    if captured_at:
        captured = datetime.fromisoformat(captured_at)
        age_seconds = (observed_at - captured).total_seconds()
        if age_seconds < -5:
            blockers.append("broker_order_lifecycle_snapshot_in_future")
        elif age_seconds > max_age:
            blockers.append("broker_order_lifecycle_snapshot_stale")

    raw_orders = data.get("orders")
    if not isinstance(raw_orders, list) or len(raw_orders) != 1:
        blockers.append("broker_order_lifecycle_exactly_one_order_required")
        raw_order: dict[str, Any] = {}
    else:
        raw_order = raw_orders[0] if isinstance(raw_orders[0], dict) else {}
        if not raw_order:
            blockers.append("broker_order_lifecycle_order_invalid")
    order = _normalize_order(raw_order, blockers)

    raw_fills = data.get("fills")
    if not isinstance(raw_fills, list):
        blockers.append("broker_order_lifecycle_fills_invalid")
        raw_fills = []
    fills: list[dict[str, Any]] = []
    for index, raw_fill in enumerate(raw_fills, start=1):
        if not isinstance(raw_fill, dict):
            blockers.append(f"broker_order_lifecycle_fill_{index}_invalid")
            continue
        fills.append(_normalize_fill(raw_fill, index=index, blockers=blockers))
    _validate_order_and_fills(order, fills, captured_at, blockers)

    core = {
        "schema_version": BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        "provider": provider,
        "snapshot_kind": snapshot_kind,
        "gateway_id": gateway_id,
        "account_alias": account_alias,
        "account_ref_hash": _account_ref_hash(account_id, provider=provider),
        "captured_at": captured_at,
        "source_sequence": source_sequence,
        "order": order,
        "fills": fills,
        "file_fingerprint": file_fingerprint,
    }
    evidence_fingerprint = _fingerprint(core)
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_PREVIEW_SCHEMA_VERSION,
        "evidence_schema_version": (BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION),
        "observation_id": _fingerprint(
            {
                "domain": "karkinos.broker_order_lifecycle.observation_id.v1",
                "evidence_fingerprint": evidence_fingerprint,
            }
        ),
        "evidence_fingerprint": evidence_fingerprint,
        "file_fingerprint": file_fingerprint,
        "provider": provider,
        "snapshot_kind": snapshot_kind,
        "gateway_id": gateway_id,
        "account_alias": account_alias,
        "account_ref_hash": _account_ref_hash(account_id, provider=provider),
        "source_name": _sanitized_source_name(source_name),
        "captured_at": captured_at,
        "observed_at": observed_at.isoformat(),
        "source_sequence": source_sequence,
        "max_snapshot_age_seconds": max_age,
        "validation_status": "pass" if not unique_blockers else "blocked",
        "ready_to_record": not unique_blockers,
        "blockers": unique_blockers,
        "order": order,
        "fills": fills,
        "fill_count": len(fills),
        **_safety_flags(),
    }
