"""Canonical fail-closed projection for current per-order evidence review."""

from __future__ import annotations

from typing import Any, Callable

from server.services.current_per_order_dossier import (
    CURRENT_PER_ORDER_CANDIDATES_SCHEMA_VERSION,
)

AUTOMATION_CURRENT_PER_ORDER_REVIEWS_SCHEMA_VERSION = (
    "karkinos.automation_current_per_order_reviews.v1"
)

_READ_BOUNDARY = {
    "reads_persisted_facts_only": True,
    "provider_contact_performed": False,
    "runtime_connector_query_performed": False,
    "does_not_mutate_oms": True,
    "does_not_mutate_production_ledger": True,
    "does_not_mutate_risk": True,
    "does_not_mutate_kill_switch": True,
    "does_not_change_capital_authority": True,
    "broker_submission_enabled": False,
    "broker_cancel_enabled": False,
    "authorizes_execution": False,
}
_CANDIDATE_FIELDS = (
    "order_id",
    "symbol",
    "side",
    "asset_class",
    "quantity",
    "order_type",
    "limit_price",
    "oms_status",
    "updated_at",
    "order_fingerprint",
    "dossier_fingerprint",
    "review_status",
    "review_ready",
    "review_blockers",
    "evidence_resolution_status",
    "confirmation_status",
    "authorizes_execution",
)


def build_current_per_order_review_summary(
    reader: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    """Validate and project the canonical persisted-only candidate contract."""

    base = {
        "schema_version": AUTOMATION_CURRENT_PER_ORDER_REVIEWS_SCHEMA_VERSION,
        "source_schema_version": "",
        "status": "unavailable",
        "candidate_count": 0,
        "review_ready_count": 0,
        "blocked_review_count": 0,
        "source_truncated": False,
        "next_operator_action": "review_current_per_order_source_unavailable",
        "primary_candidate": None,
        "candidates": [],
        "source_blockers": ["current_per_order_dossier_source_unavailable"],
        **_READ_BOUNDARY,
    }
    if reader is None:
        return base
    try:
        source = reader()
    except Exception:
        return {
            **base,
            "status": "blocked_source",
            "source_blockers": ["current_per_order_dossier_source_failed"],
        }
    if not isinstance(source, dict):
        return {
            **base,
            "status": "blocked_source",
            "source_blockers": ["current_per_order_dossier_source_invalid"],
        }

    source_blockers: list[str] = []
    source_schema_version = str(source.get("schema_version") or "")
    if source_schema_version != CURRENT_PER_ORDER_CANDIDATES_SCHEMA_VERSION:
        source_blockers.append("current_per_order_source_schema_invalid")

    raw_candidates = source.get("candidates")
    if not isinstance(raw_candidates, list):
        source_blockers.append("current_per_order_candidates_invalid")
        candidates: list[dict[str, Any]] = []
    else:
        candidates = [dict(item) for item in raw_candidates if isinstance(item, dict)]
        if len(candidates) != len(raw_candidates):
            source_blockers.append("current_per_order_candidate_contract_invalid")
    if any(not _candidate_contract_is_valid(item) for item in candidates):
        source_blockers.append("current_per_order_candidate_contract_invalid")

    declared_count = _safe_non_negative_int(source.get("candidate_count"))
    if declared_count is None or declared_count != len(candidates):
        source_blockers.append("current_per_order_candidate_count_mismatch")

    raw_truncated = source.get("truncated")
    if not isinstance(raw_truncated, bool):
        source_blockers.append("current_per_order_source_truncation_invalid")
    source_truncated = raw_truncated is True
    if source_truncated:
        source_blockers.append("current_per_order_candidate_source_truncated")

    if any(source.get(key) is not expected for key, expected in _READ_BOUNDARY.items()):
        source_blockers.append("current_per_order_source_boundary_invalid")

    unique_source_blockers = list(dict.fromkeys(source_blockers))
    if unique_source_blockers:
        return {
            **base,
            "source_schema_version": source_schema_version,
            "status": "blocked_source",
            "source_truncated": source_truncated,
            "next_operator_action": "review_current_per_order_source_blockers",
            "source_blockers": unique_source_blockers,
        }

    candidates = [_project_candidate(item) for item in candidates]
    ready = [item for item in candidates if item["review_ready"] is True]
    blocked = [item for item in candidates if item["review_ready"] is False]
    if ready:
        status = "review_ready"
        next_action = "open_trading_current_per_order_review"
        primary = ready[0]
    elif blocked:
        status = "blocked_review"
        next_action = "resolve_current_per_order_evidence_blockers"
        primary = blocked[0]
    else:
        status = "no_current_candidates"
        next_action = "none_default_disabled"
        primary = None
    return {
        **base,
        "source_schema_version": source_schema_version,
        "status": status,
        "candidate_count": len(candidates),
        "review_ready_count": len(ready),
        "blocked_review_count": len(blocked),
        "source_truncated": False,
        "next_operator_action": next_action,
        "primary_candidate": primary,
        "candidates": candidates,
        "source_blockers": [],
    }


def _candidate_contract_is_valid(candidate: dict[str, Any]) -> bool:
    for key in ("order_id", "symbol", "side", "quantity", "review_status"):
        if not isinstance(candidate.get(key), str) or not candidate[key].strip():
            return False
    review_ready = candidate.get("review_ready")
    blockers = candidate.get("review_blockers")
    if not isinstance(review_ready, bool) or not isinstance(blockers, list):
        return False
    if any(not isinstance(item, str) or not item.strip() for item in blockers):
        return False
    if (review_ready and blockers) or (not review_ready and not blockers):
        return False
    return candidate.get("authorizes_execution") is False


def _project_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: candidate.get(key) for key in _CANDIDATE_FIELDS if key in candidate}


def _safe_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None
