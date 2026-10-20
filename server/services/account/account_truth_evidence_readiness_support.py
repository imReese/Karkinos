"""Pure projection helpers for Account Truth evidence readiness."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from account_truth.broker_evidence import StoredBrokerEvidenceEvent

ACCOUNT_TRUTH_EVIDENCE_SCOPE_SCHEMA_VERSION = "karkinos.account_truth.evidence_scope.v1"
_SAFE_SCOPE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]{0,63}$")


def _legacy_source_resolution_projection(
    citic_source_follow_up: dict[str, object],
) -> dict[str, object]:
    """Explain the remaining source stage without changing any financial gate."""

    pending_source_count = _safe_nonnegative_int(
        citic_source_follow_up.get("pending_source_count")
    )
    count_complete = citic_source_follow_up.get("count_complete") is True
    query_windows_clear = (
        citic_source_follow_up.get("query_window_integrity_clear") is True
    )
    source_scopes_clear = (
        citic_source_follow_up.get("source_scope_integrity_clear") is True
    )
    if not count_complete:
        status = "legacy_source_review_state_unavailable"
        next_manual_action = str(
            citic_source_follow_up.get("next_manual_action")
            or "repair_citic_source_intake_metadata_store"
        )
    elif pending_source_count == 0:
        status = "no_legacy_source_resolution_pending"
        next_manual_action = "none"
    elif not query_windows_clear:
        status = "legacy_query_window_review_required"
        next_manual_action = "review_citic_source_query_windows"
    elif not source_scopes_clear:
        status = "legacy_source_scope_review_required"
        next_manual_action = "review_citic_source_scopes"
    else:
        status = "legacy_attestations_complete_canonical_resolution_required"
        next_manual_action = "provide_citic_account_truth_evidence_or_reject_source"

    legacy_attestations_complete = (
        count_complete
        and pending_source_count > 0
        and query_windows_clear
        and source_scopes_clear
    )
    return {
        "schema_version": ("karkinos.account_truth.citic_source_resolution_stage.v1"),
        "status": status,
        "pending_source_count": pending_source_count,
        "source_count_complete": count_complete,
        "query_window_attestations_complete": query_windows_clear,
        "source_scope_attestations_complete": source_scopes_clear,
        "legacy_source_attestations_complete": legacy_attestations_complete,
        "canonical_account_truth_established_by_legacy_sources": False,
        "next_manual_action": next_manual_action,
        "satisfies_account_truth": False,
        "satisfies_reconciliation": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "limitations": [
            "Reviewed legacy query windows and source scopes do not establish current or complete canonical Account Truth.",
            "Closing source follow-up still requires separately reviewed canonical evidence or an explicit source rejection.",
        ],
    }


def _item_from_score_component(
    *,
    score: dict[str, object],
    score_available: bool,
    requirement: str,
    score_field: str,
    required_action: str,
) -> dict[str, object]:
    status = str(score.get(score_field) or "missing") if score_available else "missing"
    return _item(
        requirement=requirement,
        status=status,
        evidence_reference=(
            f"account_truth_score:{score_field}" if score_available else None
        ),
        required_action=None if status == "pass" else required_action,
    )


def _freshness_item(
    *,
    score: dict[str, object],
    score_available: bool,
    ledger_coverage_status: str,
) -> dict[str, object]:
    freshness = str(score.get("data_freshness_status") or "missing")
    if not score_available:
        status = "missing"
    elif freshness == "fresh" and ledger_coverage_status == "covered":
        status = "pass"
    elif freshness == "stale" or ledger_coverage_status == "stale":
        status = "stale"
    else:
        status = "blocked"
    return _item(
        requirement="freshness_and_ledger_coverage",
        status=status,
        evidence_reference=(
            "account_truth_score:ledger_coverage" if score_available else None
        ),
        required_action=(
            None
            if status == "pass"
            else "refresh_broker_evidence_covering_latest_ledger"
        ),
    )


def _item(
    *,
    requirement: str,
    status: str,
    evidence_reference: str | None,
    required_action: str | None,
) -> dict[str, object]:
    return {
        "requirement": requirement,
        "status": status,
        "evidence_reference": evidence_reference,
        "required_action": required_action,
    }


def _db_path_for_state(state: Any) -> Path | None:
    path = getattr(getattr(state, "db", None), "_path", None)
    return Path(path) if path is not None else None


def _missing_evidence_scope() -> dict[str, object]:
    core = {
        "schema_version": ACCOUNT_TRUTH_EVIDENCE_SCOPE_SCHEMA_VERSION,
        "status": "blocked",
        "import_run_id": None,
        "source_schema_version": None,
        "source_fact_lineage": {
            "status": "blocked",
            "source_fact_fingerprint": None,
            "derived_snapshot_count": 0,
            "blockers": ["account_truth_source_fact_lineage_import_missing"],
        },
        "account_binding": {
            "status": "missing",
            "account_alias": None,
            "account_reference_hash": None,
        },
        "declared_coverage_window": {
            "status": "missing",
            "start_date": None,
            "end_date": None,
        },
        "observed_event_window": {
            "status": "missing",
            "occurred_start_date": None,
            "occurred_end_date": None,
            "settled_start_date": None,
            "settled_end_date": None,
            "settlement_date_missing_count": 0,
            "event_count": 0,
            "unique_event_count": 0,
            "expected_event_count": 0,
        },
        "asset_scope": {
            "status": "unverified",
            "observed_asset_classes": [],
            "observed_currencies": [],
            "observed_event_types": [],
        },
        "snapshot_evidence": {
            "cash_snapshot_count": 0,
            "position_snapshot_count": 0,
            "latest_cash_snapshot_date": None,
            "latest_position_snapshot_date": None,
        },
        "blockers": [
            "account_truth_evidence_scope_missing",
            "account_truth_account_scope_unbound",
            "account_truth_coverage_window_undeclared",
            "account_truth_asset_scope_completeness_unverified",
        ],
        "required_actions": [
            "record_reviewed_account_truth_evidence_scope",
        ],
    }
    observed_scope_fingerprint = _fingerprint(core)
    return {
        **core,
        "observed_scope_fingerprint": observed_scope_fingerprint,
        "evidence_fingerprint": observed_scope_fingerprint,
        "review": None,
        "limitations": [
            "No persisted Account Truth evidence scope could be resolved.",
        ],
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _lineage_allows_inheritance(scope: dict[str, object]) -> bool:
    lineage = _mapping(scope.get("source_fact_lineage"))
    return bool(
        lineage.get("status") == "pass"
        and str(lineage.get("source_fact_fingerprint") or "")
        and int(lineage.get("derived_snapshot_count") or 0) > 0
    )


def _scope_with_blocker(
    scope: dict[str, object],
    blocker: str,
) -> dict[str, object]:
    blocked = {
        **scope,
        "status": "blocked",
        "blockers": list(
            dict.fromkeys([*_unique_strings(scope.get("blockers")), blocker])
        ),
        "required_actions": ["record_reviewed_account_truth_evidence_scope"],
    }
    blocked["evidence_fingerprint"] = _fingerprint(_scope_fingerprint_core(blocked))
    return blocked


def _reviewed_scope_fingerprint_matches(
    expected: str,
    scope: dict[str, object],
) -> bool:
    current = str(scope.get("observed_scope_fingerprint") or "")
    if expected == current:
        return True
    legacy_core = {
        key: value
        for key, value in scope.items()
        if key
        not in {
            "source_fact_lineage",
            "observed_scope_fingerprint",
            "evidence_fingerprint",
            "review",
            "limitations",
            "persisted_facts_only",
            "provider_contacted",
            "database_writes_performed",
            "authorizes_execution",
            "changes_capital_authority",
        }
    }
    return expected == _fingerprint(legacy_core)


def _scope_fingerprint_core(scope: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in scope.items()
        if key not in {"evidence_fingerprint", "limitations"}
    }


def _aware_event_date(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.date().isoformat()


def _settlement_date(value: str) -> str | None:
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None


def _safe_observed_codes(
    values: Sequence[str] | Any,
    *,
    pattern: re.Pattern[str] = _SAFE_SCOPE_CODE,
    transform: Any = str.lower,
) -> tuple[list[str], bool]:
    normalized: list[str] = []
    valid = True
    for value in values:
        candidate = transform(str(value).strip())
        if not pattern.fullmatch(candidate):
            valid = False
            continue
        normalized.append(candidate)
    return sorted(set(normalized)), valid


def _minimum_date(values: Sequence[str | None]) -> str | None:
    valid = [value for value in values if value is not None]
    return min(valid) if valid else None


def _maximum_date(values: Sequence[str | None]) -> str | None:
    valid = [value for value in values if value is not None]
    return max(valid) if valid else None


def _latest_event_date(
    events: Sequence[StoredBrokerEvidenceEvent],
    *,
    event_type: str,
) -> str | None:
    return _maximum_date(
        [
            _aware_event_date(event.occurred_at)
            for event in events
            if event.event_type == event_type
        ]
    )


def _safe_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _unique_strings(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


legacy_source_resolution_projection = _legacy_source_resolution_projection
item_from_score_component = _item_from_score_component
freshness_item = _freshness_item
readiness_item = _item
db_path_for_state = _db_path_for_state
missing_evidence_scope = _missing_evidence_scope
mapping = _mapping
lineage_allows_inheritance = _lineage_allows_inheritance
scope_with_blocker = _scope_with_blocker
reviewed_scope_fingerprint_matches = _reviewed_scope_fingerprint_matches
scope_fingerprint_core = _scope_fingerprint_core
aware_event_date = _aware_event_date
settlement_date = _settlement_date
safe_observed_codes = _safe_observed_codes
minimum_date = _minimum_date
maximum_date = _maximum_date
latest_event_date = _latest_event_date
safe_nonnegative_int = _safe_nonnegative_int
unique_strings = _unique_strings
fingerprint = _fingerprint
