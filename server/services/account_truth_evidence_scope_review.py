"""Explicit human review commands for Account Truth evidence scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.evidence_scope_review import (
    EvidenceScopeReviewRejected,
    EvidenceScopeReviewRepository,
)
from server.account_truth_gate import (
    broker_events_for_import_run,
    build_latest_account_truth_score_payload,
)
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_readiness,
    nonreviewable_account_truth_evidence_scope_blockers,
    project_account_truth_evidence_scope,
)


def record_account_truth_evidence_scope_review(
    state: Any,
    *,
    import_run_id: str,
    expected_observed_scope_fingerprint: str,
    provider: str,
    account_alias: str,
    account_reference_hash: str,
    coverage_start_date: str,
    coverage_end_date: str,
    asset_classes: list[str],
    full_account_scope_attested: bool,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    """Persist one exact owner review and return the rebuilt read projection."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        raise EvidenceScopeReviewRejected("account_truth_database_unavailable")
    score = build_latest_account_truth_score_payload(state)
    current_import_run_id = str(score.get("import_run_id") or "")
    if not current_import_run_id:
        raise EvidenceScopeReviewRejected("account_truth_import_run_missing")
    if import_run_id != current_import_run_id:
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_review_import_superseded"
        )

    broker_repository = BrokerEvidenceRepository(db_path)
    import_run = broker_repository.get_import_run(import_run_id)
    if import_run is None:
        raise EvidenceScopeReviewRejected("account_truth_import_run_missing")
    observed_scope = project_account_truth_evidence_scope(
        score=score,
        import_run=import_run,
        events=broker_events_for_import_run(broker_repository, import_run),
    )
    observed_fingerprint = str(observed_scope.get("observed_scope_fingerprint") or "")
    if expected_observed_scope_fingerprint != observed_fingerprint:
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_review_fingerprint_mismatch"
        )
    if nonreviewable_account_truth_evidence_scope_blockers(observed_scope):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_review_evidence_integrity_blocked"
        )
    observed_window = _mapping(observed_scope.get("observed_event_window"))
    if observed_window.get("status") != "available":
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_observed_window_unavailable"
        )
    observed_start = str(observed_window.get("occurred_start_date") or "")
    observed_end = str(observed_window.get("occurred_end_date") or "")
    if coverage_start_date > observed_start or coverage_end_date < observed_end:
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_review_window_incomplete"
        )
    observed_assets = set(
        _strings(
            _mapping(observed_scope.get("asset_scope")).get("observed_asset_classes")
        )
    )
    if not observed_assets or not observed_assets.issubset(
        {str(asset).strip().lower() for asset in asset_classes}
    ):
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_review_assets_incomplete"
        )

    review = EvidenceScopeReviewRepository(db_path).record_review(
        import_run_id=import_run.import_run_id,
        import_file_fingerprint=import_run.file_fingerprint,
        observed_scope_fingerprint=observed_fingerprint,
        provider=provider,
        account_alias=account_alias,
        account_reference_hash=account_reference_hash,
        coverage_start_date=coverage_start_date,
        coverage_end_date=coverage_end_date,
        asset_classes=asset_classes,
        full_account_scope_attested=full_account_scope_attested,
        decision="accepted",
        reviewer=reviewer,
    )
    return _command_response(
        review=review,
        readiness=build_account_truth_evidence_readiness(state),
    )


def revoke_account_truth_evidence_scope_review(
    state: Any,
    *,
    import_run_id: str,
    expected_observed_scope_fingerprint: str,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    """Append one revocation and return the rebuilt blocked projection."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        raise EvidenceScopeReviewRejected("account_truth_database_unavailable")
    score = build_latest_account_truth_score_payload(state)
    if str(score.get("import_run_id") or "") != import_run_id:
        raise EvidenceScopeReviewRejected(
            "account_truth_evidence_scope_review_import_superseded"
        )
    review = EvidenceScopeReviewRepository(db_path).revoke_latest(
        import_run_id=import_run_id,
        expected_observed_scope_fingerprint=expected_observed_scope_fingerprint,
        reviewer=reviewer,
    )
    return _command_response(
        review=review,
        readiness=build_account_truth_evidence_readiness(state),
    )


def _db_path_for_state(state: Any) -> Path | None:
    path = getattr(getattr(state, "db", None), "_path", None)
    return Path(path) if path is not None else None


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _command_response(
    *, review: Any, readiness: dict[str, object]
) -> dict[str, object]:
    return {
        "schema_version": "karkinos.account_truth.evidence_scope_review_command.v1",
        "status": "recorded" if review.decision == "accepted" else "revoked",
        "review": {
            "review_id": review.review_id,
            "schema_version": review.schema_version,
            "import_run_id": review.import_run_id,
            "observed_scope_fingerprint": review.observed_scope_fingerprint,
            "decision": review.decision,
            "review_fingerprint": review.review_fingerprint,
            "created_at": review.created_at,
            "reused": review.reused,
        },
        "readiness": readiness,
        "scope_review_write_performed": not review.reused,
        "writes_only_scope_review_store": True,
        "does_not_mutate_broker_evidence": True,
        "does_not_mutate_production_ledger": True,
        "does_not_reconcile_account": True,
        "provider_contacted": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
