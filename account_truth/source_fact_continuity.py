"""Materiality-aware continuity for canonical Account Truth imports.

The continuity contract carries an accepted account/scope review across safe
daily state refreshes and append-only account activity.  It never edits broker
evidence, the production ledger, orders, strategies, or capital authority.

Persisted import rows remain immutable.  Historical state snapshots and
non-decision metadata may be superseded because the current Karkinos-derived
cash/position snapshot and canonical reconciliation independently prove the
current state.  Existing economic activity must remain present and unchanged;
new activity must be chronological and is admitted only as a monotonic suffix.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Sequence

from account_truth.broker_statement_roll_forward import (
    DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX,
)
from account_truth.source_fact_lineage import (
    project_account_truth_source_fact_lineage,
)

ACCOUNT_TRUTH_SOURCE_FACT_CONTINUITY_SCHEMA_VERSION = (
    "karkinos.account_truth.source_fact_continuity.v1"
)

_SNAPSHOT_EVENT_TYPES = frozenset({"cash_snapshot", "position_snapshot"})
_DECISION_FACT_FIELDS = (
    "event_id",
    "event_type",
    "occurred_at",
    "symbol",
    "asset_class",
    "currency",
    "quantity",
    "price",
    "gross_amount",
    "fee",
    "tax",
    "transfer_fee",
    "net_amount",
    "cash_balance",
    "position_quantity",
    "cost_basis",
    "cost_basis_method",
    "broker_order_id",
    "client_order_id",
)


def assess_account_truth_source_fact_continuity(
    *,
    current_import: Any,
    current_events: Sequence[Any],
    reviewed_import: Any,
    reviewed_events: Sequence[Any],
    require_current_derived_snapshot: bool = True,
) -> dict[str, object]:
    """Classify one current import against an earlier reviewed import.

    The public result contains counts and fingerprints only.  It deliberately
    excludes event ids, symbols, quantities, balances, prices, and broker rows.
    """

    current_lineage = project_account_truth_source_fact_lineage(
        import_run=current_import,
        events=current_events,
    )
    reviewed_lineage = project_account_truth_source_fact_lineage(
        import_run=reviewed_import,
        events=reviewed_events,
    )
    blockers: list[str] = []
    if current_lineage.get("status") != "pass":
        blockers.append("account_truth_source_fact_continuity_current_lineage_blocked")
    if reviewed_lineage.get("status") != "pass":
        blockers.append("account_truth_source_fact_continuity_reviewed_lineage_blocked")
    if str(getattr(current_import, "source_type", "")) != str(
        getattr(reviewed_import, "source_type", "")
    ):
        blockers.append("account_truth_source_fact_continuity_source_type_changed")
    if (
        require_current_derived_snapshot
        and int(current_lineage.get("derived_snapshot_count") or 0) < 1
    ):
        blockers.append("account_truth_source_fact_continuity_daily_snapshot_missing")

    current_activity = _activity_by_event_id(current_events)
    reviewed_activity = _activity_by_event_id(reviewed_events)
    if current_activity is None or reviewed_activity is None:
        blockers.append(
            "account_truth_source_fact_continuity_activity_identity_invalid"
        )
        current_activity = current_activity or {}
        reviewed_activity = reviewed_activity or {}

    current_ids = set(current_activity)
    reviewed_ids = set(reviewed_activity)
    removed_ids = reviewed_ids - current_ids
    added_ids = current_ids - reviewed_ids
    shared_ids = current_ids & reviewed_ids
    changed_ids = {
        event_id
        for event_id in shared_ids
        if _decision_fact_fingerprint(current_activity[event_id])
        != _decision_fact_fingerprint(reviewed_activity[event_id])
    }
    if removed_ids:
        blockers.append("account_truth_source_fact_continuity_activity_removed")
    if changed_ids:
        blockers.append("account_truth_source_fact_continuity_activity_changed")

    latest_reviewed_activity_at = _latest_activity_timestamp(reviewed_activity.values())
    added_activity_times = [
        _aware_timestamp(getattr(current_activity[event_id], "occurred_at", ""))
        for event_id in added_ids
    ]
    if any(value is None for value in added_activity_times):
        blockers.append("account_truth_source_fact_continuity_activity_time_invalid")
    elif latest_reviewed_activity_at is not None and any(
        value < latest_reviewed_activity_at
        for value in added_activity_times
        if value is not None
    ):
        blockers.append("account_truth_source_fact_continuity_activity_not_append_only")

    settlement_metadata_changed_count = 0
    nondecision_metadata_changed_count = 0
    current_snapshot_date = _derived_snapshot_date(current_lineage)
    for event_id in shared_ids - changed_ids:
        current_event = current_activity[event_id]
        reviewed_event = reviewed_activity[event_id]
        if str(getattr(current_event, "settled_at", "")) != str(
            getattr(reviewed_event, "settled_at", "")
        ):
            settlement_metadata_changed_count += 1
            if not _historical_settlement_metadata_is_safe(
                current_event=current_event,
                reviewed_event=reviewed_event,
                current_snapshot_date=current_snapshot_date,
            ):
                blockers.append(
                    "account_truth_source_fact_continuity_settlement_change_unsafe"
                )
        if str(getattr(current_event, "row_fingerprint", "")) != str(
            getattr(reviewed_event, "row_fingerprint", "")
        ):
            nondecision_metadata_changed_count += 1

    exact_source_facts = bool(
        current_lineage.get("source_fact_fingerprint")
        == reviewed_lineage.get("source_fact_fingerprint")
        and current_lineage.get("base_event_count")
        == reviewed_lineage.get("base_event_count")
    )
    unique_blockers = list(dict.fromkeys(blockers))
    if unique_blockers:
        mode = "blocked_material_drift"
    elif added_ids and not exact_source_facts:
        mode = "append_only_activity_with_state_refresh"
    elif added_ids:
        mode = "append_only_activity"
    elif exact_source_facts:
        mode = "daily_snapshot_roll_forward"
    else:
        mode = "canonical_state_refresh"

    core = {
        "schema_version": ACCOUNT_TRUTH_SOURCE_FACT_CONTINUITY_SCHEMA_VERSION,
        "status": "continuous" if not unique_blockers else "blocked",
        "mode": mode,
        "reviewed_import_run_id": str(
            getattr(reviewed_import, "import_run_id", "") or ""
        ),
        "current_import_run_id": str(
            getattr(current_import, "import_run_id", "") or ""
        ),
        "reviewed_source_fact_fingerprint": reviewed_lineage.get(
            "source_fact_fingerprint"
        ),
        "current_source_fact_fingerprint": current_lineage.get(
            "source_fact_fingerprint"
        ),
        "reviewed_activity_count": len(reviewed_activity),
        "current_activity_count": len(current_activity),
        "added_activity_count": len(added_ids),
        "removed_activity_count": len(removed_ids),
        "changed_activity_count": len(changed_ids),
        "settlement_metadata_changed_count": settlement_metadata_changed_count,
        "nondecision_metadata_changed_count": nondecision_metadata_changed_count,
        "reviewed_activity_fingerprint": _activity_set_fingerprint(
            reviewed_activity.values()
        ),
        "current_activity_fingerprint": _activity_set_fingerprint(
            current_activity.values()
        ),
        "current_derived_snapshot_date": current_snapshot_date,
        "blockers": unique_blockers,
        "persisted_facts_only": True,
        "contains_private_financial_values": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def assess_account_truth_source_fact_history_continuity(
    *,
    repository: Any,
    current_import: Any,
    reviewed_import: Any,
    limit: int = 1000,
) -> dict[str, object]:
    """Require every persisted import transition to be materially continuous."""

    blockers: list[str] = []
    if limit < 1 or limit > 1000:
        blockers.append("account_truth_source_fact_continuity_scan_limit_invalid")
        return _blocked_history(blockers)
    imports = list(repository.list_import_runs(limit=limit))
    if len(imports) == limit:
        blockers.append("account_truth_source_fact_continuity_scan_truncated")
    import_ids = [str(getattr(item, "import_run_id", "")) for item in imports]
    try:
        current_index = import_ids.index(str(current_import.import_run_id))
        reviewed_index = import_ids.index(str(reviewed_import.import_run_id))
    except ValueError:
        blockers.append("account_truth_source_fact_continuity_import_missing")
        return _blocked_history(blockers)
    if current_index > reviewed_index:
        blockers.append("account_truth_source_fact_continuity_import_order_invalid")
        return _blocked_history(blockers)

    chronological = list(reversed(imports[current_index : reviewed_index + 1]))
    assessments: list[dict[str, object]] = []
    for previous, current in zip(chronological, chronological[1:]):
        assessment = assess_account_truth_source_fact_continuity(
            current_import=current,
            current_events=_events_for_import(repository, current),
            reviewed_import=previous,
            reviewed_events=_events_for_import(repository, previous),
            require_current_derived_snapshot=True,
        )
        assessments.append(assessment)
        blockers.extend(str(item) for item in assessment.get("blockers") or [])
    direct = assess_account_truth_source_fact_continuity(
        current_import=current_import,
        current_events=_events_for_import(repository, current_import),
        reviewed_import=reviewed_import,
        reviewed_events=_events_for_import(repository, reviewed_import),
        require_current_derived_snapshot=(
            current_import.import_run_id != reviewed_import.import_run_id
        ),
    )
    blockers.extend(str(item) for item in direct.get("blockers") or [])
    unique_blockers = list(dict.fromkeys(blockers))
    core = {
        **direct,
        "status": "continuous" if not unique_blockers else "blocked",
        "mode": (
            str(direct.get("mode") or "blocked_material_drift")
            if not unique_blockers
            else "blocked_material_drift"
        ),
        "history_transition_count": len(assessments),
        "history_modes": list(
            dict.fromkeys(str(item.get("mode") or "") for item in assessments)
        ),
        "blockers": unique_blockers,
    }
    core.pop("evidence_fingerprint", None)
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def source_fact_continuity_allows_inheritance(value: object) -> bool:
    """Return whether a sanitized continuity assessment is safe to inherit."""

    return bool(
        isinstance(value, dict)
        and value.get("schema_version")
        == ACCOUNT_TRUTH_SOURCE_FACT_CONTINUITY_SCHEMA_VERSION
        and value.get("status") == "continuous"
        and not value.get("blockers")
        and str(value.get("reviewed_source_fact_fingerprint") or "").startswith(
            "sha256:"
        )
        and int(value.get("removed_activity_count") or 0) == 0
        and int(value.get("changed_activity_count") or 0) == 0
        and value.get("authorizes_execution") is False
        and value.get("changes_capital_authority") is False
    )


def _activity_by_event_id(events: Sequence[Any]) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    for event in events:
        event_id = str(getattr(event, "event_id", "")).strip()
        event_type = str(getattr(event, "event_type", "")).strip()
        if event_id.startswith(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX):
            continue
        if event_type in _SNAPSHOT_EVENT_TYPES:
            continue
        if (
            not event_id
            or event_id in result
            or bool(getattr(event, "is_row_duplicate", False))
        ):
            return None
        result[event_id] = event
    return result


def _decision_fact_fingerprint(event: Any) -> str:
    return _fingerprint(
        {
            field: _normalized_fact_value(getattr(event, field, None))
            for field in _DECISION_FACT_FIELDS
        }
    )


def _activity_set_fingerprint(events: Sequence[Any] | Any) -> str:
    return _fingerprint(
        sorted(_decision_fact_fingerprint(event) for event in list(events))
    )


def _normalized_fact_value(value: object) -> object:
    if value is None:
        return None
    return str(value).strip()


def _latest_activity_timestamp(events: Sequence[Any] | Any) -> datetime | None:
    values = [
        _aware_timestamp(getattr(event, "occurred_at", "")) for event in list(events)
    ]
    if not values:
        return None
    if any(value is None for value in values):
        return None
    return max(value for value in values if value is not None)


def _aware_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _historical_settlement_metadata_is_safe(
    *,
    current_event: Any,
    reviewed_event: Any,
    current_snapshot_date: str | None,
) -> bool:
    if not current_snapshot_date:
        return False
    try:
        snapshot_boundary = datetime.fromisoformat(current_snapshot_date).date()
    except ValueError:
        return False
    for event in (current_event, reviewed_event):
        raw = str(getattr(event, "settled_at", "")).strip()
        if not raw:
            continue
        try:
            settled = datetime.fromisoformat(raw).date()
        except ValueError:
            return False
        if settled > snapshot_boundary:
            return False
    return True


def _derived_snapshot_date(lineage: dict[str, object]) -> str | None:
    value = str(lineage.get("derived_snapshot_date") or "")
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _events_for_import(repository: Any, import_run: Any) -> list[Any]:
    return list(
        repository.list_events(
            getattr(import_run, "duplicate_of_import_run_id", None)
            or import_run.import_run_id
        )
    )


def _blocked_history(blockers: Sequence[str]) -> dict[str, object]:
    core = {
        "schema_version": ACCOUNT_TRUTH_SOURCE_FACT_CONTINUITY_SCHEMA_VERSION,
        "status": "blocked",
        "mode": "blocked_material_drift",
        "reviewed_import_run_id": None,
        "current_import_run_id": None,
        "reviewed_source_fact_fingerprint": None,
        "current_source_fact_fingerprint": None,
        "reviewed_activity_count": 0,
        "current_activity_count": 0,
        "added_activity_count": 0,
        "removed_activity_count": 0,
        "changed_activity_count": 0,
        "settlement_metadata_changed_count": 0,
        "nondecision_metadata_changed_count": 0,
        "reviewed_activity_fingerprint": None,
        "current_activity_fingerprint": None,
        "current_derived_snapshot_date": None,
        "history_transition_count": 0,
        "history_modes": [],
        "blockers": list(dict.fromkeys(blockers)),
        "persisted_facts_only": True,
        "contains_private_financial_values": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
