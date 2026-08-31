"""Persisted-only readiness projection for Account Truth evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from server.account_truth_gate import (
    build_latest_account_truth_promotion_evidence,
    build_latest_account_truth_score_payload,
)
from server.services.account_truth_evidence_readiness_support import (
    ACCOUNT_TRUTH_EVIDENCE_SCOPE_SCHEMA_VERSION,
)
from server.services.account_truth_evidence_readiness_support import (
    db_path_for_state as _db_path_for_state,
)
from server.services.account_truth_evidence_readiness_support import (
    fingerprint as _fingerprint,
)
from server.services.account_truth_evidence_readiness_support import (
    freshness_item as _freshness_item,
)
from server.services.account_truth_evidence_readiness_support import (
    item_from_score_component as _item_from_score_component,
)
from server.services.account_truth_evidence_readiness_support import (
    legacy_source_resolution_projection as _legacy_source_resolution_projection,
)
from server.services.account_truth_evidence_readiness_support import (
    missing_evidence_scope as _missing_evidence_scope,
)
from server.services.account_truth_evidence_readiness_support import (
    readiness_item as _item,
)
from server.services.account_truth_evidence_readiness_support import (
    safe_nonnegative_int as _safe_nonnegative_int,
)
from server.services.account_truth_evidence_readiness_support import (
    unique_strings as _unique_strings,
)
from server.services.account_truth_evidence_scope import (
    apply_account_truth_evidence_scope_review,
    build_account_truth_evidence_scope,
    nonreviewable_account_truth_evidence_scope_blockers,
    project_account_truth_evidence_scope,
)
from server.services.citic_source_follow_up import build_citic_source_follow_up

ACCOUNT_TRUTH_EVIDENCE_READINESS_SCHEMA_VERSION = (
    "karkinos.account_truth.evidence_readiness.v2"
)


def build_account_truth_evidence_readiness(
    state: Any,
    *,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Build one zero-write projection from canonical persisted evidence."""

    db_path = _db_path_for_state(state)
    score = build_latest_account_truth_score_payload(state)
    follow_up = build_citic_source_follow_up(db_path)
    evidence_scope = build_account_truth_evidence_scope(
        db_path=db_path,
        score=score,
    )
    promotion_evidence = (
        build_latest_account_truth_promotion_evidence(state)
        if clock is None
        else build_latest_account_truth_promotion_evidence(state, clock=clock)
    )
    return project_account_truth_evidence_readiness(
        score=score,
        citic_source_follow_up=follow_up,
        evidence_scope=evidence_scope,
        promotion_evidence=promotion_evidence,
    )


