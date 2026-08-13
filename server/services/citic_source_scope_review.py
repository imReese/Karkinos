"""Commands and sanitized projections for reviewed CITIC source scope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from account_truth.citic_source_intake import CiticSourceIntake
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReview,
)
from account_truth.citic_source_scope_review import (
    CiticSourceScopeReview,
    CiticSourceScopeReviewRejected,
    CiticSourceScopeReviewRepository,
)

CITIC_SOURCE_SCOPE_REVIEW_COMMAND_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_scope_review_command.v2"
)
CITIC_SOURCE_SCOPE_BATCH_ASSESSMENT_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_source_scope_batch_assessment.v2"
)


def record_citic_source_scope_review(
    state: Any,
    *,
    intake_id: str,
    expected_file_fingerprint: str,
    expected_source_preview_fingerprint: str,
    expected_query_window_review_id: str,
    expected_query_window_review_fingerprint: str,
    account_alias: str,
    account_reference_hash: str,
    account_type: str,
    market_scopes: list[str],
    asset_classes: list[str],
    account_value_band: str,
    business_types: list[str],
    no_other_filters_attested: bool,
    complete_returned_results_attested: bool,
    source_scope_attested: bool,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    review = CiticSourceScopeReviewRepository(_required_db_path(state)).record_review(
        intake_id=intake_id,
        expected_file_fingerprint=expected_file_fingerprint,
        expected_source_preview_fingerprint=expected_source_preview_fingerprint,
        expected_query_window_review_id=expected_query_window_review_id,
        expected_query_window_review_fingerprint=(
            expected_query_window_review_fingerprint
        ),
        account_alias=account_alias,
        account_reference_hash=account_reference_hash,
        account_type=account_type,
        market_scopes=market_scopes,
        asset_classes=asset_classes,
        account_value_band=account_value_band,
        business_types=business_types,
        no_other_filters_attested=no_other_filters_attested,
        complete_returned_results_attested=complete_returned_results_attested,
        source_scope_attested=source_scope_attested,
        reviewer=reviewer,
    )
    return _command_response(review=review)


def revoke_citic_source_scope_review(
    state: Any,
    *,
    intake_id: str,
    expected_active_review_id: str,
    expected_active_review_fingerprint: str,
    reviewer: str = "local_owner",
) -> dict[str, object]:
    review = CiticSourceScopeReviewRepository(_required_db_path(state)).revoke_latest(
        intake_id=intake_id,
        expected_active_review_id=expected_active_review_id,
        expected_active_review_fingerprint=expected_active_review_fingerprint,
        reviewer=reviewer,
    )
    return _command_response(review=review)


def latest_citic_source_scope_reviews_by_intake(
    db_path: str | Path,
    *,
    intakes: Sequence[CiticSourceIntake],
) -> dict[str, CiticSourceScopeReview]:
    repository = CiticSourceScopeReviewRepository(db_path)
    return {
        intake.intake_id: review
        for intake in intakes
        if (review := repository.get_latest_review(intake.intake_id)) is not None
    }


def active_citic_source_scope_review(
    *,
    source: CiticSourceIntake,
    query_window_review: CiticSourceQueryWindowReview | None,
    source_scope_review: CiticSourceScopeReview | None,
) -> CiticSourceScopeReview | None:
    if (
        query_window_review is None
        or query_window_review.decision != "accepted"
        or source_scope_review is None
        or source_scope_review.decision != "accepted"
        or source_scope_review.intake_id != source.intake_id
        or source_scope_review.file_fingerprint != source.file_fingerprint
        or source_scope_review.source_preview_fingerprint
        != source.source_preview_fingerprint
        or source_scope_review.query_window_review_id != query_window_review.review_id
        or source_scope_review.query_window_review_fingerprint
        != query_window_review.review_fingerprint
    ):
        return None
    return source_scope_review


def project_citic_source_scope_batch_assessment(
    *,
    source_count: int,
    active_query_window_reviews: Sequence[CiticSourceQueryWindowReview],
    active_scope_reviews: Sequence[CiticSourceScopeReview],
) -> dict[str, object]:
    """Assess exact-source scope attestations without promoting legacy XLS."""

    source_count_valid = (
        isinstance(source_count, int)
        and not isinstance(source_count, bool)
        and source_count >= 0
    )
    effective_source_count = source_count if source_count_valid else 0
    query_by_intake: dict[str, CiticSourceQueryWindowReview] = {}
    invalid_query_review_count = 0
    for review in active_query_window_reviews:
        intake_id = str(getattr(review, "intake_id", ""))
        if (
            getattr(review, "decision", None) != "accepted"
            or getattr(review, "query_window_attested", None) is not True
            or not intake_id.startswith("citic_intake_")
            or intake_id in query_by_intake
            or not _sha256_fingerprint_is_valid(
                str(getattr(review, "review_fingerprint", ""))
            )
        ):
            invalid_query_review_count += 1
            continue
        query_by_intake[intake_id] = review

    valid_scope_reviews: list[CiticSourceScopeReview] = []
    invalid_scope_review_count = 0
    seen_intakes: set[str] = set()
    identity_rows: list[dict[str, object]] = []
    for review in active_scope_reviews:
        intake_id = str(getattr(review, "intake_id", ""))
        query_review = query_by_intake.get(intake_id)
        if (
            getattr(review, "decision", None) != "accepted"
            or getattr(review, "no_other_filters_attested", None) is not True
            or getattr(review, "complete_returned_results_attested", None) is not True
            or getattr(review, "source_scope_attested", None) is not True
            or not intake_id.startswith("citic_intake_")
            or intake_id in seen_intakes
            or query_review is None
            or review.query_window_review_id != query_review.review_id
            or review.query_window_review_fingerprint != query_review.review_fingerprint
            or review.file_fingerprint != query_review.file_fingerprint
            or review.source_preview_fingerprint
            != query_review.source_preview_fingerprint
            or not _sha256_fingerprint_is_valid(review.account_reference_hash)
            or not _sha256_fingerprint_is_valid(review.review_fingerprint)
            or not review.market_scopes
            or not review.asset_classes
            or not review.account_value_band
            or not review.business_types
        ):
            invalid_scope_review_count += 1
            continue
        seen_intakes.add(intake_id)
        valid_scope_reviews.append(review)
        identity_rows.append(
            {
                "intake_id": intake_id,
                "query_window_review_fingerprint": (
                    review.query_window_review_fingerprint
                ),
                "source_scope_review_fingerprint": review.review_fingerprint,
                "account_alias": review.account_alias,
                "account_reference_hash": review.account_reference_hash,
                "account_type": review.account_type,
                "market_scopes": list(review.market_scopes),
                "asset_classes": list(review.asset_classes),
                "account_value_band": review.account_value_band,
                "business_types": list(review.business_types),
            }
        )

    reviewed_source_count = len(valid_scope_reviews)
    unreviewed_source_count = max(
        0,
        effective_source_count - reviewed_source_count,
    )
    all_current_sources_reviewed = bool(
        source_count_valid
        and effective_source_count > 0
        and invalid_query_review_count == 0
        and invalid_scope_review_count == 0
        and len(query_by_intake) == effective_source_count
        and reviewed_source_count == effective_source_count
        and len(active_scope_reviews) == effective_source_count
    )
    account_bindings = {
        (
            review.account_alias,
            review.account_reference_hash,
            review.account_type,
        )
        for review in valid_scope_reviews
    }
    declared_scopes = {
        (
            tuple(review.market_scopes),
            tuple(review.asset_classes),
            review.account_value_band,
            tuple(review.business_types),
        )
        for review in valid_scope_reviews
    }
    account_binding_consistent = (
        bool(valid_scope_reviews) and len(account_bindings) == 1
    )
    declared_scope_consistent = bool(valid_scope_reviews) and len(declared_scopes) == 1
    account_scope_bound = all_current_sources_reviewed and account_binding_consistent
    declared_source_scope_complete = (
        all_current_sources_reviewed and declared_scope_consistent
    )
    attestations_complete = (
        all(
            review.no_other_filters_attested
            and review.complete_returned_results_attested
            and review.source_scope_attested
            for review in valid_scope_reviews
        )
        and reviewed_source_count == effective_source_count > 0
    )

    blockers = ["citic_source_scope_batch_complete_account_coverage_unproven"]
    if not source_count_valid:
        blockers.append("citic_source_scope_batch_source_count_invalid")
    if effective_source_count == 0:
        blockers.append("citic_source_scope_batch_sources_missing")
    if invalid_query_review_count:
        blockers.append("citic_source_scope_batch_query_window_review_invalid")
    if invalid_scope_review_count:
        blockers.append("citic_source_scope_batch_review_invalid")
    if unreviewed_source_count:
        blockers.append("citic_source_scope_batch_sources_unreviewed")
    if valid_scope_reviews and not account_binding_consistent:
        blockers.append("citic_source_scope_batch_account_binding_conflict")
    if valid_scope_reviews and not declared_scope_consistent:
        blockers.append("citic_source_scope_batch_declared_scope_conflict")
    if reviewed_source_count > effective_source_count:
        blockers.append("citic_source_scope_batch_review_count_exceeds_sources")

    integrity_blockers = {
        "citic_source_scope_batch_source_count_invalid",
        "citic_source_scope_batch_query_window_review_invalid",
        "citic_source_scope_batch_review_invalid",
        "citic_source_scope_batch_account_binding_conflict",
        "citic_source_scope_batch_declared_scope_conflict",
        "citic_source_scope_batch_review_count_exceeds_sources",
    }
    if any(blocker in integrity_blockers for blocker in blockers):
        integrity_status = "blocked"
    elif effective_source_count == 0:
        integrity_status = "not_available"
    elif not all_current_sources_reviewed:
        integrity_status = "partial"
    else:
        integrity_status = "clear"

    consistent_scope = next(iter(declared_scopes), None)
    consistent_account = next(iter(account_bindings), None)
    core: dict[str, object] = {
        "schema_version": CITIC_SOURCE_SCOPE_BATCH_ASSESSMENT_SCHEMA_VERSION,
        "status": "blocked",
        "integrity_status": integrity_status,
        "source_count": effective_source_count,
        "reviewed_source_count": reviewed_source_count,
        "unreviewed_source_count": unreviewed_source_count,
        "invalid_query_window_review_count": invalid_query_review_count,
        "invalid_scope_review_count": invalid_scope_review_count,
        "all_current_sources_reviewed": all_current_sources_reviewed,
        "account_binding_consistent": account_binding_consistent,
        "declared_scope_consistent": declared_scope_consistent,
        "account_scope_bound": account_scope_bound,
        "declared_source_scope_complete": declared_source_scope_complete,
        "no_other_filters_attested": attestations_complete,
        "complete_returned_results_attested": attestations_complete,
        "declared_account_type": (
            consistent_account[2]
            if account_binding_consistent and consistent_account is not None
            else None
        ),
        "declared_market_scopes": (
            list(consistent_scope[0])
            if declared_scope_consistent and consistent_scope is not None
            else []
        ),
        "declared_asset_classes": (
            list(consistent_scope[1])
            if declared_scope_consistent and consistent_scope is not None
            else []
        ),
        "declared_business_types": (
            list(consistent_scope[3])
            if declared_scope_consistent and consistent_scope is not None
            else []
        ),
        "declared_account_value_band": (
            consistent_scope[2]
            if declared_scope_consistent and consistent_scope is not None
            else None
        ),
        "blockers": list(dict.fromkeys(blockers)),
        "required_evidence": [
            "explicit_source_scope_review_for_each_current_source",
            "same_privacy_minimized_account_binding_for_all_sources",
            "consistent_declared_market_asset_value_band_and_business_scope",
            "explicit_non_authorizing_account_value_band",
            "explicit_no_other_filters_attestation",
            "explicit_complete_returned_results_attestation",
            "itemized_settlement_components_and_current_account_snapshots",
        ],
        "complete_account_coverage_proven": False,
        "settlement_components_complete": False,
        "current_account_snapshots_present": False,
        "account_reference_hashes_included": False,
        "source_names_included": False,
        "paths_included": False,
        "events_included": False,
        "transaction_details_included": False,
        "assessment_persisted": False,
        "database_writes_performed": False,
        "provider_contacted": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "limitations": [
            "This assessment verifies only owner-declared scope consistency for the exact pending CITIC exports.",
            "The declared account-value band is query-scope metadata, not a current balance, order limit, or capital authorization.",
            "Complete returned results for a declared query do not prove full account history, itemized settlement, current cash, or current positions.",
        ],
    }
    core["assessment_fingerprint"] = _fingerprint(
        {
            **{key: value for key, value in core.items() if key != "limitations"},
            "review_identities": sorted(
                identity_rows,
                key=lambda row: (
                    str(row["intake_id"]),
                    str(row["source_scope_review_fingerprint"]),
                ),
            ),
        }
    )
    return core


def citic_source_scope_review_response(
    review: CiticSourceScopeReview,
    *,
    source_review_status: str = "follow_up_required",
    query_window_review: CiticSourceQueryWindowReview | None = None,
    query_window_review_verified: bool = False,
) -> dict[str, object]:
    query_window_current = bool(
        query_window_review_verified
        or query_window_review is not None
        and query_window_review.decision == "accepted"
        and review.query_window_review_id == query_window_review.review_id
        and review.query_window_review_fingerprint
        == query_window_review.review_fingerprint
    )
    effective_status = (
        "active"
        if review.decision == "accepted"
        and source_review_status == "follow_up_required"
        and query_window_current
        else (
            "revoked"
            if review.decision == "revoked"
            else (
                "source_closed"
                if source_review_status != "follow_up_required"
                else "query_window_superseded"
            )
        )
    )
    return {
        "review_id": review.review_id,
        "schema_version": review.schema_version,
        "intake_id": review.intake_id,
        "file_fingerprint": review.file_fingerprint,
        "source_preview_fingerprint": review.source_preview_fingerprint,
        "query_window_review_id": review.query_window_review_id,
        "query_window_review_fingerprint": review.query_window_review_fingerprint,
        "account_alias": review.account_alias,
        "account_reference_hash": review.account_reference_hash,
        "account_type": review.account_type,
        "market_scopes": list(review.market_scopes),
        "asset_classes": list(review.asset_classes),
        "account_value_band": review.account_value_band,
        "business_types": list(review.business_types),
        "no_other_filters_attested": review.no_other_filters_attested,
        "complete_returned_results_attested": (
            review.complete_returned_results_attested
        ),
        "source_scope_attested": review.source_scope_attested,
        "decision": review.decision,
        "effective_status": effective_status,
        "supersedes_review_id": review.supersedes_review_id,
        "reviewer": review.reviewer,
        "review_fingerprint": review.review_fingerprint,
        "created_at": review.created_at,
        "reused": review.reused,
        "review_persisted": True,
        "raw_account_identifier_included": False,
        "events_included": False,
        "transaction_details_included": False,
        "source_name_included": False,
        "source_path_included": False,
        "eligible_for_account_truth": False,
        "eligible_for_reconciliation": False,
        "does_not_mutate_broker_evidence": True,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_provider": True,
        "does_not_enable_broker_submission": True,
        "does_not_change_capital_authority": True,
        "account_value_band_is_capital_authority": False,
    }


def _command_response(review: CiticSourceScopeReview) -> dict[str, object]:
    return {
        "schema_version": CITIC_SOURCE_SCOPE_REVIEW_COMMAND_SCHEMA_VERSION,
        "status": "recorded" if review.decision == "accepted" else "revoked",
        "review": citic_source_scope_review_response(
            review,
            query_window_review_verified=True,
        ),
        "source_scope_review_write_performed": not review.reused,
        "writes_only_source_scope_review_store": True,
        "raw_account_identifier_persisted": False,
        "events_persisted": False,
        "does_not_mutate_source_intake": True,
        "does_not_mutate_query_window_review": True,
        "does_not_mutate_broker_evidence": True,
        "does_not_mutate_production_ledger": True,
        "does_not_reconcile_account": True,
        "does_not_contact_provider": True,
        "does_not_enable_broker_submission": True,
        "does_not_change_capital_authority": True,
        "account_value_band_is_capital_authority": False,
    }


def _required_db_path(state: Any) -> Path:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise CiticSourceScopeReviewRejected(
            "citic_source_scope_review_store_not_configured"
        )
    return Path(db_path)


def _sha256_fingerprint_is_valid(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    return bool(
        prefix == "sha256"
        and separator
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
