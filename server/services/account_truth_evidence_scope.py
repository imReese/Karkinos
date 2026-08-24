"""Account Truth evidence-scope projection and human-review binding."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from account_truth.broker_evidence import (
    BrokerEvidenceRepository,
    BrokerImportRun,
    StoredBrokerEvidenceEvent,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReview,
    EvidenceScopeReviewRepository,
)
from account_truth.source_fact_continuity import (
    assess_account_truth_source_fact_history_continuity,
    source_fact_continuity_allows_inheritance,
)
from account_truth.source_fact_lineage import (
    account_truth_scope_review_binding_fingerprint,
    project_account_truth_source_fact_lineage,
)
from server.account_truth_gate import broker_events_for_import_run
from server.services.account_truth_evidence_readiness_support import (
    ACCOUNT_TRUTH_EVIDENCE_SCOPE_SCHEMA_VERSION,
)
from server.services.account_truth_evidence_readiness_support import (
    aware_event_date as _aware_event_date,
)
from server.services.account_truth_evidence_readiness_support import (
    fingerprint as _fingerprint,
)
from server.services.account_truth_evidence_readiness_support import (
    latest_event_date as _latest_event_date,
)
from server.services.account_truth_evidence_readiness_support import (
    lineage_allows_inheritance as _lineage_allows_inheritance,
)
from server.services.account_truth_evidence_readiness_support import mapping as _mapping
from server.services.account_truth_evidence_readiness_support import (
    maximum_date as _maximum_date,
)
from server.services.account_truth_evidence_readiness_support import (
    minimum_date as _minimum_date,
)
from server.services.account_truth_evidence_readiness_support import (
    reviewed_scope_fingerprint_matches as _reviewed_scope_fingerprint_matches,
)
from server.services.account_truth_evidence_readiness_support import (
    safe_observed_codes as _safe_observed_codes,
)
from server.services.account_truth_evidence_readiness_support import (
    scope_fingerprint_core as _scope_fingerprint_core,
)
from server.services.account_truth_evidence_readiness_support import (
    scope_with_blocker as _scope_with_blocker,
)
from server.services.account_truth_evidence_readiness_support import (
    settlement_date as _settlement_date,
)
from server.services.account_truth_evidence_readiness_support import (
    unique_strings as _unique_strings,
)

_REVIEWABLE_EVIDENCE_SCOPE_BLOCKERS = frozenset(
    {
        "account_truth_account_scope_unbound",
        "account_truth_coverage_window_undeclared",
        "account_truth_asset_scope_completeness_unverified",
    }
)
_SAFE_CURRENCY = re.compile(r"^[A-Z]{3}$")


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
    review_repository = (
        EvidenceScopeReviewRepository(db_path)
        if db_path is not None and import_run_id
        else None
    )
    review = (
        review_repository.get_latest_review(import_run_id)
        if review_repository is not None
        else None
    )
    reviewed_import_run: BrokerImportRun | None = None
    reviewed_observed_scope: dict[str, object] | None = None
    continuity: dict[str, object] | None = None
    inherited = False
    if (
        review is None
        and review_repository is not None
        and import_run is not None
        and _lineage_allows_inheritance(observed_scope)
    ):
        candidates = review_repository.list_latest_reviews_across_imports(limit=1000)
        for candidate in candidates:
            if candidate.import_run_id == import_run.import_run_id:
                continue
            candidate_import = repository.get_import_run(candidate.import_run_id)
            if candidate_import is None:
                continue
            candidate_events = broker_events_for_import_run(
                repository, candidate_import
            )
            candidate_scope = project_account_truth_evidence_scope(
                score={**score, "import_run_id": candidate_import.import_run_id},
                import_run=candidate_import,
                events=candidate_events,
            )
            candidate_continuity = assess_account_truth_source_fact_history_continuity(
                repository=repository,
                current_import=import_run,
                reviewed_import=candidate_import,
            )
            if not source_fact_continuity_allows_inheritance(candidate_continuity):
                continue
            review = candidate
            reviewed_import_run = candidate_import
            reviewed_observed_scope = candidate_scope
            continuity = candidate_continuity
            inherited = True
            break
        if review is None and len(candidates) == 1000:
            return _scope_with_blocker(
                observed_scope,
                "account_truth_evidence_scope_review_lineage_scan_truncated",
            )
        if review is None and candidates:
            return _scope_with_blocker(
                observed_scope,
                "account_truth_evidence_scope_review_lineage_drift",
            )
    return apply_account_truth_evidence_scope_review(
        observed_scope=observed_scope,
        import_run=import_run,
        review=review,
        reviewed_import_run=reviewed_import_run,
        reviewed_observed_scope=reviewed_observed_scope,
        continuity=continuity,
        inherited=inherited,
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
    source_fact_lineage = (
        project_account_truth_source_fact_lineage(
            import_run=import_run,
            events=events,
        )
        if import_run is not None
        else {
            "status": "blocked",
            "source_fact_fingerprint": None,
            "derived_snapshot_count": 0,
            "blockers": ["account_truth_source_fact_lineage_import_missing"],
        }
    )

    unique_events = [event for event in events if not event.is_row_duplicate]
    occurred_dates = [_aware_event_date(event.occurred_at) for event in unique_events]
    settlement_values = [event.settled_at.strip() for event in unique_events]
    settled_dates = [_settlement_date(value) for value in settlement_values if value]
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
    blockers.extend(_unique_strings(source_fact_lineage.get("blockers")))

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
        "source_fact_lineage": source_fact_lineage,
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
            "settlement_date_missing_count": sum(
                not value for value in settlement_values
            ),
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
    reviewed_import_run: BrokerImportRun | None = None,
    reviewed_observed_scope: dict[str, object] | None = None,
    continuity: dict[str, object] | None = None,
    inherited: bool = False,
) -> dict[str, object]:
    """Apply one exact or materially continuous human scope review."""

    if review is None:
        return observed_scope
    blockers = nonreviewable_account_truth_evidence_scope_blockers(observed_scope)
    review_scope = reviewed_observed_scope if inherited else observed_scope
    review_import = reviewed_import_run if inherited else import_run
    review_scope_fingerprint = str(
        (review_scope or {}).get("observed_scope_fingerprint") or ""
    )
    if review_import is None or review.import_run_id != review_import.import_run_id:
        blockers.append("account_truth_evidence_scope_review_import_mismatch")
    elif review.import_file_fingerprint != review_import.file_fingerprint:
        blockers.append("account_truth_evidence_scope_review_source_drift")
    if not _reviewed_scope_fingerprint_matches(
        review.observed_scope_fingerprint,
        review_scope or {},
    ):
        blockers.append("account_truth_evidence_scope_review_observed_drift")
    if inherited and not source_fact_continuity_allows_inheritance(continuity):
        blockers.append("account_truth_evidence_scope_review_lineage_drift")
    if review.decision == "revoked":
        blockers.append("account_truth_evidence_scope_review_revoked")

    observed_window = _mapping(observed_scope.get("observed_event_window"))
    observed_start = str(observed_window.get("occurred_start_date") or "")
    observed_end = str(observed_window.get("occurred_end_date") or "")
    if (
        not observed_start
        or not observed_end
        or review.coverage_start_date > observed_start
        or (not inherited and review.coverage_end_date < observed_end)
    ):
        blockers.append("account_truth_evidence_scope_review_window_incomplete")

    reviewed_asset_scope = _mapping(observed_scope.get("asset_scope"))
    observed_assets = set(
        _unique_strings(reviewed_asset_scope.get("observed_asset_classes"))
    )
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
        "binding_mode": (
            (
                "inherited_source_fact_lineage"
                if str((continuity or {}).get("mode") or "")
                == "daily_snapshot_roll_forward"
                else "inherited_source_fact_continuity"
            )
            if inherited
            else "exact_import"
        ),
        "reviewed_import_run_id": review.import_run_id,
        "continuity": continuity if inherited else None,
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

    current_asset_scope = _mapping(observed_scope.get("asset_scope"))
    current_source_fact_fingerprint = str(
        _mapping(observed_scope.get("source_fact_lineage")).get(
            "source_fact_fingerprint"
        )
        or ""
    )
    source_fact_fingerprint = (
        str((continuity or {}).get("reviewed_source_fact_fingerprint") or "")
        if inherited
        else current_source_fact_fingerprint
    )
    review_binding_fingerprint = account_truth_scope_review_binding_fingerprint(
        review,
        source_fact_fingerprint=source_fact_fingerprint,
    )
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
            "end_date": (
                max(review.coverage_end_date, observed_end)
                if inherited
                else review.coverage_end_date
            ),
            **(
                {
                    "reviewed_end_date": review.coverage_end_date,
                    "extension_mode": "materially_continuous_canonical_source",
                }
                if inherited
                else {}
            ),
        },
        "asset_scope": {
            **current_asset_scope,
            "status": "complete",
            "reviewed_asset_classes": review.asset_classes,
        },
        "review": review_payload,
        "source_fact_continuity": continuity if inherited else None,
        "review_binding_source_fact_fingerprint": source_fact_fingerprint,
        "review_binding_fingerprint": review_binding_fingerprint,
        "blockers": [],
        "required_actions": [],
        "limitations": [
            *_unique_strings(observed_scope.get("limitations")),
            "Scope completeness is an explicit local-owner review bound to exact or materially continuous persisted evidence; it is not a broker assertion or execution authority.",
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