def project_account_truth_evidence_readiness(
    *,
    score: dict[str, object],
    citic_source_follow_up: dict[str, object],
    evidence_scope: dict[str, object] | None = None,
    promotion_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    """Project exact evidence gaps without recalculating financial facts."""

    score_available = score.get("status") == "available"
    gate_status = str(score.get("gate_status") or "blocked")
    ledger_coverage = score.get("ledger_coverage")
    ledger_coverage_status = (
        str(ledger_coverage.get("status") or "unknown")
        if isinstance(ledger_coverage, dict)
        else "unknown"
    )
    pending_source_count = _safe_nonnegative_int(
        citic_source_follow_up.get("pending_source_count")
    )
    source_count_complete = citic_source_follow_up.get("count_complete") is True
    source_follow_up_status = str(citic_source_follow_up.get("status") or "unavailable")
    source_follow_up_blockers = _unique_strings(citic_source_follow_up.get("blockers"))
    legacy_source_resolution = _legacy_source_resolution_projection(
        citic_source_follow_up
    )
    effective_scope = evidence_scope or _missing_evidence_scope()
    evidence_scope_status = str(effective_scope.get("status") or "blocked")
    evidence_scope_fingerprint = str(effective_scope.get("evidence_fingerprint") or "")

    snapshot_capture = (
        dict(promotion_evidence.get("snapshot_capture") or {})
        if isinstance(promotion_evidence, dict)
        else {}
    )
    snapshot_blockers = [
        blocker
        for blocker in _unique_strings(
            promotion_evidence.get("blockers")
            if isinstance(promotion_evidence, dict)
            else []
        )
        if blocker.startswith("account_truth_snapshot_")
        or blocker
        in {
            "account_truth_cash_snapshot_missing",
            "account_truth_position_snapshot_missing",
        }
    ]
    snapshot_status = (
        "pass"
        if promotion_evidence is None
        or (
            snapshot_capture.get("status") == "clear"
            and promotion_evidence.get("data_freshness_status") == "fresh"
            and not snapshot_blockers
        )
        else (
            "stale"
            if "account_truth_snapshot_stale" in snapshot_blockers
            else "blocked"
        )
    )
    items = [
        _item(
            requirement="canonical_broker_evidence",
            status="pass" if score_available else "missing",
            evidence_reference=(
                f"account_truth_import:{score.get('import_run_id')}"
                if score_available and score.get("import_run_id")
                else None
            ),
            required_action=(
                None if score_available else "import_and_reconcile_broker_evidence"
            ),
        ),
        _item(
            requirement="reviewed_account_and_period_scope",
            status="pass" if evidence_scope_status == "complete" else "blocked",
            evidence_reference=(
                f"account_truth_evidence_scope:{evidence_scope_fingerprint}"
                if evidence_scope_fingerprint
                else None
            ),
            required_action=(
                None
                if evidence_scope_status == "complete"
                else str(
                    (
                        _unique_strings(effective_scope.get("required_actions"))
                        or ["record_reviewed_account_truth_evidence_scope"]
                    )[0]
                )
            ),
        ),
        _item_from_score_component(
            score=score,
            score_available=score_available,
            requirement="current_cash_snapshot",
            score_field="cash_status",
            required_action="provide_cash_snapshot",
        ),
        _item_from_score_component(
            score=score,
            score_available=score_available,
            requirement="current_position_snapshot",
            score_field="position_status",
            required_action="provide_position_snapshot",
        ),
        _item_from_score_component(
            score=score,
            score_available=score_available,
            requirement="itemized_settlement_fees_and_taxes",
            score_field="fee_status",
            required_action="provide_itemized_settlement_or_cash_flow",
        ),
        _item_from_score_component(
            score=score,
            score_available=score_available,
            requirement="position_cost_basis",
            score_field="cost_basis_status",
            required_action="provide_position_cost_basis_evidence",
        ),
        _freshness_item(
            score=score,
            score_available=score_available,
            ledger_coverage_status=ledger_coverage_status,
        ),
        _item(
            requirement="cash_and_position_snapshot_effective_freshness",
            status=snapshot_status,
            evidence_reference=(
                str(promotion_evidence.get("source_fingerprint") or "") or None
                if isinstance(promotion_evidence, dict)
                else None
            ),
            required_action=(
                None
                if snapshot_status == "pass"
                else "import_current_cash_and_position_snapshots"
            ),
        ),
        _item(
            requirement="reconciliation_gate",
            status=gate_status if score_available else "missing",
            evidence_reference=(
                "account_truth_score:latest" if score_available else None
            ),
            required_action=(
                None if gate_status == "pass" else "resolve_account_truth_blockers"
            ),
        ),
        _item(
            requirement="known_incomplete_source_reviews",
            status=(
                "pass"
                if source_count_complete and pending_source_count == 0
                else "blocked"
            ),
            evidence_reference=str(
                citic_source_follow_up.get("evidence_fingerprint") or ""
            )
            or None,
            required_action=(
                None
                if source_count_complete and pending_source_count == 0
                else str(
                    citic_source_follow_up.get("next_manual_action")
                    or "repair_citic_source_intake_metadata_store"
                )
            ),
        ),
    ]

    blockers = _unique_strings(score.get("blocking_reasons"))
    if not source_count_complete:
        blockers.append(source_follow_up_status)
    elif pending_source_count > 0:
        blockers.append("citic_source_follow_up_required")
    blockers.extend(source_follow_up_blockers)
    blockers.extend(_unique_strings(effective_scope.get("blockers")))
    blockers.extend(snapshot_blockers)
    blockers = list(dict.fromkeys(blockers))

    required_evidence = _unique_strings(citic_source_follow_up.get("required_evidence"))
    required_actions = _unique_strings(score.get("required_actions"))
    required_actions.extend(
        item["required_action"]
        for item in items
        if item["status"] != "pass" and item["required_action"]
    )
    required_actions.extend(_unique_strings(effective_scope.get("required_actions")))
    required_actions = list(dict.fromkeys(required_actions))

    ready = (
        gate_status == "pass"
        and evidence_scope_status == "complete"
        and all(item["status"] == "pass" for item in items)
    )
    projection_core = {
        "schema_version": ACCOUNT_TRUTH_EVIDENCE_READINESS_SCHEMA_VERSION,
        "status": "ready" if ready else "blocked",
        "account_truth_gate_status": gate_status,
        "account_truth_import_run_id": score.get("import_run_id"),
        "score_status": score.get("status") or "missing",
        "score_components": {
            field: score.get(field) or "missing"
            for field in (
                "cash_status",
                "position_status",
                "fee_status",
                "cost_basis_status",
                "data_freshness_status",
            )
        },
        "ledger_coverage_status": ledger_coverage_status,
        "snapshot_capture": snapshot_capture or None,
        "evidence_scope": effective_scope,
        "citic_source_follow_up": {
            "status": source_follow_up_status,
            "pending_source_count": pending_source_count,
            "count_complete": source_count_complete,
            "evidence_fingerprint": citic_source_follow_up.get("evidence_fingerprint"),
            "query_window_batch_integrity_status": str(
                citic_source_follow_up.get("query_window_batch_integrity_status")
                or "not_available"
            ),
            "query_window_batch_assessment_fingerprint": str(
                citic_source_follow_up.get("query_window_batch_assessment_fingerprint")
                or ""
            ),
            "query_window_gap_calendar_day_count": _safe_nonnegative_int(
                citic_source_follow_up.get("query_window_gap_calendar_day_count")
            ),
            "query_window_overlap_calendar_day_count": _safe_nonnegative_int(
                citic_source_follow_up.get("query_window_overlap_calendar_day_count")
            ),
            "query_window_integrity_clear": (
                citic_source_follow_up.get("query_window_integrity_clear") is True
            ),
            "source_scope_batch_integrity_status": str(
                citic_source_follow_up.get("source_scope_batch_integrity_status")
                or "not_available"
            ),
            "source_scope_batch_assessment_fingerprint": str(
                citic_source_follow_up.get("source_scope_batch_assessment_fingerprint")
                or ""
            ),
            "source_scope_integrity_clear": (
                citic_source_follow_up.get("source_scope_integrity_clear") is True
            ),
            "source_scope_account_binding_consistent": (
                citic_source_follow_up.get("source_scope_account_binding_consistent")
                is True
            ),
            "source_scope_declared_scope_consistent": (
                citic_source_follow_up.get("source_scope_declared_scope_consistent")
                is True
            ),
            "source_scope_complete_returned_results_attested": (
                citic_source_follow_up.get(
                    "source_scope_complete_returned_results_attested"
                )
                is True
            ),
            "intake_scan_truncated": (
                citic_source_follow_up.get("intake_scan_truncated") is True
            ),
            "resolution": legacy_source_resolution,
        },
        "items": items,
        "blockers": blockers,
        "required_evidence": required_evidence,
        "required_actions": required_actions,
    }
    return {
        **projection_core,
        "known_incomplete_source_count": pending_source_count,
        "source_review_count_complete": source_count_complete,
        "evidence_fingerprint": _fingerprint(projection_core),
        "next_manual_action": required_actions[0] if required_actions else "none",
        "limitations": [
            "This readiness view projects canonical persisted evidence and does not replace Account Truth or reconciliation.",
            "Observed event ranges are not treated as complete account or time coverage without a separately reviewed scope binding.",
            "Incomplete CITIC History Trades remain non-authoritative source material until missing evidence is explicitly imported and reviewed.",
            "A ready result does not grant broker-write, execution, or capital authority.",
        ],
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "eligible_for_reconciliation": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
