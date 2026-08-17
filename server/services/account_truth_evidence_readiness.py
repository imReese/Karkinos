"""Persisted-only readiness projection for Account Truth evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReview,
    EvidenceScopeReviewRepository,
)
from server.account_truth_gate import (
    broker_events_for_import_run,
    build_latest_account_truth_promotion_evidence,
    build_latest_account_truth_score_payload,
)
from server.services.citic_source_follow_up import build_citic_source_follow_up

ACCOUNT_TRUTH_EVIDENCE_READINESS_SCHEMA_VERSION = (
    "karkinos.account_truth.evidence_readiness.v2"
)
ACCOUNT_TRUTH_EVIDENCE_SCOPE_SCHEMA_VERSION = "karkinos.account_truth.evidence_scope.v1"
_REVIEWABLE_EVIDENCE_SCOPE_BLOCKERS = frozenset(
    {
        "account_truth_account_scope_unbound",
        "account_truth_coverage_window_undeclared",
        "account_truth_asset_scope_completeness_unverified",
    }
)
_SAFE_SCOPE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]{0,63}$")
_SAFE_CURRENCY = re.compile(r"^[A-Z]{3}$")


def build_account_truth_evidence_readiness(state: Any) -> dict[str, object]:
    """Build one zero-write projection from canonical persisted evidence."""

    db_path = _db_path_for_state(state)
    score = build_latest_account_truth_score_payload(state)
    follow_up = build_citic_source_follow_up(db_path)
    evidence_scope = build_account_truth_evidence_scope(
        db_path=db_path,
        score=score,
    )
    promotion_evidence = build_latest_account_truth_promotion_evidence(state)
    return project_account_truth_evidence_readiness(
        score=score,
        citic_source_follow_up=follow_up,
        evidence_scope=evidence_scope,
        promotion_evidence=promotion_evidence,
    )


def build_account_truth_evidence_scope(
    *,
    db_path: Path | None,
    score: dict[str, object],
) -> dict[str, object]:
    """Read the selected canonical import and project its provable scope."""

    import_run: BrokerImportRun | None = None
    events: list[StoredBrokerEvidenceEvent] = []
    import_run_id = str(score.get("import_run_id") or "").strip()
    if db_path is not None and import_run_id:
        repository = BrokerEvidenceRepository(db_path)
        import_run = repository.get_import_run(import_run_id)
        if import_run is not None:
            events = broker_events_for_import_run(repository, import_run)
    observed_scope = project_account_truth_evidence_scope(
        score=score,
        import_run=import_run,
        events=events,
    )
    review = (
        EvidenceScopeReviewRepository(db_path).get_latest_review(import_run_id)
        if db_path is not None and import_run_id
        else None
    )
    return apply_account_truth_evidence_scope_review(
        observed_scope=observed_scope,
        import_run=import_run,
        review=review,
    )


def project_account_truth_evidence_scope(
    *,
    score: dict[str, object],
    import_run: BrokerImportRun | None,
    events: Sequence[StoredBrokerEvidenceEvent],
) -> dict[str, object]:
    """Separate observed event span from reviewed account/period coverage."""

    score_import_run_id = str(score.get("import_run_id") or "").strip()
    selected_import_run_id = (
        str(import_run.import_run_id).strip() if import_run is not None else ""
    )
    import_matches_score = bool(
        score_import_run_id
        and selected_import_run_id
        and score_import_run_id == selected_import_run_id
    )
    expected_event_count = int(import_run.valid_row_count) if import_run else 0
    event_count_matches = import_matches_score and len(events) == expected_event_count

    unique_events = [event for event in events if not event.is_row_duplicate]
    occurred_dates = [_aware_event_date(event.occurred_at) for event in unique_events]
    settled_dates = [_settlement_date(event.settled_at) for event in unique_events]
    timestamps_valid = (
        bool(unique_events) and all(occurred_dates) and all(settled_dates)
    )

    observed_asset_classes, asset_codes_valid = _safe_observed_codes(
        event.asset_class for event in unique_events if event.asset_class.strip()
    )
    observed_currencies, currency_codes_valid = _safe_observed_codes(
        (event.currency for event in unique_events if event.currency.strip()),
        pattern=_SAFE_CURRENCY,
        transform=str.upper,
    )
    observed_event_types, event_type_codes_valid = _safe_observed_codes(
        event.event_type for event in unique_events if event.event_type.strip()
    )
    scope_codes_valid = (
        asset_codes_valid and currency_codes_valid and event_type_codes_valid
    )

    observed_window_status = (
        "available"
        if timestamps_valid and event_count_matches
        else "missing" if not unique_events else "blocked"
    )
    blockers = [
        "account_truth_account_scope_unbound",
        "account_truth_coverage_window_undeclared",
        "account_truth_asset_scope_completeness_unverified",
    ]
    if score_import_run_id and not import_matches_score:
        blockers.append("account_truth_evidence_scope_import_mismatch")
    if import_matches_score and not event_count_matches:
        blockers.append("account_truth_evidence_scope_event_count_mismatch")
    if unique_events and not timestamps_valid:
        blockers.append("account_truth_observed_event_time_invalid")
    if not scope_codes_valid:
        blockers.append("account_truth_observed_scope_code_invalid")
    if not unique_events:
        blockers.append("account_truth_observed_events_missing")

    required_actions = [
        "bind_account_truth_evidence_to_reviewed_account_scope",
        "record_reviewed_account_truth_coverage_window",
        "review_account_truth_asset_scope_completeness",
    ]
    core = {
        "schema_version": ACCOUNT_TRUTH_EVIDENCE_SCOPE_SCHEMA_VERSION,
        "status": "blocked",
        "import_run_id": selected_import_run_id or None,
        "source_schema_version": (
            str(import_run.schema_version) if import_run is not None else None
        ),
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
            "status": observed_window_status,
            "occurred_start_date": _minimum_date(occurred_dates),
            "occurred_end_date": _maximum_date(occurred_dates),
            "settled_start_date": _minimum_date(settled_dates),
            "settled_end_date": _maximum_date(settled_dates),
            "event_count": len(events),
            "unique_event_count": len(unique_events),
            "expected_event_count": expected_event_count,
        },
        "asset_scope": {
            "status": "unverified",
            "observed_asset_classes": observed_asset_classes,
            "observed_currencies": observed_currencies,
            "observed_event_types": observed_event_types,
        },
        "snapshot_evidence": {
            "cash_snapshot_count": sum(
                event.event_type == "cash_snapshot" for event in unique_events
            ),
            "position_snapshot_count": sum(
                event.event_type == "position_snapshot" for event in unique_events
            ),
            "latest_cash_snapshot_date": _latest_event_date(
                unique_events,
                event_type="cash_snapshot",
            ),
            "latest_position_snapshot_date": _latest_event_date(
                unique_events,
                event_type="position_snapshot",
            ),
        },
        "blockers": list(dict.fromkeys(blockers)),
        "required_actions": required_actions,
    }
    observed_scope_fingerprint = _fingerprint(core)
    return {
        **core,
        "observed_scope_fingerprint": observed_scope_fingerprint,
        "evidence_fingerprint": observed_scope_fingerprint,
        "review": None,
        "limitations": [
            "Observed event dates prove only the span of persisted rows; they do not prove complete account coverage for that period.",
            "The current canonical broker-evidence schema does not bind the import to a reviewed account alias or account-reference hash.",
            "Observed asset classes do not prove that every asset held by the account was included in the source export.",
        ],
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def apply_account_truth_evidence_scope_review(
    *,
    observed_scope: dict[str, object],
    import_run: BrokerImportRun | None,
    review: EvidenceScopeReview | None,
) -> dict[str, object]:
    """Apply one exact, current human review without weakening observed facts."""

    if review is None:
        return observed_scope
    blockers = nonreviewable_account_truth_evidence_scope_blockers(observed_scope)
    observed_fingerprint = str(observed_scope.get("observed_scope_fingerprint") or "")
    if import_run is None or review.import_run_id != import_run.import_run_id:
        blockers.append("account_truth_evidence_scope_review_import_mismatch")
    elif review.import_file_fingerprint != import_run.file_fingerprint:
        blockers.append("account_truth_evidence_scope_review_source_drift")
    if review.observed_scope_fingerprint != observed_fingerprint:
        blockers.append("account_truth_evidence_scope_review_observed_drift")
    if review.decision == "revoked":
        blockers.append("account_truth_evidence_scope_review_revoked")

    observed_window = _mapping(observed_scope.get("observed_event_window"))
    observed_start = str(observed_window.get("occurred_start_date") or "")
    observed_end = str(observed_window.get("occurred_end_date") or "")
    if (
        not observed_start
        or not observed_end
        or review.coverage_start_date > observed_start
        or review.coverage_end_date < observed_end
    ):
        blockers.append("account_truth_evidence_scope_review_window_incomplete")

    asset_scope = _mapping(observed_scope.get("asset_scope"))
    observed_assets = set(_unique_strings(asset_scope.get("observed_asset_classes")))
    if not observed_assets.issubset(set(review.asset_classes)):
        blockers.append("account_truth_evidence_scope_review_assets_incomplete")
    if review.full_account_scope_attested is not True:
        blockers.append("account_truth_evidence_scope_review_attestation_missing")

    review_payload = {
        "schema_version": review.schema_version,
        "review_id": review.review_id,
        "decision": review.decision,
        "provider": review.provider,
        "review_fingerprint": review.review_fingerprint,
        "reviewed_at": review.created_at,
    }
    if blockers:
        blocked = {
            **observed_scope,
            "status": "blocked",
            "review": review_payload,
            "blockers": list(
                dict.fromkeys(
                    [
                        *_unique_strings(observed_scope.get("blockers")),
                        *blockers,
                    ]
                )
            ),
            "required_actions": ["record_reviewed_account_truth_evidence_scope"],
        }
        blocked["evidence_fingerprint"] = _fingerprint(_scope_fingerprint_core(blocked))
        return blocked

    complete = {
        **observed_scope,
        "status": "complete",
        "account_binding": {
            "status": "bound",
            "provider": review.provider,
            "account_alias": review.account_alias,
            "account_reference_hash": review.account_reference_hash,
        },
        "declared_coverage_window": {
            "status": "complete",
            "start_date": review.coverage_start_date,
            "end_date": review.coverage_end_date,
        },
        "asset_scope": {
            **asset_scope,
            "status": "complete",
            "reviewed_asset_classes": review.asset_classes,
        },
        "review": review_payload,
        "blockers": [],
        "required_actions": [],
        "limitations": [
            *_unique_strings(observed_scope.get("limitations")),
            "Scope completeness is an explicit local-owner review bound to exact persisted evidence; it is not a broker assertion or execution authority.",
        ],
    }
    complete["evidence_fingerprint"] = _fingerprint(_scope_fingerprint_core(complete))
    return complete


def nonreviewable_account_truth_evidence_scope_blockers(
    evidence_scope: dict[str, object],
) -> list[str]:
    """Return persisted-evidence integrity blockers no human scope claim can clear."""

    return [
        blocker
        for blocker in _unique_strings(evidence_scope.get("blockers"))
        if blocker not in _REVIEWABLE_EVIDENCE_SCOPE_BLOCKERS
    ]


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
