"""Human commands resolving reviewed legacy CITIC sources to canonical evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from account_truth.citic_source_canonical_resolution import (
    CiticSourceCanonicalResolutionRejected,
    CiticSourceCanonicalResolutionRepository,
    citic_source_set_fingerprint,
)
from account_truth.citic_source_intake import CiticSourceIntakeRepository
from account_truth.evidence_scope_review import EvidenceScopeReviewRepository
from server.account_truth_gate import build_latest_account_truth_score_payload
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_scope,
)
from server.services.citic_source_follow_up import build_citic_source_follow_up


def record_citic_source_canonical_resolution(
    state: Any,
    *,
    expected_source_set_fingerprint: str,
    expected_scope_review_id: str,
    expected_scope_review_fingerprint: str,
    canonical_statement_covers_sources_attested: bool,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    """Resolve the exact current legacy source set against one active scope review."""

    if canonical_statement_covers_sources_attested is not True:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_attestation_required"
        )
    db_path = _db_path_for_state(state)
    if db_path is None:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_database_unavailable"
        )

    score = build_latest_account_truth_score_payload(state)
    scope = build_account_truth_evidence_scope(db_path=db_path, score=score)
    if scope.get("status") != "complete":
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_account_scope_not_complete"
        )
    review_binding = _mapping(scope.get("review"))
    if review_binding.get("decision") != "accepted":
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_scope_review_not_active"
        )
    review_id = str(review_binding.get("review_id") or "")
    review_fingerprint = str(review_binding.get("review_fingerprint") or "")
    reviewed_import_run_id = str(
        review_binding.get("reviewed_import_run_id") or score.get("import_run_id") or ""
    )
    if expected_scope_review_id != review_id:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_scope_review_id_drift"
        )
    if expected_scope_review_fingerprint != review_fingerprint:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_scope_review_fingerprint_drift"
        )

    persisted_review = EvidenceScopeReviewRepository(db_path).get_latest_review(
        reviewed_import_run_id
    )
    if (
        persisted_review is None
        or persisted_review.decision != "accepted"
        or persisted_review.review_id != review_id
        or persisted_review.review_fingerprint != review_fingerprint
    ):
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_scope_review_binding_drift"
        )

    intakes = CiticSourceIntakeRepository(db_path).list_intakes(limit=200)
    if len(intakes) >= 200:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_source_scan_truncated"
        )
    sources = sorted(
        {
            item.source_preview_fingerprint
            for item in intakes
            if item.review_status == "follow_up_required"
        }
    )
    if not sources:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_sources_missing"
        )
    if citic_source_set_fingerprint(sources) != expected_source_set_fingerprint:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_source_set_drift"
        )

    resolution = CiticSourceCanonicalResolutionRepository(db_path).record_resolution(
        source_preview_fingerprints=sources,
        expected_source_set_fingerprint=expected_source_set_fingerprint,
        scope_review_id=review_id,
        scope_review_import_run_id=reviewed_import_run_id,
        scope_review_fingerprint=review_fingerprint,
        reviewer=reviewer,
    )
    return _command_response(
        resolution=resolution,
        follow_up=build_citic_source_follow_up(db_path),
    )


def revoke_citic_source_canonical_resolution(
    state: Any,
    *,
    expected_resolution_id: str,
    expected_resolution_fingerprint: str,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    """Revoke the latest resolution so covered source follow-up reopens."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_database_unavailable"
        )
    resolution = CiticSourceCanonicalResolutionRepository(db_path).revoke_latest(
        expected_resolution_id=expected_resolution_id,
        expected_resolution_fingerprint=expected_resolution_fingerprint,
        reviewer=reviewer,
    )
    return _command_response(
        resolution=resolution,
        follow_up=build_citic_source_follow_up(db_path),
    )


def current_citic_source_set_fingerprint(state: Any) -> str:
    """Return the exact sanitized pending-source set fingerprint for review UI."""

    db_path = _db_path_for_state(state)
    if db_path is None:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_database_unavailable"
        )
    intakes = CiticSourceIntakeRepository(db_path).list_intakes(limit=200)
    if len(intakes) >= 200:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_source_scan_truncated"
        )
    sources = [
        item.source_preview_fingerprint
        for item in intakes
        if item.review_status == "follow_up_required"
    ]
    if not sources:
        raise CiticSourceCanonicalResolutionRejected(
            "citic_source_canonical_resolution_sources_missing"
        )
    return citic_source_set_fingerprint(sources)


def _command_response(
    *, resolution: Any, follow_up: dict[str, object]
) -> dict[str, object]:
    return {
        "schema_version": (
            "karkinos.account_truth.citic_source_canonical_resolution_command.v1"
        ),
        "status": "recorded" if resolution.decision == "accepted" else "revoked",
        "resolution": {
            "resolution_id": resolution.resolution_id,
            "schema_version": resolution.schema_version,
            "source_set_fingerprint": resolution.source_set_fingerprint,
            "covered_source_count": len(resolution.source_preview_fingerprints),
            "scope_review_id": resolution.scope_review_id,
            "scope_review_import_run_id": resolution.scope_review_import_run_id,
            "scope_review_fingerprint": resolution.scope_review_fingerprint,
            "decision": resolution.decision,
            "resolution_fingerprint": resolution.resolution_fingerprint,
            "created_at": resolution.created_at,
            "reused": resolution.reused,
        },
        "citic_source_follow_up": follow_up,
        "writes_only_canonical_resolution_store": True,
        "does_not_mutate_broker_evidence": True,
        "does_not_mutate_production_ledger": True,
        "does_not_reconcile_account": True,
        "provider_contacted": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _db_path_for_state(state: Any) -> Path | None:
    path = getattr(getattr(state, "db", None), "_path", None)
    return Path(path) if path is not None else None


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}
