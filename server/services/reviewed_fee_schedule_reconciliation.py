"""Persisted Account Truth reconciliation for reviewed fee schedules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from account_truth.broker_evidence import (
    BrokerEvidenceReadRejected,
    BrokerEvidenceRepository,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReview,
    EvidenceScopeReviewReadRejected,
    EvidenceScopeReviewRepository,
)
from account_truth.reconciliation import MONEY_RECONCILIATION_TOLERANCE
from account_truth.source_fact_continuity import (
    assess_account_truth_source_fact_history_continuity,
    source_fact_continuity_allows_inheritance,
)
from account_truth.source_fact_lineage import (
    account_truth_scope_review_binding_fingerprint,
    project_account_truth_source_fact_lineage,
)
from server.contracts.reviewed_fee_schedule import (
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
)
from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown
from server.services.reviewed_fee_schedule_commission import (
    validated_notional_envelope,
)
from server.services.reviewed_fee_schedule_policy import (
    NOTIONAL_ENVELOPE_SCHEMA_VERSION,
    REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    SUPPORTED_ASSET_CLASSES,
    TRADE_EVENT_TYPES,
    decimal_value,
    event_date,
    fingerprint_payload,
    mapping_payload,
    normalize_asset_class,
    normalize_reviewed_asset_classes,
    reviewed_asset_classes_from_preview,
)
from server.services.reviewed_fee_schedule_repository import (
    ReviewedFeeScheduleReviewRepository,
)


def compare_schedule_to_events(
    *,
    schedule: Mapping[str, Any],
    events: Sequence[Any],
    start_date: str,
    end_date: str,
    reviewed_asset_classes: Sequence[str],
) -> dict[str, Any]:
    issues: list[str] = []
    normalized_reviewed_assets = normalize_reviewed_asset_classes(
        reviewed_asset_classes
    )
    source_trade_events = [
        event
        for event in events
        if not bool(getattr(event, "is_row_duplicate", False))
        and str(getattr(event, "event_type", "")) in TRADE_EVENT_TYPES
    ]
    trade_events = [
        event
        for event in source_trade_events
        if normalize_asset_class(getattr(event, "asset_class", ""))
        in normalized_reviewed_assets
    ]
    excluded_asset_counts: dict[str, int] = {}
    for event in source_trade_events:
        asset_class = normalize_asset_class(getattr(event, "asset_class", ""))
        if asset_class not in normalized_reviewed_assets:
            excluded_asset_counts[asset_class or "unknown"] = (
                excluded_asset_counts.get(asset_class or "unknown", 0) + 1
            )
    if not trade_events:
        issues.append("reviewed_fee_schedule_trade_evidence_missing")
    side_counts = {"buy": 0, "sell": 0}
    asset_counts: dict[str, int] = {}
    asset_side_counts: dict[str, dict[str, int]] = {}
    matched_notional_limits: dict[str, dict[str, Decimal | int]] = {}
    match_count = 0
    mismatch_counts = {"fee": 0, "tax": 0, "transfer_fee": 0}
    mismatch_counts_by_asset_and_side: dict[tuple[str, str], dict[str, int]] = {}
    maximum_differences = {key: Decimal("0") for key in mismatch_counts}
    config = _config_for_schedule(schedule)

    for event in trade_events:
        occurred_date = event_date(getattr(event, "occurred_at", ""))
        if occurred_date is None or not (start_date <= occurred_date <= end_date):
            issues.append("reviewed_fee_schedule_trade_outside_effective_window")
            continue
        event_type = str(getattr(event, "event_type", ""))
        side = "buy" if event_type == "trade_buy" else "sell"
        asset_class = normalize_asset_class(getattr(event, "asset_class", ""))
        if asset_class not in SUPPORTED_ASSET_CLASSES:
            issues.append("reviewed_fee_schedule_trade_asset_unsupported")
            continue
        quantity = decimal_value(getattr(event, "quantity", None))
        price = decimal_value(getattr(event, "price", None))
        if quantity is None or quantity <= 0 or price is None or price <= 0:
            issues.append("reviewed_fee_schedule_trade_terms_invalid")
            continue
        resolved = resolve_manual_trade_fee_breakdown(
            config,
            asset_class=asset_class,
            direction=side,
            quantity=float(quantity),
            price=float(price),
            symbol=str(getattr(event, "symbol", "")),
        )
        if resolved is None:
            issues.append("reviewed_fee_schedule_trade_model_unavailable")
            continue
        expected_components = {
            key: decimal_value(resolved.fee_breakdown_json.get(key))
            for key in ("commission", "other_fees", "stamp_tax", "transfer_fee")
        }
        if any(value is None for value in expected_components.values()):
            issues.append("reviewed_fee_schedule_trade_component_invalid")
            continue
        expected = {
            "fee": expected_components["commission"]
            + expected_components["other_fees"],
            "tax": expected_components["stamp_tax"],
            "transfer_fee": expected_components["transfer_fee"],
        }
        observed = {
            "fee": decimal_value(getattr(event, "fee", None)),
            "tax": decimal_value(getattr(event, "tax", None)),
            "transfer_fee": decimal_value(getattr(event, "transfer_fee", None)),
        }
        if any(value is None for value in (*expected.values(), *observed.values())):
            issues.append("reviewed_fee_schedule_trade_component_invalid")
            continue
        row_matches = True
        for component in mismatch_counts:
            difference = abs(observed[component] - expected[component])
            maximum_differences[component] = max(
                maximum_differences[component], difference
            )
            if difference > MONEY_RECONCILIATION_TOLERANCE:
                mismatch_counts[component] += 1
                grouped = mismatch_counts_by_asset_and_side.setdefault(
                    (asset_class, side),
                    {"fee": 0, "tax": 0, "transfer_fee": 0},
                )
                grouped[component] += 1
                row_matches = False
        side_counts[side] += 1
        asset_counts[asset_class] = asset_counts.get(asset_class, 0) + 1
        per_asset_sides = asset_side_counts.setdefault(
            asset_class,
            {"buy": 0, "sell": 0},
        )
        per_asset_sides[side] += 1
        if row_matches:
            match_count += 1
            gross_amount = quantity * price
            limit = matched_notional_limits.setdefault(
                asset_class,
                {
                    "maximum_gross_amount": Decimal("0"),
                    "matched_trade_count": 0,
                },
            )
            limit["maximum_gross_amount"] = max(
                Decimal(str(limit["maximum_gross_amount"])),
                gross_amount,
            )
            limit["matched_trade_count"] = int(limit["matched_trade_count"]) + 1

    for side, count in side_counts.items():
        if count == 0:
            issues.append(f"reviewed_fee_schedule_{side}_coverage_missing")
    for asset_class, counts in sorted(asset_side_counts.items()):
        for side, count in counts.items():
            if count == 0:
                issues.append(
                    "reviewed_fee_schedule_asset_side_coverage_missing:"
                    f"{asset_class}:{side}"
                )
    if any(mismatch_counts.values()):
        issues.append("reviewed_fee_schedule_component_mismatch")
    envelope_core = {
        "schema_version": NOTIONAL_ENVELOPE_SCHEMA_VERSION,
        "enforcement_mode": "maximum_matched_historical_gross_by_asset_class",
        "asset_classes": sorted(matched_notional_limits),
        "limits": {
            asset_class: {
                "maximum_gross_amount": format(
                    Decimal(str(values["maximum_gross_amount"])),
                    "f",
                ),
                "matched_trade_count": int(values["matched_trade_count"]),
            }
            for asset_class, values in sorted(matched_notional_limits.items())
        },
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
    }
    return {
        "status": "pass" if not issues else "blocked",
        "reviewed_asset_classes": list(normalized_reviewed_assets),
        "source_trade_count": len(source_trade_events),
        "trade_count": len(trade_events),
        "excluded_trade_count": len(source_trade_events) - len(trade_events),
        "excluded_asset_class_counts": dict(sorted(excluded_asset_counts.items())),
        "matched_trade_count": match_count,
        "side_counts": side_counts,
        "asset_class_counts": dict(sorted(asset_counts.items())),
        "asset_side_counts": {
            asset_class: dict(counts)
            for asset_class, counts in sorted(asset_side_counts.items())
        },
        "mismatch_counts": mismatch_counts,
        "mismatch_counts_by_asset_and_side": [
            {"asset_class": asset_class, "side": side, **counts}
            for (asset_class, side), counts in sorted(
                mismatch_counts_by_asset_and_side.items()
            )
        ],
        "maximum_absolute_differences": {
            key: format(value, "f") for key, value in maximum_differences.items()
        },
        "tolerance": format(MONEY_RECONCILIATION_TOLERANCE, "f"),
        "reconciled_notional_envelope": {
            **envelope_core,
            "evidence_fingerprint": fingerprint_payload(envelope_core),
        },
        "issues": list(dict.fromkeys(issues)),
    }


def active_review_matches_fee_evidence(
    db: Any,
    fee_evidence: Mapping[str, Any],
    *,
    as_of_date: str | None = None,
) -> list[str]:
    """Recheck persisted review identity without config or provider access."""

    path = getattr(db, "_path", None)
    if path is None:
        return ["reviewed_fee_schedule_database_unavailable"]
    try:
        review = ReviewedFeeScheduleReviewRepository(path).get_latest_review()
    except ReviewedFeeScheduleReadRejected as exc:
        return [exc.code]
    if review is None:
        return ["reviewed_fee_schedule_review_missing"]
    blockers: list[str] = []
    if review.decision != "accepted":
        blockers.append("reviewed_fee_schedule_review_revoked")
    try:
        notional_limits, notional_envelope_fingerprint = validated_notional_envelope(
            mapping_payload(
                mapping_payload(review.preview).get("component_reconciliation")
            ).get("reconciled_notional_envelope")
        )
    except ReviewedFeeScheduleRejected as exc:
        blockers.append(exc.code)
        notional_limits = {}
        notional_envelope_fingerprint = ""
    expected = _expected_fee_evidence(
        review,
        notional_limits=notional_limits,
        notional_envelope_fingerprint=notional_envelope_fingerprint,
    )
    for key, value in expected.items():
        if fee_evidence.get(key) != value:
            blockers.append(f"reviewed_fee_schedule_binding_mismatch:{key}")
    blockers.extend(_account_truth_lineage_blockers(path, review))
    if as_of_date:
        try:
            normalized = date.fromisoformat(str(as_of_date)[:10]).isoformat()
        except ValueError:
            blockers.append("reviewed_fee_schedule_action_date_invalid")
        else:
            if not (
                review.effective_start_date <= normalized <= review.effective_end_date
            ):
                blockers.append("reviewed_fee_schedule_action_date_not_covered")
    return list(dict.fromkeys(blockers))


def _expected_fee_evidence(
    review: Any,
    *,
    notional_limits: Mapping[str, Decimal],
    notional_envelope_fingerprint: str,
) -> dict[str, Any]:
    expected = {
        "fee_schedule_review_id": review.review_id,
        "fee_schedule_review_fingerprint": review.review_fingerprint,
        "fee_schedule_fingerprint": review.schedule_fingerprint,
        "fee_schedule_preview_fingerprint": review.preview_fingerprint,
        "account_truth_import_run_id": review.account_truth_import_run_id,
        "account_truth_source_fingerprint": review.account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": review.account_truth_scope_fingerprint,
        "fee_notional_envelope_enforced": True,
        "fee_notional_envelope_fingerprint": notional_envelope_fingerprint,
        "fee_notional_covered_asset_classes": sorted(notional_limits),
    }
    if review.preview.get("schema_version") == (
        REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION
    ):
        expected["fee_schedule_reviewed_asset_classes"] = list(
            reviewed_asset_classes_from_preview(review.preview)
        )
    return expected


def _account_truth_lineage_blockers(path: Any, review: Any) -> list[str]:
    blockers: list[str] = []
    try:
        broker_repository = BrokerEvidenceRepository(path)
        import_runs = broker_repository.list_import_runs(limit=1)
        reviewed_import = broker_repository.get_import_run(
            review.account_truth_import_run_id
        )
        current_import = import_runs[0] if import_runs else None
        scope_repository = EvidenceScopeReviewRepository(path)
        latest_scope_review = (
            _current_scope_review_for_lineage(
                broker_repository=broker_repository,
                review_repository=scope_repository,
                current_import=current_import,
            )
            if current_import is not None
            else None
        )
        continuity = (
            assess_account_truth_source_fact_history_continuity(
                repository=broker_repository,
                current_import=current_import,
                reviewed_import=reviewed_import,
            )
            if current_import is not None and reviewed_import is not None
            else {}
        )
        original_scope_review = scope_repository.get_latest_review(
            review.account_truth_import_run_id
        )
    except (BrokerEvidenceReadRejected, EvidenceScopeReviewReadRejected) as exc:
        return [str(getattr(exc, "code", "account_truth_review_read_failed"))]

    lineage_history_continuous = bool(
        current_import is not None
        and reviewed_import is not None
        and source_fact_continuity_allows_inheritance(continuity)
    )
    if current_import is None or reviewed_import is None:
        blockers.append("reviewed_fee_schedule_account_truth_import_missing")
    elif not lineage_history_continuous:
        blockers.append("reviewed_fee_schedule_account_truth_import_drift")
    if latest_scope_review is None:
        blockers.append("reviewed_fee_schedule_account_truth_scope_review_missing")
    elif latest_scope_review.decision != "accepted":
        blockers.append("reviewed_fee_schedule_account_truth_scope_review_revoked")
    elif latest_scope_review.account_reference_hash != review.account_reference_hash:
        blockers.append("reviewed_fee_schedule_account_reference_drift")
    elif current_import is not None:
        blockers.extend(
            _scope_binding_blockers(
                review=review,
                latest_scope_review=latest_scope_review,
                original_scope_review=original_scope_review,
                continuity=continuity,
            )
        )
    return blockers


def _scope_binding_blockers(
    *,
    review: Any,
    latest_scope_review: EvidenceScopeReview,
    original_scope_review: EvidenceScopeReview | None,
    continuity: Mapping[str, Any],
) -> list[str]:
    if (
        str(review.preview.get("schema_version") or "")
        == REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION
        and review.preview.get("account_truth_binding_mode")
        == "stable_source_fact_lineage"
    ):
        current_source_fingerprint = str(
            continuity.get("reviewed_source_fact_fingerprint") or ""
        )
        current_scope_fingerprint = account_truth_scope_review_binding_fingerprint(
            latest_scope_review,
            source_fact_fingerprint=current_source_fingerprint,
        )
        blockers: list[str] = []
        if review.account_truth_source_fingerprint != current_source_fingerprint:
            blockers.append("reviewed_fee_schedule_account_truth_source_lineage_drift")
        if review.account_truth_scope_fingerprint != current_scope_fingerprint:
            blockers.append("reviewed_fee_schedule_account_truth_scope_binding_drift")
        return blockers
    if (
        original_scope_review is None
        or latest_scope_review.review_id != original_scope_review.review_id
    ):
        return ["reviewed_fee_schedule_account_truth_scope_binding_drift"]
    return []


def current_scope_review_for_lineage(
    *,
    broker_repository: BrokerEvidenceRepository,
    review_repository: EvidenceScopeReviewRepository,
    current_import: Any,
) -> EvidenceScopeReview | None:
    """Find an exact or safely inherited scope review for a persisted import."""

    return _current_scope_review_for_lineage(
        broker_repository=broker_repository,
        review_repository=review_repository,
        current_import=current_import,
    )


def _current_scope_review_for_lineage(
    *,
    broker_repository: BrokerEvidenceRepository,
    review_repository: EvidenceScopeReviewRepository,
    current_import: Any,
) -> EvidenceScopeReview | None:
    exact = review_repository.get_latest_review(current_import.import_run_id)
    if exact is not None:
        return exact
    current_lineage = _source_fact_lineage_for_import(
        broker_repository,
        current_import,
    )
    if (
        current_lineage.get("status") != "pass"
        or int(current_lineage.get("derived_snapshot_count") or 0) < 1
    ):
        return None
    candidates = review_repository.list_latest_reviews_across_imports(limit=1000)
    if len(candidates) == 1000:
        raise EvidenceScopeReviewReadRejected(
            "account_truth_evidence_scope_review_lineage_scan_truncated"
        )
    for candidate in candidates:
        candidate_import = broker_repository.get_import_run(candidate.import_run_id)
        if candidate_import is None:
            continue
        continuity = assess_account_truth_source_fact_history_continuity(
            repository=broker_repository,
            current_import=current_import,
            reviewed_import=candidate_import,
        )
        if source_fact_continuity_allows_inheritance(continuity):
            return candidate
    return None


def component_reconciliation_extends_reviewed(
    stored_value: object,
    current_value: object,
) -> bool:
    """Accept only an all-matched superset of reviewed fee observations."""

    stored = mapping_payload(stored_value)
    current = mapping_payload(current_value)
    stored_trade_count = _nonnegative_int(stored.get("trade_count"))
    current_trade_count = _nonnegative_int(current.get("trade_count"))
    stored_matched = _nonnegative_int(stored.get("matched_trade_count"))
    current_matched = _nonnegative_int(current.get("matched_trade_count"))
    if None in {
        stored_trade_count,
        current_trade_count,
        stored_matched,
        current_matched,
    }:
        return False
    if stored_matched != stored_trade_count or current_matched != current_trade_count:
        return False
    if current_trade_count < stored_trade_count:
        return False
    if current.get("mismatch_counts_by_asset_and_side"):
        return False
    return all(
        _count_tree_is_superset(stored.get(key), current.get(key))
        for key in ("side_counts", "asset_side_counts")
    )


def _count_tree_is_superset(stored_value: object, current_value: object) -> bool:
    stored = mapping_payload(stored_value)
    current = mapping_payload(current_value)
    for key, stored_item in stored.items():
        if isinstance(stored_item, Mapping):
            if not _count_tree_is_superset(stored_item, current.get(key)):
                return False
            continue
        stored_count = _nonnegative_int(stored_item)
        current_count = _nonnegative_int(current.get(key))
        if (
            stored_count is None
            or current_count is None
            or current_count < stored_count
        ):
            return False
    return True


def _nonnegative_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _source_fact_lineage_for_import(
    repository: BrokerEvidenceRepository,
    import_run: Any,
) -> dict[str, object]:
    events = repository.list_events(
        import_run.duplicate_of_import_run_id or import_run.import_run_id
    )
    return project_account_truth_source_fact_lineage(
        import_run=import_run,
        events=events,
    )


def _config_for_schedule(schedule: Mapping[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        account_commission_rate=schedule["stock_a_commission_rate"],
        account_min_commission=schedule["stock_a_min_commission"],
        broker_fee_schedule=SimpleNamespace(**dict(schedule)),
    )


__all__ = [
    "active_review_matches_fee_evidence",
    "compare_schedule_to_events",
    "component_reconciliation_extends_reviewed",
    "current_scope_review_for_lineage",
]
