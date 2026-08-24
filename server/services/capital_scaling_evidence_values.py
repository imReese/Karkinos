"""Pure value handling for capital-scaling evidence."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from server.services.capital_scaling_evidence_contracts import (
    REAL_EXECUTION_MODES as _REAL_EXECUTION_MODES,
)
from server.services.capital_scaling_evidence_contracts import SHANGHAI as _SHANGHAI


def _validated_window(
    start: datetime,
    end: datetime,
    *,
    max_boundary_gap_hours: int,
) -> tuple[datetime, datetime, int]:
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("review_window_start must be timezone-aware")
    if end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("review_window_end must be timezone-aware")
    normalized_start = _aware_utc(start)
    normalized_end = _aware_utc(end)
    if normalized_start >= normalized_end:
        raise ValueError("review window start must precede end")
    if (normalized_end - normalized_start).days > 366:
        raise ValueError("review window cannot exceed 366 days")
    gap_hours = int(max_boundary_gap_hours)
    if gap_hours < 1 or gap_hours > 168:
        raise ValueError("max_boundary_gap_hours must be between 1 and 168")
    return normalized_start, normalized_end, gap_hours


def _is_real_execution_row(row: dict[str, Any]) -> bool:
    if str(row.get("execution_mode") or "").strip().lower() not in (
        _REAL_EXECUTION_MODES
    ):
        return False
    source = str(row.get("source") or "").strip().lower()
    return not any(marker in source for marker in ("paper", "shadow", "simulat"))


def _has_reconciled_fill_linkage(
    row: dict[str, Any],
    metadata: dict[str, Any],
) -> bool:
    required = (
        row.get("provider_name"),
        row.get("broker_order_id"),
        metadata.get("account_truth_import_run_id"),
        metadata.get("execution_reconciliation_run_id"),
    )
    return all(str(value or "").strip() for value in required)


def _effective_terminal_status(
    row: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> str:
    status = str(row.get("status") or "").strip().lower()
    terminal_statuses = {"filled", "rejected", "cancelled", "expired"}
    if status in terminal_statuses:
        return status
    if status == "reconciled":
        for transition in reversed(transitions):
            candidate = str(transition.get("to_status") or "").strip().lower()
            if candidate in terminal_statuses:
                return candidate
    return status


def _sanitized_account_truth_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "import_run_id": str(source.get("import_run_id") or ""),
        "created_at": str(source.get("created_at") or ""),
        "schema_version": str(source.get("schema_version") or ""),
        "score": int(source.get("score") or 0),
        "gate_status": str(source.get("gate_status") or "blocked"),
        "cash_status": str(source.get("cash_status") or "blocked"),
        "position_status": str(source.get("position_status") or "blocked"),
        "fee_status": str(source.get("fee_status") or "blocked"),
        "cost_basis_status": str(source.get("cost_basis_status") or "blocked"),
        "data_freshness_status": str(source.get("data_freshness_status") or "missing"),
        "unresolved_mismatch_count": int(source.get("unresolved_mismatch_count") or 0),
        "resolved_review_count": int(source.get("resolved_review_count") or 0),
        "blocking_reasons": [
            str(item) for item in source.get("blocking_reasons") or []
        ],
    }


def _nearest_snapshot(
    snapshots: list[tuple[datetime, dict[str, Any]]],
    *,
    target: datetime,
) -> tuple[datetime, dict[str, Any]] | None:
    if not snapshots:
        return None
    return min(snapshots, key=lambda item: abs((item[0] - target).total_seconds()))


def _nested_int(
    snapshot: tuple[datetime, dict[str, Any]] | None,
    field: str,
) -> int | None:
    if snapshot is None:
        return None
    account_truth = snapshot[1].get("account_truth")
    account_truth = account_truth if isinstance(account_truth, dict) else {}
    value = account_truth.get(field)
    return int(value) if value is not None else None


def _fact(
    *,
    kind: str,
    metrics: dict[str, Any],
    blockers: list[str],
    source_refs: list[str],
    assumptions: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    payload = {
        "schema_version": "karkinos.capital_scaling_evidence_fact.v1",
        "evidence_kind": kind,
        "status": "clear" if not blockers else "blocked",
        "metrics": metrics,
        "blockers": list(dict.fromkeys(blockers)),
        "source_refs": list(dict.fromkeys(ref for ref in source_refs if ref)),
        "assumptions": assumptions,
        "limitations": limitations,
        "does_not_issue_capital_authorization": True,
        "does_not_mutate_runtime_limits": True,
        "does_not_submit_broker_order": True,
    }
    return {**payload, "source_fingerprint": _fingerprint(payload)}


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _nearest_rank(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(float(percentile * Decimal(len(ordered)))))
    return ordered[rank - 1]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _decimal_string_or_none(value: Decimal | None) -> str | None:
    return _decimal_string(value) if value is not None else None


def _parse_datetime(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **_json_object(row.get("payload_json")),
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


validated_window = _validated_window
is_real_execution_row = _is_real_execution_row
has_reconciled_fill_linkage = _has_reconciled_fill_linkage
effective_terminal_status = _effective_terminal_status
sanitized_account_truth_source = _sanitized_account_truth_source
nearest_snapshot = _nearest_snapshot
nested_int = _nested_int
fact = _fact
average = _average
nearest_rank = _nearest_rank
decimal_value = _decimal
decimal_string = _decimal_string
decimal_string_or_none = _decimal_string_or_none
parse_datetime = _parse_datetime
aware_utc = _aware_utc
event_response = _event_response
json_object = _json_object
fingerprint = _fingerprint
