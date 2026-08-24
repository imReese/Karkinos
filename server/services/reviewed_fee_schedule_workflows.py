"""Application workflows for reviewed fee schedule preview and resolution."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Mapping, Sequence

from account_truth.broker_evidence import (
    BrokerEvidenceReadRejected,
    BrokerEvidenceRepository,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReviewReadRejected,
    EvidenceScopeReviewRepository,
)
from account_truth.source_fact_continuity import (
    assess_account_truth_source_fact_history_continuity,
    source_fact_continuity_allows_inheritance,
)
from server.contracts.reviewed_fee_schedule import (
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReview,
)
from server.services.reviewed_fee_schedule_commission import (
    ReviewedFeeScheduleResolution,
    build_commission_calculator,
    reviewed_cost_model_reference,
    validated_notional_envelope,
)
from server.services.reviewed_fee_schedule_policy import (
    REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    SHA256_PATTERN,
    SUPPORTED_ASSET_CLASSES,
    SUPPORTED_REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSIONS,
    account_truth_clock,
    database_path,
    date_window,
    fingerprint_payload,
    mapping_payload,
    normalize_asset_class,
    normalize_reviewed_asset_classes,
    normalize_schedule,
    reviewed_asset_classes_from_preview,
    schedule_from_config,
    validated_preview,
)
from server.services.reviewed_fee_schedule_reconciliation import (
    compare_schedule_to_events,
    component_reconciliation_extends_reviewed,
)
from server.services.reviewed_fee_schedule_repository import (
    ReviewedFeeScheduleReviewRepository,
)

EvidenceBuilder = Callable[..., Mapping[str, Any]]
PreviewBuilder = Callable[..., dict[str, Any]]


def build_reviewed_fee_schedule_preview_workflow(
    state: Any,
    *,
    effective_start_date: str,
    effective_end_date: str,
    reviewed_asset_classes: Sequence[str] | None,
    schedule_override: Mapping[str, Any] | None,
    account_truth_as_of: datetime | None,
    evidence_readiness_builder: EvidenceBuilder,
    promotion_evidence_builder: EvidenceBuilder,
) -> dict[str, Any]:
    """Compare safe schedule terms with exact Account Truth at a bound clock."""

    start_date, end_date = date_window(effective_start_date, effective_end_date)
    normalized_reviewed_assets = normalize_reviewed_asset_classes(
        reviewed_asset_classes
    )
    schedule = (
        normalize_schedule(schedule_override)
        if schedule_override is not None
        else schedule_from_config(getattr(state, "config", None))
    )
    schedule_fingerprint = fingerprint_payload(schedule)
    bound_clock = account_truth_clock(account_truth_as_of)
    readiness = _build_bound_evidence(
        evidence_readiness_builder,
        state,
        clock=bound_clock,
    )
    promotion = _build_bound_evidence(
        promotion_evidence_builder,
        state,
        clock=bound_clock,
    )
    evidence_scope = mapping_payload(readiness.get("evidence_scope"))
    account_binding = mapping_payload(evidence_scope.get("account_binding"))
    scope_review = mapping_payload(evidence_scope.get("review"))
    source_fact_lineage = mapping_payload(evidence_scope.get("source_fact_lineage"))
    account_alias = str(account_binding.get("account_alias") or "")
    account_reference_hash = str(account_binding.get("account_reference_hash") or "")
    import_run_id = str(readiness.get("account_truth_import_run_id") or "")
    reviewed_import_run_id = str(
        scope_review.get("reviewed_import_run_id") or import_run_id
    )
    source_fingerprint = str(
        evidence_scope.get("review_binding_source_fact_fingerprint")
        or source_fact_lineage.get("source_fact_fingerprint")
        or promotion.get("source_fingerprint")
        or ""
    )
    scope_fingerprint = str(
        evidence_scope.get("review_binding_fingerprint")
        or evidence_scope.get("evidence_fingerprint")
        or ""
    )
    binding_mode = (
        "stable_source_fact_lineage"
        if source_fact_lineage.get("status") == "pass"
        and evidence_scope.get("review_binding_fingerprint")
        else "legacy_exact_import"
    )
    issues = _account_truth_preview_issues(
        readiness=readiness,
        promotion=promotion,
        import_run_id=import_run_id,
        account_alias=account_alias,
        account_reference_hash=account_reference_hash,
        source_fingerprint=source_fingerprint,
        scope_fingerprint=scope_fingerprint,
        schedule=schedule,
    )
    events: Sequence[Any] = ()
    db_path = database_path(state)
    if db_path is None or not import_run_id:
        issues.append("reviewed_fee_schedule_account_truth_source_missing")
    else:
        repository = BrokerEvidenceRepository(db_path)
        import_run = repository.get_import_run(import_run_id)
        if import_run is None:
            issues.append("reviewed_fee_schedule_account_truth_import_missing")
        else:
            events = repository.list_events(
                import_run.duplicate_of_import_run_id or import_run.import_run_id
            )
    comparison = compare_schedule_to_events(
        schedule=schedule,
        events=events,
        start_date=start_date,
        end_date=end_date,
        reviewed_asset_classes=normalized_reviewed_assets,
    )
    issues.extend(comparison["issues"])
    issues = list(dict.fromkeys(issues))
    core = {
        "schema_version": REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
        "status": "ready" if not issues else "blocked",
        "schedule": schedule,
        "schedule_fingerprint": schedule_fingerprint,
        "effective_start_date": start_date,
        "effective_end_date": end_date,
        "reviewed_asset_classes": list(normalized_reviewed_assets),
        "account_truth_import_run_id": reviewed_import_run_id,
        "account_truth_source_fingerprint": source_fingerprint,
        "account_truth_scope_fingerprint": scope_fingerprint,
        "account_truth_binding_mode": binding_mode,
        "account_reference_hash": account_reference_hash,
        "account_truth_readiness_status": readiness.get("status"),
        "account_truth_promotion_status": promotion.get("status"),
        "component_reconciliation": {
            key: value for key, value in comparison.items() if key != "issues"
        },
        "issues": issues,
        "persisted_broker_events_only": True,
        "stores_broker_event_details": False,
        "provider_contacted": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    return {**core, "preview_fingerprint": fingerprint_payload(core)}


def build_reviewed_fee_schedule_review_status_workflow(
    state: Any,
    *,
    as_of_date: str | None,
    preview_builder: PreviewBuilder,
    evidence_readiness_builder: EvidenceBuilder,
    promotion_evidence_builder: EvidenceBuilder,
) -> dict[str, Any]:
    """Project the current review and optional action-date coverage read-only."""

    db_path = database_path(state)
    if db_path is None:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_database_unavailable"
        )
    review = ReviewedFeeScheduleReviewRepository(db_path).get_latest_review()
    if review is None:
        return _review_status_payload(
            status="missing",
            review=None,
            blockers=["reviewed_fee_schedule_review_missing"],
            current_preview_fingerprint=None,
        )
    if review.decision != "accepted":
        return _review_status_payload(
            status="revoked",
            review=review,
            blockers=["reviewed_fee_schedule_review_revoked"],
            current_preview_fingerprint=None,
        )
    try:
        current_preview = preview_builder(
            state,
            effective_start_date=review.effective_start_date,
            effective_end_date=review.effective_end_date,
            reviewed_asset_classes=reviewed_asset_classes_from_preview(review.preview),
            schedule_override=review.schedule,
        )
    except ReviewedFeeScheduleRejected as exc:
        return _review_status_payload(
            status="blocked",
            review=review,
            blockers=[exc.code],
            current_preview_fingerprint=None,
        )
    blockers = [str(item) for item in current_preview.get("issues") or []]
    if not review_matches_current_preview(
        state=state,
        review=review,
        current_preview=current_preview,
        evidence_readiness_builder=evidence_readiness_builder,
        promotion_evidence_builder=promotion_evidence_builder,
    ):
        blockers.append("reviewed_fee_schedule_source_drift")
    if as_of_date is not None:
        try:
            normalized_date = date.fromisoformat(str(as_of_date)[:10]).isoformat()
        except ValueError:
            blockers.append("reviewed_fee_schedule_action_date_invalid")
        else:
            if not (
                review.effective_start_date
                <= normalized_date
                <= review.effective_end_date
            ):
                blockers.append("reviewed_fee_schedule_action_date_not_covered")
    blockers = list(dict.fromkeys(blockers))
    return _review_status_payload(
        status="blocked" if blockers else "active",
        review=review,
        blockers=blockers,
        current_preview_fingerprint=current_preview.get("preview_fingerprint"),
    )


def resolve_reviewed_fee_schedule_workflow(
    state: Any,
    *,
    start_date: str,
    end_date: str,
    universe: Sequence[str],
    asset_classes: Sequence[str],
    expected_cost_model_reference: str | None,
    account_truth_as_of: datetime | None,
    preview_builder: PreviewBuilder,
    evidence_readiness_builder: EvidenceBuilder,
    promotion_evidence_builder: EvidenceBuilder,
) -> ReviewedFeeScheduleResolution:
    """Resolve one active review and recheck its current Account Truth binding."""

    db_path = database_path(state)
    if db_path is None:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_database_unavailable")
    review = ReviewedFeeScheduleReviewRepository(db_path).get_latest_review()
    if review is None:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_review_missing")
    if review.decision != "accepted":
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_review_revoked")
    requested_start, requested_end = date_window(start_date, end_date)
    account_truth_clock(account_truth_as_of)
    if (
        account_truth_as_of is not None
        and account_truth_as_of.date().isoformat() != requested_end
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_account_truth_as_of_date_mismatch"
        )
    if (
        requested_start < review.effective_start_date
        or requested_end > review.effective_end_date
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_backtest_window_not_covered"
        )
    normalized_assets = tuple(normalize_asset_class(item) for item in asset_classes)
    if (
        not universe
        or len(universe) != len(normalized_assets)
        or any(item not in SUPPORTED_ASSET_CLASSES for item in normalized_assets)
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_backtest_assets_not_covered"
        )
    reviewed_asset_classes = reviewed_asset_classes_from_preview(review.preview)
    uncovered_review_assets = sorted(
        set(normalized_assets) - set(reviewed_asset_classes)
    )
    if uncovered_review_assets:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_backtest_assets_outside_reviewed_scope:"
            + ",".join(uncovered_review_assets)
        )
    preview = preview_builder(
        state,
        effective_start_date=review.effective_start_date,
        effective_end_date=review.effective_end_date,
        reviewed_asset_classes=reviewed_asset_classes,
        schedule_override=review.schedule,
        account_truth_as_of=account_truth_as_of,
    )
    if preview.get("status") != "ready":
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_current_reconciliation_blocked"
        )
    if not review_matches_current_preview(
        state=state,
        review=review,
        current_preview=preview,
        account_truth_as_of=account_truth_as_of,
        evidence_readiness_builder=evidence_readiness_builder,
        promotion_evidence_builder=promotion_evidence_builder,
    ):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_source_drift")
    notional_limits, notional_envelope_fingerprint = validated_notional_envelope(
        mapping_payload(review.preview.get("component_reconciliation")).get(
            "reconciled_notional_envelope"
        )
    )
    uncovered_assets = sorted(set(normalized_assets) - set(notional_limits))
    if uncovered_assets:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_asset_notional_envelope_missing:"
            + ",".join(uncovered_assets)
        )
    cost_model_reference = reviewed_cost_model_reference(review)
    if (
        expected_cost_model_reference is not None
        and expected_cost_model_reference != cost_model_reference
    ):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_reference_mismatch")
    calculator = build_commission_calculator(
        review.schedule,
        universe=universe,
        asset_classes=normalized_assets,
        fee_rule_version=cost_model_reference,
        notional_limits=notional_limits,
    )
    fee_evidence = _resolved_fee_evidence(
        review=review,
        reviewed_asset_classes=reviewed_asset_classes,
        notional_limits=notional_limits,
        notional_envelope_fingerprint=notional_envelope_fingerprint,
        account_truth_as_of=account_truth_as_of,
    )
    return ReviewedFeeScheduleResolution(
        cost_model_reference=cost_model_reference,
        commission_calc=calculator,
        fee_evidence=fee_evidence,
        review=review,
    )


def review_matches_current_preview(
    *,
    state: Any,
    review: ReviewedFeeScheduleReview,
    current_preview: Mapping[str, Any],
    evidence_readiness_builder: EvidenceBuilder,
    promotion_evidence_builder: EvidenceBuilder,
    account_truth_as_of: datetime | None = None,
) -> bool:
    """Permit exact replay or a reconciled, materially continuous extension."""

    if current_preview.get("preview_fingerprint") == review.preview_fingerprint:
        return True
    stored_preview = validated_preview(review.preview)
    stored_schema_version = stored_preview.get("schema_version")
    if (
        stored_schema_version
        not in SUPPORTED_REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSIONS
    ):
        return False
    if current_preview.get("status") != "ready" or current_preview.get("issues"):
        return False
    current_assets = reviewed_asset_classes_from_preview(current_preview)
    stored_assets = reviewed_asset_classes_from_preview(stored_preview)
    if stored_schema_version in {
        "karkinos.account_truth.reviewed_fee_schedule_preview.v1",
        "karkinos.account_truth.reviewed_fee_schedule_preview.v2",
    }:
        if current_assets != tuple(sorted(SUPPORTED_ASSET_CLASSES)):
            return False
    elif current_assets != stored_assets:
        return False
    stable_fields = (
        "status",
        "schedule",
        "schedule_fingerprint",
        "effective_start_date",
        "effective_end_date",
        "account_reference_hash",
        "persisted_broker_events_only",
        "stores_broker_event_details",
        "provider_contacted",
        "authorizes_execution",
        "changes_capital_authority",
    )
    if any(
        stored_preview.get(key) != current_preview.get(key) for key in stable_fields
    ):
        return False
    if not component_reconciliation_extends_reviewed(
        stored_preview.get("component_reconciliation"),
        current_preview.get("component_reconciliation"),
    ):
        return False
    db_path = database_path(state)
    if db_path is None:
        return False
    try:
        repository = BrokerEvidenceRepository(db_path)
        reviewed_import = repository.get_import_run(review.account_truth_import_run_id)
        bound_clock = account_truth_clock(account_truth_as_of)
        promotion = _build_bound_evidence(
            promotion_evidence_builder,
            state,
            clock=bound_clock,
        )
        current_import_id = str(promotion.get("import_run_id") or "")
        current_import = repository.get_import_run(current_import_id)
        if reviewed_import is None or current_import is None:
            return False
        continuity = assess_account_truth_source_fact_history_continuity(
            repository=repository,
            current_import=current_import,
            reviewed_import=reviewed_import,
        )
        readiness = _build_bound_evidence(
            evidence_readiness_builder,
            state,
            clock=bound_clock,
        )
        original_scope_review = EvidenceScopeReviewRepository(
            db_path
        ).get_latest_review(review.account_truth_import_run_id)
    except (BrokerEvidenceReadRejected, EvidenceScopeReviewReadRejected):
        return False
    if not source_fact_continuity_allows_inheritance(continuity):
        return False
    current_scope = mapping_payload(readiness.get("evidence_scope"))
    current_scope_review = mapping_payload(current_scope.get("review"))
    return bool(
        readiness.get("status") == "ready"
        and original_scope_review is not None
        and original_scope_review.decision == "accepted"
        and current_scope_review.get("review_id") == original_scope_review.review_id
        and original_scope_review.account_reference_hash
        == review.account_reference_hash
    )


def _account_truth_preview_issues(
    *,
    readiness: Mapping[str, Any],
    promotion: Mapping[str, Any],
    import_run_id: str,
    account_alias: str,
    account_reference_hash: str,
    source_fingerprint: str,
    scope_fingerprint: str,
    schedule: Mapping[str, Any],
) -> list[str]:
    issues: list[str] = []
    if readiness.get("status") != "ready":
        issues.append("reviewed_fee_schedule_account_truth_not_ready")
    if promotion.get("status") != "clear":
        issues.append("reviewed_fee_schedule_account_truth_promotion_blocked")
    if str(promotion.get("import_run_id") or "") != import_run_id:
        issues.append("reviewed_fee_schedule_account_truth_import_mismatch")
    if not account_alias or schedule["account_profile_id"] != account_alias:
        issues.append("reviewed_fee_schedule_account_binding_mismatch")
    if not SHA256_PATTERN.fullmatch(account_reference_hash):
        issues.append("reviewed_fee_schedule_account_reference_invalid")
    if not SHA256_PATTERN.fullmatch(source_fingerprint):
        issues.append("reviewed_fee_schedule_account_truth_source_fingerprint_invalid")
    if not SHA256_PATTERN.fullmatch(scope_fingerprint):
        issues.append("reviewed_fee_schedule_account_truth_scope_fingerprint_invalid")
    return issues


def _build_bound_evidence(
    builder: EvidenceBuilder,
    state: Any,
    *,
    clock: Callable[[], datetime] | None,
) -> Mapping[str, Any]:
    return builder(state) if clock is None else builder(state, clock=clock)


def _review_status_payload(
    *,
    status: str,
    review: ReviewedFeeScheduleReview | None,
    blockers: list[str],
    current_preview_fingerprint: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "review": review.to_json_dict() if review is not None else None,
        "blockers": list(dict.fromkeys(blockers)),
        "current_preview_fingerprint": current_preview_fingerprint,
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def _resolved_fee_evidence(
    *,
    review: ReviewedFeeScheduleReview,
    reviewed_asset_classes: Sequence[str],
    notional_limits: Mapping[str, Any],
    notional_envelope_fingerprint: str,
    account_truth_as_of: datetime | None,
) -> dict[str, Any]:
    evidence = {
        "account_specific": True,
        "fee_schedule_source": "reviewed_account_truth_or_reconciled_fee_schedule",
        "fee_schedule_fingerprint": review.schedule_fingerprint,
        "broker_statement_reconciled": True,
        "fee_schedule_review_id": review.review_id,
        "fee_schedule_review_fingerprint": review.review_fingerprint,
        "fee_schedule_preview_fingerprint": review.preview_fingerprint,
        "account_truth_import_run_id": review.account_truth_import_run_id,
        "account_truth_source_fingerprint": review.account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": review.account_truth_scope_fingerprint,
        "effective_start_date": review.effective_start_date,
        "effective_end_date": review.effective_end_date,
        "fee_notional_envelope_enforced": True,
        "fee_notional_envelope_fingerprint": notional_envelope_fingerprint,
        "fee_notional_covered_asset_classes": sorted(notional_limits),
        "fee_schedule_reviewed_asset_classes": list(reviewed_asset_classes),
    }
    if account_truth_as_of is not None:
        evidence["account_truth_freshness_as_of"] = account_truth_as_of.isoformat()
    return evidence


__all__ = [
    "build_reviewed_fee_schedule_preview_workflow",
    "build_reviewed_fee_schedule_review_status_workflow",
    "resolve_reviewed_fee_schedule_workflow",
    "review_matches_current_preview",
]
